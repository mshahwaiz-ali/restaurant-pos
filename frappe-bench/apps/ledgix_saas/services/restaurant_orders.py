from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, now_datetime

from ledgix_saas.api.taxation import (
	calculate_tax_breakdown,
	get_tax_profile,
	is_tax_enabled,
	resolve_item_tax_context,
	resolve_tax_rate,
)
from ledgix_saas.services.menu import get_effective_item_availability, resolve_branch_menu
from ledgix_saas.services.organization import ensure_branch_access
from ledgix_saas.services.pricing import resolve_item_price
from ledgix_saas.services.recipe import build_consumption_plan


FINAL_ORDER_STATUSES = {"Closed", "Voided"}
PROTECTED_KITCHEN_STATUSES = {"Fired", "Preparing", "Ready", "Served"}
CHANNEL_FIELD = {
	"Dine In": "available_dine_in",
	"Takeaway": "available_takeaway",
	"Delivery": "available_delivery",
}


def _as_rows(value):
	if isinstance(value, str):
		value = frappe.parse_json(value)
	return value or []


def _active_order(order_name):
	order = frappe.get_doc("Ledgix Restaurant Order", order_name)
	ensure_branch_access(order.branch)
	if order.status in FINAL_ORDER_STATUSES or order.linked_sale:
		frappe.throw("Restaurant Order is finalized and cannot be changed.")
	return order


def _serialize_item(item):
	return {
		"name": item.name,
		"restaurant_order": item.restaurant_order,
		"origin_order": item.origin_order,
		"origin_order_item": item.origin_order_item,
		"client_item_id": item.client_item_id,
		"menu_item": item.menu_item,
		"item": item.item,
		"display_name": item.display_name_snapshot,
		"quantity": flt(item.quantity),
		"void_quantity": flt(item.void_quantity),
		"billable_quantity": flt(item.billable_quantity),
		"seat_no": cint(item.seat_no),
		"course": item.course,
		"is_course_held": cint(item.is_course_held),
		"rate": flt(item.rate),
		"modifier_unit_total": flt(item.modifier_unit_total),
		"line_unit_rate": flt(item.line_unit_rate),
		"amount": flt(item.amount),
		"tax_amount": flt(item.tax_amount),
		"net_amount": flt(item.net_amount),
		"kitchen_status": item.kitchen_status,
		"fired_quantity": flt(item.fired_quantity),
		"prepared_quantity": flt(item.prepared_quantity),
		"ready_quantity": flt(item.ready_quantity),
		"served_quantity": flt(item.served_quantity),
		"is_voided": cint(item.is_voided),
		"item_note": item.item_note,
		"modifiers": [
			{
				"modifier_group": row.modifier_group,
				"modifier_option": row.modifier_option,
				"group_name": row.modifier_group_name_snapshot,
				"option_name": row.option_name_snapshot,
				"kitchen_label": row.kitchen_label_snapshot,
				"quantity": flt(row.selection_quantity),
				"price_delta": flt(row.price_delta),
				"stock_effect": row.stock_effect,
				"linked_item": row.linked_item,
				"stock_quantity": flt(row.stock_quantity),
				"uom": row.uom,
			}
			for row in item.modifiers
		],
	}


def get_order_payload(order_name):
	order = frappe.get_doc("Ledgix Restaurant Order", order_name)
	ensure_branch_access(order.branch)
	items = frappe.get_all(
		"Ledgix Restaurant Order Item",
		filters={"restaurant_order": order.name},
		pluck="name",
		order_by="creation asc",
		limit_page_length=0,
	)
	return {
		"name": order.name,
		"branch": order.branch,
		"stock_location": order.stock_location,
		"order_type": order.order_type,
		"menu": order.menu,
		"price_list": order.price_list,
		"status": order.status,
		"table_session": order.table_session,
		"restaurant_table": order.restaurant_table,
		"table_name": order.table_name_snapshot,
		"server": order.server,
		"cashier": order.cashier,
		"covers": cint(order.covers),
		"customer": order.customer,
		"subtotal": flt(order.subtotal),
		"modifier_total": flt(order.modifier_total),
		"discount_amount": flt(order.discount_amount),
		"service_charge": flt(order.service_charge),
		"tip_amount": flt(order.tip_amount),
		"tax_amount": flt(order.tax_amount),
		"grand_total": flt(order.grand_total),
		"items": [_serialize_item(frappe.get_doc("Ledgix Restaurant Order Item", name)) for name in items],
	}


