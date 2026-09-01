from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.restaurant_pos import get_open_checks, get_restaurant_pos_boot, get_table_map


@frappe.whitelist()
def boot(branch=None, channel="Dine In", menu=None, customer=None):
	require_ledgix_cashier_or_above()
	return get_restaurant_pos_boot(branch=branch, channel=channel, menu=menu, customer=customer)


@frappe.whitelist()
def tables(branch):
	require_ledgix_cashier_or_above()
	return get_table_map(branch)


@frappe.whitelist()
def open_checks(branch, order_type=None):
	require_ledgix_cashier_or_above()
	return get_open_checks(branch, order_type=order_type)
