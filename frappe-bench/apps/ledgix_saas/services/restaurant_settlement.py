from __future__ import annotations

import frappe
from frappe.utils import cint, flt, now_datetime, today

from ledgix_saas.services.organization import ensure_branch_access
from ledgix_saas.services.restaurant_audit import log_restaurant_operation
from ledgix_saas.services.restaurant_orders import close_table_session, get_order_payload


MANAGER_ROLES = {"System Manager", "Ledgix Admin", "Ledgix Manager"}
FINAL_ORDER_STATUSES = {"Closed", "Voided"}


def _as_rows(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or [])


def _is_manager():
	return bool(set(frappe.get_roles(frappe.session.user)).intersection(MANAGER_ROLES))


def _lock_order(order_name):
	rows = frappe.db.sql(
		"""
		SELECT name, status, linked_sale
		FROM `tabLedgix Restaurant Order`
		WHERE name=%s
		FOR UPDATE
		""",
		(order_name,),
		as_dict=True,
	)
	if not rows:
		frappe.throw("Restaurant Order was not found.")
	return rows[0]


def _open_shift(branch):
	filters = {"status": "Open", "docstatus": 0, "branch": branch}
	meta = frappe.get_meta("Ledgix POS Shift")
	if meta.has_field("opened_by"):
		filters["opened_by"] = frappe.session.user
	return frappe.db.get_value("Ledgix POS Shift", filters, "name", order_by="creation desc")


def _customer(order):
	if order.customer and frappe.db.exists("Ledgix Customer", order.customer):
		return order.customer
	if frappe.db.exists("Ledgix Customer", "Walk-in Customer"):
		return "Walk-in Customer"
	customer = frappe.db.get_value("Ledgix Customer", {"is_active": 1}, "name", order_by="creation asc")
	if not customer:
		frappe.throw("Create an active Ledgix Customer before restaurant settlement.")
	return customer


def _payment_methods():
	return frappe.get_all(
		"Ledgix Payment Method",
		filters={"enabled": 1},
		fields=["name", "payment_method_name", "method_type", "requires_reference", "allow_change", "sort_order"],
		order_by="sort_order asc, payment_method_name asc",
		limit_page_length=0,
	)


def _active_order_items(order_name):
	return [
		row
		for row in frappe.get_all(
			"Ledgix Restaurant Order Item",
			filters={"restaurant_order": order_name, "is_voided": 0},
			fields=[
				"name", "item", "billable_quantity", "fired_quantity", "line_unit_rate",
				"list_rate", "rate", "modifier_unit_total", "amount", "net_amount",
				"price_list_snapshot", "item_price_reference", "recipe_cost_per_unit",
				"seat_no", "course", "tax_snapshot_locked",
			],
			order_by="creation asc",
			limit_page_length=0,
		)
		if flt(row.billable_quantity) > 0
	]


def _validate_fire_complete(order, rows):
	if not rows:
		frappe.throw("Restaurant Order has no billable items to settle.")
	for row in rows:
		if flt(row.fired_quantity) + 0.000001 < flt(row.billable_quantity):
			frappe.throw(f"Restaurant Order Item {row.name} must be fully fired before settlement.")
		if not cint(row.tax_snapshot_locked):
			frappe.throw(f"Restaurant Order Item {row.name} is missing its locked fiscal snapshot.")