def open_table_session(restaurant_table, covers=1, server=None, customer=None, guest_name=None, session_notes=None):
	table = frappe.db.get_value(
		"Ledgix Restaurant Table",
		{"name": restaurant_table, "is_active": 1},
		["name", "branch", "floor", "capacity"],
		as_dict=True,
	)
	if not table:
		frappe.throw("Restaurant Table is inactive or does not exist.")
	ensure_branch_access(table.branch)

	existing = frappe.db.get_value(
		"Ledgix Table Session",
		{"restaurant_table": table.name, "status": ["in", ["Open", "Closing"]]},
		"name",
		order_by="opened_at desc",
	)
	if existing:
		return get_table_session_payload(existing)

	covers = cint(covers)
	if covers <= 0:
		frappe.throw("Covers must be greater than zero.")

	doc = frappe.get_doc({
		"doctype": "Ledgix Table Session",
		"restaurant_table": table.name,
		"covers": covers,
		"server": server,
		"customer": customer,
		"guest_name": (guest_name or "").strip(),
		"session_notes": (session_notes or "").strip(),
	})
	doc.insert(ignore_permissions=True)
	return get_table_session_payload(doc.name)


def get_table_session_payload(session_name):
	session = frappe.get_doc("Ledgix Table Session", session_name)
	ensure_branch_access(session.branch)
	orders = frappe.get_all(
		"Ledgix Restaurant Order",
		filters={"table_session": session.name},
		fields=["name", "status", "grand_total", "server", "covers", "opened_at", "split_from_order"],
		order_by="opened_at asc",
		limit_page_length=0,
	)
	return {
		"name": session.name,
		"branch": session.branch,
		"floor": session.floor,
		"restaurant_table": session.restaurant_table,
		"status": session.status,
		"covers": cint(session.covers),
		"server": session.server,
		"customer": session.customer,
		"guest_name": session.guest_name,
		"opened_at": session.opened_at,
		"orders": [dict(row) for row in orders],
	}


def close_table_session(session_name):
	session = frappe.get_doc("Ledgix Table Session", session_name)
	ensure_branch_access(session.branch)
	if session.status == "Closed":
		return get_table_session_payload(session.name)
	open_orders = frappe.get_all(
		"Ledgix Restaurant Order",
		filters={"table_session": session.name, "status": ["not in", ["Closed", "Voided"]]},
		pluck="name",
		limit_page_length=0,
	)
	if open_orders:
		frappe.throw(f"Close or void open Restaurant Orders first: {', '.join(open_orders)}")
	session.status = "Closed"
	session.closed_at = session.closed_at or now_datetime()
	session.closed_by = session.closed_by or frappe.session.user
	session.save(ignore_permissions=True)
	return get_table_session_payload(session.name)


def open_restaurant_order(
	*,
	order_type="Dine In",
	branch=None,
	menu=None,
	table_session=None,
	customer=None,
	server=None,
	covers=1,
	pickup_name=None,
	contact_phone=None,
	delivery_address=None,
	delivery_instructions=None,
	promised_at=None,
	client_order_id=None,
):
	if client_order_id:
		existing = frappe.db.get_value("Ledgix Restaurant Order", {"client_order_id": client_order_id}, "name")
		if existing:
			return get_order_payload(existing)

	if order_type == "Dine In":
		if not table_session:
			frappe.throw("Dine In orders require a Table Session.")
		session = frappe.db.get_value(
			"Ledgix Table Session",
			{"name": table_session, "status": ["in", ["Open", "Closing"]]},
			["branch", "covers", "server", "customer"],
			as_dict=True,
		)
		if not session:
			frappe.throw("Table Session is not open.")
		if branch and branch != session.branch:
			frappe.throw("Order Branch must match the Table Session branch.")
		branch = session.branch
		server = server or session.server
		customer = customer or session.customer
		covers = cint(covers) or cint(session.covers) or 1

	resolved = resolve_branch_menu(branch=branch, channel=order_type, menu=menu, customer=customer)
	doc = frappe.get_doc({
		"doctype": "Ledgix Restaurant Order",
		"branch": resolved["branch"],
		"stock_location": resolved["stock_location"],
		"order_type": order_type,
		"menu": resolved["menu"].name,
		"price_list": resolved["price_list"],
		"table_session": table_session,
		"server": server,
		"covers": max(cint(covers), 1),
		"customer": customer,
		"pickup_name": pickup_name,
		"contact_phone": contact_phone,
		"delivery_address": delivery_address,
		"delivery_instructions": delivery_instructions,
		"promised_at": promised_at,
		"client_order_id": client_order_id,
	})
	doc.insert(ignore_permissions=True)
	return get_order_payload(doc.name)


