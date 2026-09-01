from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
	"Ledgix Sale": [
		{
			"fieldname": "restaurant_order",
			"label": "Restaurant Order",
			"fieldtype": "Link",
			"options": "Ledgix Restaurant Order",
			"insert_after": "stock_location",
			"read_only": 1,
			"unique": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "restaurant_table_session",
			"label": "Table Session",
			"fieldtype": "Link",
			"options": "Ledgix Table Session",
			"insert_after": "restaurant_order",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "restaurant_order_type",
			"label": "Restaurant Order Type",
			"fieldtype": "Data",
			"insert_after": "restaurant_table_session",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "restaurant_table_snapshot",
			"label": "Table Snapshot",
			"fieldtype": "Data",
			"insert_after": "restaurant_order_type",
			"read_only": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "restaurant_server_snapshot",
			"label": "Server Snapshot",
			"fieldtype": "Data",
			"insert_after": "restaurant_table_snapshot",
			"read_only": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "restaurant_covers_snapshot",
			"label": "Covers Snapshot",
			"fieldtype": "Int",
			"insert_after": "restaurant_server_snapshot",
			"read_only": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "restaurant_stock_consumed_at_kitchen",
			"label": "Restaurant Stock Consumed at Kitchen",
			"fieldtype": "Check",
			"insert_after": "restaurant_covers_snapshot",
			"hidden": 1,
			"read_only": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "service_charge",
			"label": "Service Charge",
			"fieldtype": "Currency",
			"insert_after": "discount_amount",
			"read_only": 1,
			"precision": "2",
			"module": "Ledgix",
		},
		{
			"fieldname": "tip_amount",
			"label": "Tip / Gratuity",
			"fieldtype": "Currency",
			"insert_after": "service_charge",
			"read_only": 1,
			"precision": "2",
			"module": "Ledgix",
		},
	],
	"Ledgix Sale Item": [
		{
			"fieldname": "restaurant_order_item",
			"label": "Restaurant Order Item",
			"fieldtype": "Link",
			"options": "Ledgix Restaurant Order Item",
			"insert_after": "item",
			"read_only": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "base_rate_snapshot",
			"label": "Restaurant Base Rate Snapshot",
			"fieldtype": "Currency",
			"insert_after": "list_rate",
			"read_only": 1,
			"precision": "2",
			"module": "Ledgix",
		},
		{
			"fieldname": "modifier_unit_total_snapshot",
			"label": "Modifier / Unit Snapshot",
			"fieldtype": "Currency",
			"insert_after": "base_rate_snapshot",
			"read_only": 1,
			"precision": "2",
			"module": "Ledgix",
		},
		{
			"fieldname": "seat_no_snapshot",
			"label": "Seat Snapshot",
			"fieldtype": "Int",
			"insert_after": "modifier_unit_total_snapshot",
			"read_only": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "course_snapshot",
			"label": "Course Snapshot",
			"fieldtype": "Data",
			"insert_after": "seat_no_snapshot",
			"read_only": 1,
			"module": "Ledgix",
		},
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	frappe.clear_cache()
