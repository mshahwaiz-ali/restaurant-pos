from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_manager_or_above
from ledgix_saas.services.reorder import get_inventory_overview, get_reorder_suggestions


@frappe.whitelist()
def overview(branch=None, stock_location=None, query=None, below_minimum=0):
	require_ledgix_manager_or_above()
	return get_inventory_overview(
		branch=branch,
		stock_location=stock_location,
		query=query,
		below_minimum=bool(int(below_minimum or 0)),
	)


@frappe.whitelist()
def suggestions(branch=None, stock_location=None, supplier=None):
	require_ledgix_manager_or_above()
	return get_reorder_suggestions(
		branch=branch,
		stock_location=stock_location,
		supplier=supplier,
	)
