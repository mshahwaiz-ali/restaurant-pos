from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.restaurant_order_splits import (
	merge_checks,
	split_check_by_items,
	split_check_by_seat,
)


@frappe.whitelist()
def split_by_items(restaurant_order, selections, client_order_id, reason):
	require_ledgix_cashier_or_above()
	return split_check_by_items(
		restaurant_order,
		selections,
		client_order_id,
		reason=reason,
	)


@frappe.whitelist()
def split_by_seat(restaurant_order, seat_no, client_order_id, reason=None):
	require_ledgix_cashier_or_above()
	return split_check_by_seat(
		restaurant_order,
		seat_no,
		client_order_id,
		reason=reason,
	)


@frappe.whitelist()
def merge(source_order, destination_order, reason):
	require_ledgix_cashier_or_above()
	return merge_checks(source_order, destination_order, reason=reason)
