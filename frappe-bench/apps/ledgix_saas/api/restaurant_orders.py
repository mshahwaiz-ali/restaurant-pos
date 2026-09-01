from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.restaurant_audit import log_restaurant_operation
from ledgix_saas.services.restaurant_orders import (
	add_order_item,
	adjust_covers,
	change_server,
	close_table_session,
	get_order_payload,
	get_table_session_payload,
	open_restaurant_order,
	open_table_session,
	transfer_table,
	update_order_item,
	void_order_item,
)


def _audit_request_id(operation, request_id=None, fallback=None):
	identity = str(request_id or fallback or "").strip()
	return f"{operation}:{identity}" if identity else None


@frappe.whitelist()
def open_session(
	restaurant_table,
	covers=1,
	server=None,
	customer=None,
	guest_name=None,
	session_notes=None,
	request_id=None,
):
	require_ledgix_cashier_or_above()
	result = open_table_session(
		restaurant_table,
		covers=covers,
		server=server,
		customer=customer,
		guest_name=guest_name,
		session_notes=session_notes,
	)
	log_restaurant_operation(
		"Open Session",
		branch=result["branch"],
		table_session=result["name"],
		request_id=_audit_request_id("open-session", request_id),
		metadata={"restaurant_table": restaurant_table, "covers": covers},
	)
	return result


@frappe.whitelist()
def close_session(table_session, request_id=None):
	require_ledgix_cashier_or_above()
	result = close_table_session(table_session)
	log_restaurant_operation(
		"Close Session",
		branch=result["branch"],
		table_session=result["name"],
		request_id=_audit_request_id("close-session", request_id),
	)
	return result


@frappe.whitelist()
def get_session(table_session):
	require_ledgix_cashier_or_above()
	return get_table_session_payload(table_session)


@frappe.whitelist()
def open_check(
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
	require_ledgix_cashier_or_above()
	result = open_restaurant_order(
		order_type=order_type,
		branch=branch,
		menu=menu,
		table_session=table_session,
		customer=customer,
		server=server,
		covers=covers,
		pickup_name=pickup_name,
		contact_phone=contact_phone,
		delivery_address=delivery_address,
		delivery_instructions=delivery_instructions,
		promised_at=promised_at,
		client_order_id=client_order_id,
	)
	log_restaurant_operation(
		"Open Check",
		branch=result["branch"],
		table_session=result.get("table_session"),
		restaurant_order=result["name"],
		request_id=_audit_request_id("open-check", fallback=client_order_id),
		metadata={"order_type": result["order_type"], "covers": result["covers"]},
	)
	return result


@frappe.whitelist()
def get_check(restaurant_order):
	require_ledgix_cashier_or_above()
	return get_order_payload(restaurant_order)


@frappe.whitelist()
def add_item(
	restaurant_order,
	menu_item,
	quantity=1,
	modifiers=None,
	seat_no=0,
	course=None,
	is_course_held=0,
	item_note=None,
	client_item_id=None,
):
	require_ledgix_cashier_or_above()
	result = add_order_item(
		restaurant_order,
		menu_item,
		quantity=quantity,
		modifiers=modifiers,
		seat_no=seat_no,
		course=course,
		is_course_held=is_course_held,
		item_note=item_note,
		client_item_id=client_item_id,
	)
	log_restaurant_operation(
		"Add Item",
		branch=result["branch"],
		table_session=result.get("table_session"),
		restaurant_order=result["name"],
		request_id=_audit_request_id("add-item", fallback=client_item_id),
		metadata={"menu_item": menu_item, "quantity": quantity, "seat_no": seat_no, "course": course},
	)
	return result


@frappe.whitelist()
def edit_item(
	order_item,
	quantity=None,
	seat_no=None,
	course=None,
	is_course_held=None,
	item_note=None,
	request_id=None,
):
	require_ledgix_cashier_or_above()
	before = frappe.db.get_value(
		"Ledgix Restaurant Order Item",
		order_item,
		["restaurant_order", "quantity", "seat_no", "course", "is_course_held", "item_note"],
		as_dict=True,
	)
	result = update_order_item(
		order_item,
		quantity=quantity,
		seat_no=seat_no,
		course=course,
		is_course_held=is_course_held,
		item_note=item_note,
	)
	log_restaurant_operation(
		"Edit Item",
		branch=result["branch"],
		table_session=result.get("table_session"),
		restaurant_order=result["name"],
		restaurant_order_item=order_item,
		request_id=_audit_request_id("edit-item", request_id),
		metadata={"before": dict(before or {}), "requested": {"quantity": quantity, "seat_no": seat_no, "course": course, "is_course_held": is_course_held, "item_note": item_note}},
	)
	return result


@frappe.whitelist()
def void_item(order_item, reason, quantity=None, request_id=None):
	require_ledgix_cashier_or_above()
	result = void_order_item(order_item, reason, quantity=quantity)
	log_restaurant_operation(
		"Void Item",
		branch=result["branch"],
		table_session=result.get("table_session"),
		restaurant_order=result["name"],
		restaurant_order_item=order_item,
		reason=reason,
		request_id=_audit_request_id("void-item", request_id),
		metadata={"quantity": quantity},
	)
	return result


@frappe.whitelist()
def move_table(table_session, destination_table, reason, request_id=None):
	require_ledgix_cashier_or_above()
	before_table = frappe.db.get_value("Ledgix Table Session", table_session, "restaurant_table")
	result = transfer_table(table_session, destination_table, reason=reason)
	log_restaurant_operation(
		"Transfer Table",
		branch=result["branch"],
		table_session=result["name"],
		reason=reason,
		request_id=_audit_request_id("transfer-table", request_id),
		metadata={"from_table": before_table, "to_table": destination_table},
	)
	return result


@frappe.whitelist()
def set_server(table_session, server, reason, request_id=None):
	require_ledgix_cashier_or_above()
	before_server = frappe.db.get_value("Ledgix Table Session", table_session, "server")
	result = change_server(table_session, server, reason=reason)
	log_restaurant_operation(
		"Change Server",
		branch=result["branch"],
		table_session=result["name"],
		reason=reason,
		request_id=_audit_request_id("change-server", request_id),
		metadata={"from_server": before_server, "to_server": server},
	)
	return result


@frappe.whitelist()
def set_covers(table_session, covers, reason, request_id=None):
	require_ledgix_cashier_or_above()
	before_covers = frappe.db.get_value("Ledgix Table Session", table_session, "covers")
	result = adjust_covers(table_session, covers, reason=reason)
	log_restaurant_operation(
		"Adjust Covers",
		branch=result["branch"],
		table_session=result["name"],
		reason=reason,
		request_id=_audit_request_id("adjust-covers", request_id),
		metadata={"from_covers": before_covers, "to_covers": covers},
	)
	return result
