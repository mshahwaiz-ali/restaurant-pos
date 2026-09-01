from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Ledgix POS Hold": [
				{
					"fieldname": "branch",
					"label": "Branch",
					"fieldtype": "Link",
					"options": "Ledgix Branch",
					"insert_after": "shift",
					"read_only": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
					"module": "Ledgix",
				},
				{
					"fieldname": "stock_location",
					"label": "Stock Location",
					"fieldtype": "Link",
					"options": "Ledgix Stock Location",
					"insert_after": "branch",
					"read_only": 1,
					"in_standard_filter": 1,
					"module": "Ledgix",
				},
			]
		},
		update=True,
	)

	branch = frappe.db.get_value(
		"Ledgix Branch",
		{"is_active": 1},
		"name",
		order_by="creation asc",
	)
	if not branch:
		frappe.throw("Restaurant branch foundation is missing.")
	location = frappe.db.get_value("Ledgix Branch", branch, "default_stock_location") or frappe.db.get_value(
		"Ledgix Stock Location",
		{"branch": branch, "is_active": 1},
		"name",
		order_by="creation asc",
	)
	if not location:
		frappe.throw("Restaurant stock-location foundation is missing.")

	frappe.db.sql(
		"""
		UPDATE `tabLedgix POS Hold` h
		LEFT JOIN `tabLedgix POS Shift` sh ON sh.name = h.shift
		SET h.branch = COALESCE(NULLIF(h.branch, ''), NULLIF(sh.branch, ''), %s),
		    h.stock_location = COALESCE(NULLIF(h.stock_location, ''), NULLIF(sh.stock_location, ''), %s)
		WHERE COALESCE(h.branch, '') = '' OR COALESCE(h.stock_location, '') = ''
		""",
		(branch, location),
	)
	frappe.clear_cache(doctype="Ledgix POS Hold")
