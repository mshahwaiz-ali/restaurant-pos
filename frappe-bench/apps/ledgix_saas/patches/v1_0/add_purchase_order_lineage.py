from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
	"Ledgix Purchase": [
		{
			"fieldname": "purchase_order",
			"label": "Purchase Order",
			"fieldtype": "Link",
			"options": "Ledgix Purchase Order",
			"insert_after": "stock_location",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "client_receipt_id",
			"label": "Client Receipt ID",
			"fieldtype": "Data",
			"insert_after": "purchase_order",
			"hidden": 1,
			"read_only": 1,
			"unique": 1,
			"no_copy": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Purchase Item": [
		{
			"fieldname": "purchase_order_item",
			"label": "Purchase Order Item",
			"fieldtype": "Data",
			"insert_after": "item",
			"read_only": 1,
			"module": "Ledgix",
		},
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	frappe.clear_cache()
