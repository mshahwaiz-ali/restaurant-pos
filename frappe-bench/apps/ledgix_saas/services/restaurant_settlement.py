from __future__ import annotations

import frappe
from frappe.utils import cint, flt, now_datetime, today

from ledgix_saas.services.organization import ensure_branch_access
from ledgix_saas.services.restaurant_audit import log_restaurant_operation
from ledgix_saas.services.restaurant_charges import build_charge_fiscal_rows
from ledgix_saas.services.restaurant_fiscal import build_discounted_fiscal_rows
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


def _validate_fire_complete(fiscal):
	if not fiscal["rows"]:
		frappe.throw("Restaurant Order has no billable items to settle.")
	for row in fiscal["rows"]:
		if flt(row["fired_quantity"]) + 0.000001 < flt(row["qty"]):
			frappe.throw(f"Restaurant Order Item {row['restaurant_order_item']} must be fully fired before settlement.")


def _normalize_adjustments(order, discount_amount=None, service_charge=None, tip_amount=None, *, persist_charges=False):
	discount = flt(order.discount_amount if discount_amount is None else discount_amount, 2)
	service = flt(order.service_charge if service_charge is None else service_charge, 2)
	tip = flt(order.tip_amount if tip_amount is None else tip_amount, 2)
	if min(discount, service, tip) < 0:
		frappe.throw("Discount, Service Charge and Tip cannot be negative.")
	item_fiscal = build_discounted_fiscal_rows(order.name, discount)
	charge_fiscal = build_charge_fiscal_rows(
		order,
		service_charge=service,
		tip_amount=tip,
		persist=persist_charges,
	)
	return discount, service, tip, item_fiscal, charge_fiscal


def _apply_adjustments(order, *, discount_amount=None, service_charge=None, tip_amount=None, reason=None, request_id=None):
	discount = flt(order.discount_amount if discount_amount is None else discount_amount, 2)
	service = flt(order.service_charge if service_charge is None else service_charge, 2)
	tip = flt(order.tip_amount if tip_amount is None else tip_amount, 2)
	if min(discount, service, tip) < 0:
		frappe.throw("Discount, Service Charge and Tip cannot be negative.")

	privileged_change = (
		abs(discount - flt(order.discount_amount)) > 0.005
		or abs(service - flt(order.service_charge)) > 0.005
	)
	if privileged_change and not _is_manager():
		frappe.throw("Discount or Service Charge changes require Manager or Admin access.", frappe.PermissionError)
	if privileged_change and not str(reason or "").strip():
		frappe.throw("Reason is required when Discount or Service Charge changes.")

	discount, service, tip, item_fiscal, charge_fiscal = _normalize_adjustments(
		order,
		discount_amount=discount,
		service_charge=service,
		tip_amount=tip,
		persist_charges=True,
	)
	new_tax = flt(item_fiscal["tax_amount"] + charge_fiscal["tax_amount"], 2)
	new_grand_total = flt(item_fiscal["net_total"] + charge_fiscal["net_total"], 2)
	changed = any(
		abs(new - old) > 0.005
		for new, old in (
			(discount, flt(order.discount_amount)),
			(service, flt(order.service_charge)),
			(tip, flt(order.tip_amount)),
			(new_tax, flt(order.tax_amount)),
			(new_grand_total, flt(order.grand_total)),
		)
	)
	if not changed:
		return order, item_fiscal, charge_fiscal

	before = {
		"discount_amount": flt(order.discount_amount, 2),
		"service_charge": flt(order.service_charge, 2),
		"tip_amount": flt(order.tip_amount, 2),
		"tax_amount": flt(order.tax_amount, 2),
		"grand_total": flt(order.grand_total, 2),
	}
	order.discount_amount = discount
	order.service_charge = service
	order.tip_amount = tip
	order.tax_amount = new_tax
	order.grand_total = new_grand_total
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
				"tax_amount": new_tax,
				"grand_total": new_grand_total,
			},
		},
	)
	return order, item_fiscal, charge_fiscal


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
	discount, service, tip, item_fiscal, charge_fiscal = _normalize_adjustments(
		order,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
		persist_charges=False,
	)
	_validate_fire_complete(item_fiscal)
	if (
		abs(discount - flt(order.discount_amount)) > 0.005
		or abs(service - flt(order.service_charge)) > 0.005
	) and not _is_manager():
		frappe.throw("Discount or Service Charge changes require Manager or Admin access.", frappe.PermissionError)
	return {
		"order": get_order_payload(order.name),
		"subtotal_before_discount": flt(item_fiscal["gross_total"], 2),
		"discount_amount": discount,
		"total_after_discount": flt(item_fiscal["total_amount"], 2),
		"tax_amount": flt(item_fiscal["tax_amount"] + charge_fiscal["tax_amount"], 2),
		"service_charge": service,
		"tip_amount": tip,
		"charge_tax_amount": flt(charge_fiscal["tax_amount"], 2),
		"grand_total": flt(item_fiscal["net_total"] + charge_fiscal["net_total"], 2),
		"payment_methods": [dict(row) for row in _payment_methods()],
		"active_shift": _open_shift(order.branch),
		"can_adjust_discount_or_service": _is_manager(),
		"charges": charge_fiscal["rows"],
	}