def _effective_group_rules(link, group):
	minimum = cint(group.min_selection)
	maximum = cint(group.max_selection)
	if cint(link.min_selection_override) >= 0:
		minimum = cint(link.min_selection_override)
	if cint(link.max_selection_override) >= 0:
		maximum = cint(link.max_selection_override)
	if link.required_override == "Required":
		minimum = max(minimum, 1)
	elif link.required_override == "Optional":
		minimum = 0
	return minimum, maximum


def _modifier_snapshots(menu_item, selections):
	selections = _as_rows(selections)
	links = frappe.get_all(
		"Ledgix Menu Item Modifier Group",
		filters={"parent": menu_item, "parenttype": "Ledgix Menu Item", "parentfield": "modifier_groups"},
		fields=["modifier_group", "required_override", "min_selection_override", "max_selection_override"],
		limit_page_length=0,
	)
	link_by_group = {row.modifier_group: row for row in links}
	groups = {}
	for group_name in link_by_group:
		group = frappe.db.get_value(
			"Ledgix Modifier Group",
			{"name": group_name, "is_active": 1},
			["name", "modifier_group_name", "selection_type", "min_selection", "max_selection"],
			as_dict=True,
		)
		if group:
			groups[group_name] = group

	normalized = []
	counts = {name: 0.0 for name in groups}
	seen_options = set()
	for raw in selections:
		if isinstance(raw, str):
			option_name = raw
			selection_qty = 1
		else:
			option_name = raw.get("modifier_option") or raw.get("option") or raw.get("name")
			selection_qty = flt(raw.get("quantity") or raw.get("selection_quantity") or 1)
		if not option_name or selection_qty <= 0:
			frappe.throw("Each modifier selection requires an option and positive quantity.")
		if option_name in seen_options:
			frappe.throw(f"Modifier Option {option_name} is selected more than once.")
		seen_options.add(option_name)
		option = frappe.db.get_value(
			"Ledgix Modifier Option",
			{"name": option_name, "is_active": 1},
			[
				"name", "modifier_group", "option_name", "kitchen_label", "price_delta",
				"stock_effect", "linked_item", "stock_quantity", "uom",
			],
			as_dict=True,
		)
		if not option or option.modifier_group not in groups:
			frappe.throw(f"Modifier Option {option_name} is not valid for this Menu Item.")
		counts[option.modifier_group] += selection_qty
		group = groups[option.modifier_group]
		normalized.append({
			"modifier_group": group.name,
			"modifier_option": option.name,
			"modifier_group_name_snapshot": group.modifier_group_name,
			"option_name_snapshot": option.option_name,
			"kitchen_label_snapshot": option.kitchen_label or option.option_name,
			"selection_quantity": selection_qty,
			"price_delta": flt(option.price_delta, 2),
			"stock_effect": option.stock_effect,
			"linked_item": option.linked_item,
			"stock_quantity": flt(option.stock_quantity, 6),
			"uom": option.uom,
		})

	for group_name, group in groups.items():
		minimum, maximum = _effective_group_rules(link_by_group[group_name], group)
		count = counts.get(group_name, 0)
		if count < minimum:
			frappe.throw(f"Modifier Group {group.modifier_group_name} requires at least {minimum} selection(s).")
		if maximum and count > maximum:
			frappe.throw(f"Modifier Group {group.modifier_group_name} allows at most {maximum} selection(s).")
		if group.selection_type == "Single" and count > 1:
			frappe.throw(f"Modifier Group {group.modifier_group_name} allows only one selection.")
	return normalized


