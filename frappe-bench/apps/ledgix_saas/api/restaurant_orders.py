from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
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


@frappe.whitelist()
def open_session(restaurant_table, covers=1, server=None, customer=None, guest_name=None, session_notes=None):
	require_ledgix_cashier_or_above()
	return open_table_session(
		restaurant_table,
		covers=covers,
		server=server,
		customer=customer,
		guest_name=guest_name,
		session_notes=session_notes,
	)


@frappe.whitelist()
def close_session(table_session):
	require_ledgix_cashier_or_above()
	return close_table_session(table_session)


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
	return open_restaurant_order(
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
	return add_order_item(
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


@frappe.whitelist()
def edit_item(order_item, quantity=None, seat_no=None, course=None, is_course_held=None, item_note=None):
	require_ledgix_cashier_or_above()
	return update_order_item(
		order_item,
		quantity=quantity,
		seat_no=seat_no,
		course=course,
		is_course_held=is_course_held,
		item_note=item_note,
	)


@frappe.whitelist()
def void_item(order_item, reason, quantity=None):
	require_ledgix_cashier_or_above()
	return void_order_item(order_item, reason, quantity=quantity)


@frappe.whitelist()
def move_table(table_session, destination_table, reason):
	require_ledgix_cashier_or_above()
	return transfer_table(table_session, destination_table, reason=reason)


@frappe.whitelist()
def set_server(table_session, server, reason):
	require_ledgix_cashier_or_above()
	return change_server(table_session, server, reason=reason)


@frappe.whitelist()
def set_covers(table_session, covers, reason):
	require_ledgix_cashier_or_above()
	return adjust_covers(table_session, covers, reason=reason)
