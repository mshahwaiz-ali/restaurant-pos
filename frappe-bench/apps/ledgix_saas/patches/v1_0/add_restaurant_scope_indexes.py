from __future__ import annotations

import frappe


INDEXES = (
	("Ledgix Stock Balance", ["stock_location", "item"], "lx_balance_location_item"),
	("Ledgix Stock Balance", ["branch", "item"], "lx_balance_branch_item"),
	("Ledgix Stock Balance", ["item"], "lx_balance_item"),
	("Ledgix Stock Movement", ["stock_location", "item", "docstatus"], "lx_move_location_item_status"),
	("Ledgix Stock Movement", ["branch", "movement_date"], "lx_move_branch_date"),
	("Ledgix Stock Movement", ["reference_name", "item", "stock_location"], "lx_move_reference_item_location"),
	("Ledgix Sale", ["branch", "sale_date"], "lx_sale_branch_date"),
	("Ledgix Sale", ["stock_location", "sale_date"], "lx_sale_location_date"),
	("Ledgix Sale", ["branch", "pos_shift"], "lx_sale_branch_shift"),
	("Ledgix Purchase", ["branch", "purchase_date"], "lx_purchase_branch_date"),
	("Ledgix Purchase", ["stock_location", "purchase_date"], "lx_purchase_location_date"),
	("Ledgix Sales Return", ["branch", "original_sale"], "lx_return_branch_sale"),
	("Ledgix Payment", ["branch", "payment_date"], "lx_payment_branch_date"),
	("Ledgix Payment", ["branch", "customer"], "lx_payment_branch_customer"),
	("Ledgix POS Shift", ["branch", "status", "docstatus"], "lx_shift_branch_status"),
	("Ledgix POS Shift", ["stock_location", "status"], "lx_shift_location_status"),
	("Ledgix Stock Lot", ["stock_location", "item", "status"], "lx_lot_location_item_status"),
	("Ledgix Stock Lot", ["branch", "purchase_date"], "lx_lot_branch_date"),
	("Ledgix Stock Serial", ["stock_location", "item", "status"], "lx_serial_location_item_status"),
	("Ledgix Stock Serial", ["branch", "purchase_date"], "lx_serial_branch_date"),
	("Ledgix Stock Serial", ["sale", "stock_location"], "lx_serial_sale_location"),
	("Ledgix POS Hold", ["branch", "status", "cashier"], "lx_hold_branch_status_cashier"),
	("Ledgix Stock Location", ["branch", "is_active"], "lx_location_branch_active"),
	("Ledgix User Branch Access", ["branch"], "lx_user_branch_access_branch"),
	("Ledgix Branch", ["restaurant_brand", "is_active"], "lx_branch_brand_active"),
)


def execute():
	"""Add the composite indexes used by branch/location operational hot paths.

	Frappe's add_index is idempotent, so this patch is safe to retry during a
	migration interrupted after some indexes were already created.
	"""
	for doctype, fields, index_name in INDEXES:
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if any(field not in {"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx"} and not meta.has_field(field) for field in fields):
			continue
		frappe.db.add_index(doctype, fields, index_name=index_name)