def _tax_snapshot(item, amount, quantity, posting_date=None):
	profile = get_tax_profile()
	if not is_tax_enabled():
		return {
			"item_tax_profile_snapshot": None,
			"tax_category_snapshot": None,
			"tax_basis_snapshot": "Transaction Value",
			"tax_rate_snapshot": 0,
			"notified_retail_price_snapshot": 0,
			"price_includes_tax_snapshot": 0,
			"taxable_amount": flt(amount, 2),
			"tax_amount": 0,
			"net_amount": flt(amount, 2),
		}

	ctx = resolve_item_tax_context(item, profile=profile)
	mapping = frappe.db.get_value(
		"Ledgix Item Tax Profile",
		{"item": item, "active": 1},
		["name", "tax_basis", "notified_retail_price"],
		as_dict=True,
		order_by="modified desc",
	) if frappe.db.exists("DocType", "Ledgix Item Tax Profile") else None
	tax_basis = (mapping.tax_basis if mapping else None) or "Transaction Value"
	notified = flt(mapping.notified_retail_price if mapping else 0)
	if tax_basis == "Notified Retail Price":
		if notified <= 0:
			frappe.throw(f"Notified Retail Price is required for Third Schedule item {item}.")
		basis_amount = flt(notified * flt(quantity), 2)
	else:
		basis_amount = flt(amount, 2)
	rate = resolve_tax_rate(ctx.get("tax_category"), posting_date=posting_date, applies_to="Sales") if cint(ctx.get("taxable", 1)) else 0
	breakdown = calculate_tax_breakdown(basis_amount, rate, price_includes_tax=bool(profile.get("price_includes_tax")))
	tax_amount = flt(breakdown.get("tax_amount"), 2)
	price_includes_tax = 1 if profile.get("price_includes_tax") else 0
	net_amount = flt(amount if price_includes_tax else flt(amount) + tax_amount, 2)
	return {
		"item_tax_profile_snapshot": mapping.name if mapping else None,
		"tax_category_snapshot": ctx.get("tax_category"),
		"tax_basis_snapshot": tax_basis,
		"tax_rate_snapshot": flt(rate, 2),
		"notified_retail_price_snapshot": notified if tax_basis == "Notified Retail Price" else 0,
		"price_includes_tax_snapshot": price_includes_tax,
		"taxable_amount": flt(breakdown.get("taxable_amount"), 2),
		"tax_amount": tax_amount,
		"net_amount": net_amount,
	}


def _recalculate_item_tax(item):
	tax_basis = item.tax_basis_snapshot or "Transaction Value"
	if tax_basis == "Notified Retail Price":
		basis_amount = flt(item.notified_retail_price_snapshot * item.billable_quantity, 2)
	else:
		basis_amount = flt(item.amount, 2)
	breakdown = calculate_tax_breakdown(
		basis_amount,
		item.tax_rate_snapshot,
		price_includes_tax=bool(cint(item.price_includes_tax_snapshot)),
	)
	item.taxable_amount = flt(breakdown.get("taxable_amount"), 2)
	item.tax_amount = flt(breakdown.get("tax_amount"), 2)
	item.net_amount = flt(item.amount if cint(item.price_includes_tax_snapshot) else flt(item.amount) + item.tax_amount, 2)


def _recalculate_order(order_name):
	order = frappe.get_doc("Ledgix Restaurant Order", order_name)
	rows = frappe.get_all(
		"Ledgix Restaurant Order Item",
		filters={"restaurant_order": order.name},
		fields=["base_amount", "modifier_amount", "amount", "tax_amount", "net_amount", "is_voided"],
		limit_page_length=0,
	)
	order.subtotal = flt(sum(flt(row.base_amount) for row in rows if not cint(row.is_voided)), 2)
	order.modifier_total = flt(sum(flt(row.modifier_amount) for row in rows if not cint(row.is_voided)), 2)
	order.tax_amount = flt(sum(flt(row.tax_amount) for row in rows if not cint(row.is_voided)), 2)
	items_total = flt(sum(flt(row.net_amount) for row in rows if not cint(row.is_voided)), 2)
	order.grand_total = flt(
		items_total - flt(order.discount_amount) + flt(order.service_charge) + flt(order.tip_amount),
		2,
	)
	order.save(ignore_permissions=True)
	return order


