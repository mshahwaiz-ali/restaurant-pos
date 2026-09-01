from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Ledgix Stock Movement": [
				{
					"fieldname": "previous_quantity",
					"label": "Previous Location Quantity",
					"fieldtype": "Float",
					"insert_after": "quantity",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"module": "Ledgix",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Ledgix Stock Movement")
