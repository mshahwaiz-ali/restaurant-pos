from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.restaurant_audit import log_restaurant_operation
from ledgix_saas.services.restaurant_order_splits import (
	merge_checks,
	split_check_by_items,
	split_check_by_seat,
)


@frappe.whitelist()
def split_by_items(restaurant_order, selections, client_order_id, reason):
	require_ledgix_cashier_or_above()
	result = split_check_by_items(
		restaurant_order,
		selections,
		client_order_id,
		reason=reason,
	)
	split_order = result["split"]
	log_restaurant_operation(
		"Split Check",
		branch=split_order["branch"],
		table_session=split_order.get("table_session"),
		restaurant_order=split_order["name"],
		source_order=restaurant_order,
		destination_order=split_order["name"],
		reason=reason,
		request_id=f"split-check:{client_order_id}",
		metadata={"mode": "items", "selections": frappe.parse_json(selections) if isinstance(selections, str) else selections},
	)
	return result


@frappe.whitelist()
def split_by_seat(restaurant_order, seat_no, client_order_id, reason=None):
	require_ledgix_cashier_or_above()
	result = split_check_by_seat(
		restaurant_order,
		seat_no,
		client_order_id,
		reason=reason,
	)
	split_order = result["split"]
	log_restaurant_operation(
		"Split Check",
		branch=split_order["branch"],
		table_session=split_order.get("table_session"),
		restaurant_order=split_order["name"],
		source_order=restaurant_order,
		destination_order=split_order["name"],
		reason=reason or f"Split seat {seat_no}",
		request_id=f"split-check:{client_order_id}",
		metadata={"mode": "seat", "seat_no": seat_no},
	)
	return result


@frappe.whitelist()
def merge(source_order, destination_order, reason, request_id=None):
	require_ledgix_cashier_or_above()
	source_branch = frappe.db.get_value("Ledgix Restaurant Order", source_order, "branch")
	result = merge_checks(source_order, destination_order, reason=reason)
	log_restaurant_operation(
		"Merge Check",
		branch=source_branch,
		table_session=result.get("table_session"),
		restaurant_order=result["name"],
		source_order=source_order,
		destination_order=destination_order,
		reason=reason,
		request_id=f"merge-check:{request_id}" if request_id else None,
	)
	return result