def add_order_item(
	order_name,
	menu_item,
	quantity=1,
	modifiers=None,
	seat_no=0,
	course=None,
	is_course_held=0,
	item_note=None,
	client_item_id=None,
):
	if client_item_id:
		existing = frappe.db.get_value("Ledgix Restaurant Order Item", {"client_item_id": client_item_id}, "name")
		if existing:
			doc = frappe.get_doc("Ledgix Restaurant Order Item", existing)
			if doc.restaurant_order != order_name:
				frappe.throw("Client Item ID is already used by another Restaurant Order.")
			return get_order_payload(order_name)

	order = _active_order(order_name)
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Quantity must be greater than zero.")
	menu_row = frappe.db.get_value(
		"Ledgix Menu Item",
		{"name": menu_item, "menu": order.menu, "is_active": 1},
		["name", "item", "display_name", CHANNEL_FIELD[order.order_type]],
		as_dict=True,
	)
	if not menu_row or not cint(menu_row.get(CHANNEL_FIELD[order.order_type])):
		frappe.throw("Menu Item is not active for this order channel.")
	availability = get_effective_item_availability(order.branch, menu_row.item)
	if not availability.get("available"):
		frappe.throw(availability.get("reason") or "This item is currently unavailable.")

	modifier_rows = _modifier_snapshots(menu_item, modifiers)
	price = resolve_item_price(
		menu_row.item,
		customer=order.customer,
		price_list=order.price_list,
		sale_channel="Retail",
		transaction_date=getdate(order.opened_at),
	)
	modifier_unit_total = flt(sum(flt(row["price_delta"]) * flt(row["selection_quantity"]) for row in modifier_rows), 2)
	line_unit_rate = flt(price["rate"] + modifier_unit_total, 2)
	amount = flt(line_unit_rate * quantity, 2)
	consumption = build_consumption_plan(
		menu_row.item,
		order_quantity=1,
		modifier_options=[
			{"modifier_option": row["modifier_option"], "quantity": row["selection_quantity"]}
			for row in modifier_rows
		],
		transaction_date=getdate(order.opened_at),
	)
	tax = _tax_snapshot(menu_row.item, amount, quantity, posting_date=getdate(order.opened_at))

	doc = frappe.get_doc({
		"doctype": "Ledgix Restaurant Order Item",
		"restaurant_order": order.name,
		"origin_order": order.name,
		"client_item_id": client_item_id,
		"menu_item": menu_item,
		"item": menu_row.item,
		"display_name_snapshot": menu_row.display_name,
		"quantity": quantity,
		"seat_no": cint(seat_no),
		"course": (course or "").strip(),
		"is_course_held": cint(is_course_held),
		"price_list_snapshot": price.get("price_list"),
		"item_price_reference": price.get("item_price_reference"),
		"list_rate": flt(price.get("list_rate"), 2),
		"rate": flt(price.get("rate"), 2),
		"modifier_unit_total": modifier_unit_total,
		"recipe": consumption.get("recipe"),
		"recipe_version": cint(consumption.get("recipe_version")),
		"recipe_cost_per_unit": flt(consumption.get("total_cost"), 4),
		"item_note": (item_note or "").strip(),
		"modifiers": modifier_rows,
		**tax,
	})
	doc.flags.from_restaurant_order_service = True
	doc.insert(ignore_permissions=True)
	_recalculate_order(order.name)
	return get_order_payload(order.name)


def update_order_item(item_name, *, quantity=None, seat_no=None, course=None, is_course_held=None, item_note=None):
	item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
	order = _active_order(item.restaurant_order)
	if item.kitchen_status in PROTECTED_KITCHEN_STATUSES or flt(item.fired_quantity) > 0:
		if quantity is not None and flt(quantity) != flt(item.quantity):
			frappe.throw("Quantity cannot be edited after the item has been fired. Use an operational void/delta KOT flow.")

	if quantity is not None:
		if flt(quantity) <= 0:
			frappe.throw("Quantity must be greater than zero.")
		item.quantity = flt(quantity)
	if seat_no is not None:
		item.seat_no = cint(seat_no)
	if course is not None:
		item.course = str(course or "").strip()
	if is_course_held is not None:
		item.is_course_held = cint(is_course_held)
	if item_note is not None:
		item.item_note = str(item_note or "").strip()
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	_recalculate_item_tax(item)
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	_recalculate_order(order.name)
	return get_order_payload(order.name)