def _build_sale(order, item_fiscal, charge_fiscal, tenders, client_sale_id, shift):
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
	sale.subtotal_before_discount = flt(item_fiscal["gross_total"] + charge_fiscal["base_amount"], 2)
	sale.discount_type = "Amount" if flt(order.discount_amount) else ""
	sale.discount_value = flt(order.discount_amount, 2)
	sale.discount_amount = flt(order.discount_amount, 2)
	sale.service_charge = flt(order.service_charge, 2)
	sale.tip_amount = flt(order.tip_amount, 2)
	sale.allow_partial_payment = 0

	for row in item_fiscal["rows"]:
		sale.append("items", {
			"item": row["item"],
			"restaurant_order_item": row["restaurant_order_item"],
			"quantity": flt(row["qty"], 6),
			"price_list_snapshot": row["price_list_snapshot"],
			"item_price_reference": row["item_price_reference"],
			"list_rate": flt(row["line_unit_rate_snapshot"], 2),
			"base_rate_snapshot": flt(row["base_rate_snapshot"], 2),
			"modifier_unit_total_snapshot": flt(row["modifier_unit_total_snapshot"], 2),
			"seat_no_snapshot": cint(row["seat_no"]),
			"course_snapshot": row["course"],
			"rate": flt(row["effective_rate"], 2),
			"price_override": 0,
			"cost_price": flt(row["cost_price"], 4),
		})

	for row in charge_fiscal["rows"]:
		sale.append("items", {
			"item": row["item"],
			"restaurant_order_charge": row["restaurant_order_charge"],
			"restaurant_charge_type": row["charge_type"],
			"quantity": 1,
			"price_list_snapshot": order.price_list,
			"list_rate": flt(row["amount"], 2),
			"base_rate_snapshot": flt(row["amount"], 2),
			"modifier_unit_total_snapshot": 0,
			"seat_no_snapshot": 0,
			"rate": flt(row["amount"], 2),
			"price_override": 0,
			"cost_price": 0,
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

	existing_sale = frappe.db.get_value(
		"Ledgix Sale",
		{"client_sale_id": client_sale_id},
		["name", "restaurant_order", "docstatus"],
		as_dict=True,
	)
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

	order, item_fiscal, charge_fiscal = _apply_adjustments(
		order,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
		reason=adjustment_reason,
		request_id=f"{request_id}:adjust" if request_id else None,
	)
	_validate_fire_complete(item_fiscal)
	shift = _open_shift(order.branch)
	if not shift:
		frappe.throw("Open a POS Shift for this branch before restaurant settlement.")

	sale = _build_sale(order, item_fiscal, charge_fiscal, tenders, client_sale_id, shift)
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
