from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.kitchen_courses import fire_course, get_expo_queue


@frappe.whitelist()
def fire(restaurant_order, course, client_fire_id, note=None):
	require_ledgix_cashier_or_above()
	return fire_course(
		restaurant_order,
		course,
		client_fire_id=client_fire_id,
		note=note,
	)


@frappe.whitelist()
def expo_queue(branch, include_ready=1):
	require_ledgix_cashier_or_above()
	return get_expo_queue(branch, include_ready=include_ready)