def void_order_item(item_name, reason, quantity=None):
	item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
	order = _active_order(item.restaurant_order)
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw("Void Reason is required.")
	remaining = flt(item.quantity) - flt(item.void_quantity)
	void_qty = remaining if quantity is None else flt(quantity)
	if void_qty <= 0 or void_qty > remaining:
		frappe.throw("Void Quantity must be positive and cannot exceed the remaining item quantity.")
	if flt(item.prepared_quantity) > 0:
		frappe.throw("Prepared items require the kitchen waste/comp flow and cannot use the pre-preparation void operation.")

	item.void_quantity = flt(item.void_quantity + void_qty, 6)
	item.void_reason = reason
	item.voided_by = frappe.session.user
	item.voided_at = now_datetime()
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	_recalculate_item_tax(item)
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	_recalculate_order(order.name)
	return get_order_payload(order.name)


def transfer_table(session_name, destination_table, reason=None):
	session = frappe.get_doc("Ledgix Table Session", session_name)
	ensure_branch_access(session.branch)
	if session.status == "Closed":
		frappe.throw("Closed Table Sessions cannot be transferred.")
	if session.restaurant_table == destination_table:
		return get_table_session_payload(session.name)
	destination = frappe.db.get_value(
		"Ledgix Restaurant Table",
		{"name": destination_table, "branch": session.branch, "is_active": 1},
		["name", "floor"],
		as_dict=True,
	)
	if not destination:
		frappe.throw("Destination Table must be active and belong to the same Branch.")
	occupied = frappe.db.get_value(
		"Ledgix Table Session",
		{"restaurant_table": destination_table, "status": ["in", ["Open", "Closing"]], "name": ["!=", session.name]},
		"name",
	)
	if occupied:
		frappe.throw(f"Destination Table is occupied by Table Session {occupied}.")
	if not str(reason or "").strip():
		frappe.throw("Table transfer reason is required.")

	session.restaurant_table = destination_table
	session.flags.allow_table_move = True
	session.save(ignore_permissions=True)
	for order_name in frappe.get_all(
		"Ledgix Restaurant Order",
		filters={"table_session": session.name, "status": ["not in", ["Closed", "Voided"]]},
		pluck="name",
		limit_page_length=0,
	):
		order = frappe.get_doc("Ledgix Restaurant Order", order_name)
		order.restaurant_table = session.restaurant_table
		order.table_name_snapshot = frappe.db.get_value("Ledgix Restaurant Table", session.restaurant_table, "table_name") or session.restaurant_table
		order.save(ignore_permissions=True)
	return get_table_session_payload(session.name)


def change_server(session_name, server, reason=None):
	session = frappe.get_doc("Ledgix Table Session", session_name)
	ensure_branch_access(session.branch)
	if session.status == "Closed":
		frappe.throw("Closed Table Sessions cannot change server.")
	if not frappe.db.exists("User", {"name": server, "enabled": 1}):
		frappe.throw("Server / Waiter must be an enabled User.")
	if session.server == server:
		return get_table_session_payload(session.name)
	if not str(reason or "").strip():
		frappe.throw("Server change reason is required.")
	session.server = server
	session.save(ignore_permissions=True)
	for order_name in frappe.get_all(
		"Ledgix Restaurant Order",
		filters={"table_session": session.name, "status": ["not in", ["Closed", "Voided"]]},
		pluck="name",
		limit_page_length=0,
	):
		order = frappe.get_doc("Ledgix Restaurant Order", order_name)
		order.server = server
		order.save(ignore_permissions=True)
	return get_table_session_payload(session.name)


def adjust_covers(session_name, covers, reason=None):
	session = frappe.get_doc("Ledgix Table Session", session_name)
	ensure_branch_access(session.branch)
	if session.status == "Closed":
		frappe.throw("Closed Table Sessions cannot change covers.")
	covers = cint(covers)
	if covers <= 0:
		frappe.throw("Covers must be greater than zero.")
	if cint(session.covers) == covers:
		return get_table_session_payload(session.name)
	if not str(reason or "").strip():
		frappe.throw("Cover adjustment reason is required.")
	session.covers = covers
	session.save(ignore_permissions=True)
	for order_name in frappe.get_all(
		"Ledgix Restaurant Order",
		filters={"table_session": session.name, "status": ["not in", ["Closed", "Voided"]]},
		pluck="name",
		limit_page_length=0,
	):
		order = frappe.get_doc("Ledgix Restaurant Order", order_name)
		order.covers = covers
		order.save(ignore_permissions=True)
	return get_table_session_payload(session.name)