def _item_net_total(order_name):
	return flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(net_amount), 0)
			FROM `tabLedgix Restaurant Order Item`
			WHERE restaurant_order=%s AND is_voided=0 AND billable_quantity > 0
			""",
			(order_name,),
		)[0][0],
		2,
	)


def _normalize_adjustments(order, discount_amount=None, service_charge=None, tip_amount=None):
	discount = flt(order.discount_amount if discount_amount is None else discount_amount, 2)
	service = flt(order.service_charge if service_charge is None else service_charge, 2)
	tip = flt(order.tip_amount if tip_amount is None else tip_amount, 2)
	if min(discount, service, tip) < 0:
		frappe.throw("Discount, Service Charge and Tip cannot be negative.")
	item_total = _item_net_total(order.name)
	if discount > item_total + 0.005:
		frappe.throw("Discount cannot exceed the billable item total.")
	return discount, service, tip, item_total


def _apply_adjustments(order, *, discount_amount=None, service_charge=None, tip_amount=None, reason=None, request_id=None):
	discount, service, tip, item_total = _normalize_adjustments(
		order,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
	)
	privileged_change = (
		abs(discount - flt(order.discount_amount)) > 0.005
		or abs(service - flt(order.service_charge)) > 0.005
	)
	if privileged_change and not _is_manager():
		frappe.throw("Discount or manual Service Charge changes require Manager or Admin access.", frappe.PermissionError)
	if privileged_change and not str(reason or "").strip():
		frappe.throw("Reason is required when Discount or Service Charge changes.")

	changed = any(
		abs(new - old) > 0.005
		for new, old in (
			(discount, flt(order.discount_amount)),
			(service, flt(order.service_charge)),
			(tip, flt(order.tip_amount)),
		)
	)
	if not changed:
		return order

	before = {
		"discount_amount": flt(order.discount_amount, 2),
		"service_charge": flt(order.service_charge, 2),
		"tip_amount": flt(order.tip_amount, 2),
		"grand_total": flt(order.grand_total, 2),
	}
	order.discount_amount = discount
	order.service_charge = service
	order.tip_amount = tip
	order.grand_total = flt(item_total - discount + service + tip, 2)
	order.flags.allow_restaurant_adjustment = True
	order.save(ignore_permissions=True)
	log_restaurant_operation(
		"Adjust Check",
		branch=order.branch,
		reason=reason,
		request_id=request_id,
		table_session=order.table_session,
		restaurant_order=order.name,
		metadata={
			"before": before,
			"after": {
				"discount_amount": discount,
				"service_charge": service,
				"tip_amount": tip,
				"grand_total": flt(order.grand_total, 2),
			},
		},
	)
	return order


def validate_order_adjustment_mutation(doc, method=None):
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = any(
		abs(flt(doc.get(fieldname)) - flt(before.get(fieldname))) > 0.005
		for fieldname in ("discount_amount", "service_charge", "tip_amount")
	)
	if changed and not getattr(doc.flags, "allow_restaurant_adjustment", False):
		frappe.throw(
			"Restaurant Order financial adjustments must be changed through the settlement service.",
			frappe.PermissionError,
		)


def preview_restaurant_settlement(
	order_name,
	*,
	discount_amount=None,
	service_charge=None,
	tip_amount=None,
):
	order = frappe.get_doc("Ledgix Restaurant Order", order_name)
	ensure_branch_access(order.branch)
	if order.status in FINAL_ORDER_STATUSES or order.linked_sale:
		frappe.throw("Restaurant Order is already finalized.")
	rows = _active_order_items(order.name)
	_validate_fire_complete(order, rows)
	discount, service, tip, item_total = _normalize_adjustments(
		order,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
	)
	if (
		abs(discount - flt(order.discount_amount)) > 0.005
		or abs(service - flt(order.service_charge)) > 0.005
	) and not _is_manager():
		frappe.throw("Discount or manual Service Charge changes require Manager or Admin access.", frappe.PermissionError)
	return {
		"order": get_order_payload(order.name),
		"item_net_total": item_total,
		"discount_amount": discount,
		"service_charge": service,
		"tip_amount": tip,
		"grand_total": flt(item_total - discount + service + tip, 2),
		"payment_methods": [dict(row) for row in _payment_methods()],
		"active_shift": _open_shift(order.branch),
		"can_adjust_discount_or_service": _is_manager(),
	}


def _build_sale(order, rows, tenders, client_sale_id, shift):
	sale = frappe.new_doc("Ledgix Sale")
	sale.customer = _customer(order)
	sale.sale_channel = "Retail"
	sale.price_list = order.price_list
	sale.sale_date = today()
	sale.pos_shift = shift
	sale.branch = order.branch
	sale.stock_location = order.stock_location
	sale.client_sale_id = client_sale_id
	sale.restaurant_order = order.name
	sale.restaurant_table_session = order.table_session
	sale.restaurant_order_type = order.order_type
	sale.restaurant_table_snapshot = order.table_name_snapshot
	sale.restaurant_server_snapshot = order.server
	sale.restaurant_covers_snapshot = cint(order.covers)
	sale.restaurant_stock_consumed_at_kitchen = 1
	sale.subtotal_before_discount = flt(sum(flt(row.amount) for row in rows), 2)
	sale.discount_type = "Amount" if flt(order.discount_amount) else ""
	sale.discount_value = flt(order.discount_amount, 2)
	sale.discount_amount = flt(order.discount_amount, 2)
	sale.service_charge = flt(order.service_charge, 2)
	sale.tip_amount = flt(order.tip_amount, 2)
	sale.allow_partial_payment = 0

	for row in rows:
		sale.append("items", {
			"item": row.item,
			"restaurant_order_item": row.name,
			"quantity": flt(row.billable_quantity, 6),
			"price_list_snapshot": row.price_list_snapshot,
			"item_price_reference": row.item_price_reference,
			"list_rate": flt(row.line_unit_rate, 2),
			"base_rate_snapshot": flt(row.rate, 2),
			"modifier_unit_total_snapshot": flt(row.modifier_unit_total, 2),
			"seat_no_snapshot": cint(row.seat_no),
			"course_snapshot": row.course,
			"rate": flt(row.line_unit_rate, 2),
			"price_override": 0,
			"cost_price": flt(row.recipe_cost_per_unit, 4),
		})

	for tender in _as_rows(tenders):
		sale.append("payments", {
			"payment_method": tender.get("payment_method"),
			"amount": flt(tender.get("amount"), 2),
			"reference_no": tender.get("reference_no") or tender.get("reference_number"),
			"notes": tender.get("notes"),
		})
	return sale


def _sale_payload(sale_name):
	sale = frappe.get_doc("Ledgix Sale", sale_name)
	return {
		"name": sale.name,
		"invoice_number": sale.invoice_number,
		"docstatus": cint(sale.docstatus),
		"restaurant_order": sale.get("restaurant_order"),
		"branch": sale.get("branch"),
		"grand_total": flt(sale.grand_total, 2),
		"paid_amount": flt(sale.paid_amount, 2),
		"change_amount": flt(sale.change_amount, 2),
		"payment_status": sale.payment_status,
		"fbr_status": sale.fbr_status,
	}


def settle_restaurant_order(
	order_name,
	*,
	tenders,
	client_sale_id,
	discount_amount=None,
	service_charge=None,
	tip_amount=None,
	adjustment_reason=None,
	request_id=None,
):
	if not client_sale_id:
		frappe.throw("Client Sale ID is required for idempotent restaurant settlement.")

	locked = _lock_order(order_name)
	if locked.linked_sale:
		return {
			"sale": _sale_payload(locked.linked_sale),
			"order": get_order_payload(order_name),
			"idempotent_replay": True,
		}

	existing_sale = frappe.db.get_value("Ledgix Sale", {"client_sale_id": client_sale_id}, ["name", "restaurant_order", "docstatus"], as_dict=True)
	if existing_sale:
		if existing_sale.restaurant_order != order_name:
			frappe.throw("Client Sale ID is already used by another Restaurant Order.")
		if cint(existing_sale.docstatus) == 1:
			return {
				"sale": _sale_payload(existing_sale.name),
				"order": get_order_payload(order_name),
				"idempotent_replay": True,
			}
		frappe.throw(f"Restaurant settlement draft {existing_sale.name} already exists and requires review.")

	order = frappe.get_doc("Ledgix Restaurant Order", order_name)
	ensure_branch_access(order.branch)
	if order.status in FINAL_ORDER_STATUSES:
		frappe.throw(f"Restaurant Order {order.status} cannot be settled.")

	order = _apply_adjustments(
		order,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
		reason=adjustment_reason,
		request_id=f"{request_id}:adjust" if request_id else None,
	)
	rows = _active_order_items(order.name)
	_validate_fire_complete(order, rows)
	shift = _open_shift(order.branch)
	if not shift:
		frappe.throw("Open a POS Shift for this branch before restaurant settlement.")

	sale = _build_sale(order, rows, tenders, client_sale_id, shift)
	sale.insert(ignore_permissions=True)
	sale.submit()

	order = frappe.get_doc("Ledgix Restaurant Order", order.name)
	order.linked_sale = sale.name
	order.status = "Closed"
	order.closed_at = order.closed_at or now_datetime()
	order.closed_by = order.closed_by or frappe.session.user
	order.flags.allow_status_transition = True
	order.save(ignore_permissions=True)

	session_payload = None
	if order.table_session:
		remaining = frappe.db.get_value(
			"Ledgix Restaurant Order",
			{
				"table_session": order.table_session,
				"status": ["not in", ["Closed", "Voided"]],
			},
			"name",
		)
		if not remaining:
			session_payload = close_table_session(order.table_session)

	log_restaurant_operation(
		"Settle Check",
		branch=order.branch,
		reason="Restaurant check finalized into Ledgix Sale",
		request_id=request_id,
		table_session=order.table_session,
		restaurant_order=order.name,
		metadata={
			"sale": sale.name,
			"invoice_number": sale.invoice_number,
			"grand_total": flt(sale.grand_total, 2),
			"paid_amount": flt(sale.paid_amount, 2),
			"change_amount": flt(sale.change_amount, 2),
		},
	)
	frappe.publish_realtime(
		"ledgix_restaurant_order_update",
		{"branch": order.branch, "restaurant_order": order.name, "status": "Closed", "sale": sale.name},
		after_commit=True,
	)
	return {
		"sale": _sale_payload(sale.name),
		"order": get_order_payload(order.name),
		"table_session": session_payload,
		"idempotent_replay": False,
	}
