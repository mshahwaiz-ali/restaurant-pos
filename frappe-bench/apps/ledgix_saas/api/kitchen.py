from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.kitchen import (
	fire_order_items,
	get_kot_payload,
	get_station_queue,
	recall_kot,
	set_kot_item_status,
	void_kitchen_item,
)


_ALLOWED_KDS_TRANSITIONS = {
	"New": {"Preparing", "Ready"},
	"Preparing": {"Ready"},
	"Ready": {"Bumped"},
	"Bumped": set(),
}


@frappe.whitelist()
def fire(restaurant_order, client_fire_id, selections=None, release_held=0, note=None):
	require_ledgix_cashier_or_above()
	return fire_order_items(
		restaurant_order,
		selections=selections,
		client_fire_id=client_fire_id,
		release_held=release_held,
		note=note,
	)


@frappe.whitelist()
def get_kot(kot):
	require_ledgix_cashier_or_above()
	return get_kot_payload(kot)


@frappe.whitelist()
def station_queue(branch, kitchen_station=None, include_ready=1):
	require_ledgix_cashier_or_above()
	return get_station_queue(branch=branch, kitchen_station=kitchen_station, include_ready=include_ready)


@frappe.whitelist()
def set_item_status(kot_item, status):
	require_ledgix_cashier_or_above()
	row = frappe.db.get_value(
		"Ledgix KOT Item",
		kot_item,
		["status", "action"],
		as_dict=True,
	)
	if not row:
		frappe.throw("KOT Item was not found.")
	if row.action != "Add":
		frappe.throw("Only Add KOT Items use the production-state workflow.")
	status = str(status or "").strip()
	if status != row.status and status not in _ALLOWED_KDS_TRANSITIONS.get(row.status, set()):
		frappe.throw(f"KDS state cannot move from {row.status} to {status}.")
	return set_kot_item_status(kot_item, status)


@frappe.whitelist()
def void_item(order_item, reason, client_fire_id, quantity=None):
	require_ledgix_cashier_or_above()
	return void_kitchen_item(
		order_item,
		quantity=quantity,
		reason=reason,
		client_fire_id=client_fire_id,
	)


@frappe.whitelist()
def recall(source_kot, reason, client_fire_id):
	require_ledgix_cashier_or_above()
	return recall_kot(source_kot, reason=reason, client_fire_id=client_fire_id)
