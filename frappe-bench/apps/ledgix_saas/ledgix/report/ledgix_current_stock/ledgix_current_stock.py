# Copyright (c) 2026, Ali and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

from ledgix_saas.services.organization import get_allowed_branches


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_prepare_scope(filters)

	columns = get_columns()
	data = get_data(filters)
	summary = get_report_summary(data)

	message = None
	if not data:
		message = """
			<div style="padding: 20px; text-align: center; color: #667085;">
				No current stock data found for the selected branch/location filters.
			</div>
		"""

	return columns, data, message, None, summary


def _prepare_scope(filters):
	allowed = get_allowed_branches()
	if filters.get("branch"):
		if filters.branch not in allowed:
			frappe.throw("You are not allowed to view stock for this Branch.", frappe.PermissionError)
		allowed = [filters.branch]

	filters.allowed_branches = tuple(allowed or ["__NO_ALLOWED_BRANCH__"])

	if filters.get("stock_location"):
		location_branch = frappe.db.get_value(
			"Ledgix Stock Location",
			{"name": filters.stock_location, "is_active": 1},
			"branch",
		)
		if not location_branch or location_branch not in allowed:
			frappe.throw("You are not allowed to view this Stock Location.", frappe.PermissionError)
		if filters.get("branch") and location_branch != filters.branch:
			frappe.throw("Stock Location does not belong to the selected Branch.")


def get_columns():
	return [
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Ledgix Branch", "width": 120},
		{"label": "Stock Location", "fieldname": "stock_location", "fieldtype": "Link", "options": "Ledgix Stock Location", "width": 150},
		{"label": "Item", "fieldname": "item", "fieldtype": "Link", "options": "Ledgix Item", "width": 155},
		{"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 190},
		{"label": "Category", "fieldname": "category", "fieldtype": "Link", "options": "Ledgix Category", "width": 150},
		{"label": "Unit", "fieldname": "unit", "fieldtype": "Data", "width": 85},
		{"label": "Current Stock", "fieldname": "current_stock", "fieldtype": "Float", "width": 125},
		{"label": "Aggregate Stock", "fieldname": "aggregate_stock", "fieldtype": "Float", "width": 125},
		{"label": "Opening Seed", "fieldname": "opening_stock", "fieldtype": "Float", "width": 115},
		{"label": "Minimum Stock", "fieldname": "minimum_stock", "fieldtype": "Float", "width": 125},
		{"label": "Stock Status", "fieldname": "stock_status", "fieldtype": "Data", "width": 125},
		{"label": "Cost Price", "fieldname": "cost_price", "fieldtype": "Currency", "width": 115},
		{"label": "Selling Price", "fieldname": "selling_price", "fieldtype": "Currency", "width": 120},
		{"label": "Stock Value", "fieldname": "stock_value", "fieldtype": "Currency", "width": 130},
		{"label": "Expected Profit / Unit", "fieldname": "expected_profit_per_unit", "fieldtype": "Currency", "width": 165},
		{"label": "Potential Profit", "fieldname": "potential_profit", "fieldtype": "Currency", "width": 135},
		{"label": "View", "fieldname": "view_action", "fieldtype": "HTML", "width": 60},
		{"label": "Print", "fieldname": "print_action", "fieldtype": "HTML", "width": 60},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			l.branch,
			l.name AS stock_location,
			i.name AS item,
			i.item_name,
			i.category,
			i.unit,
			IFNULL(sb.quantity, 0) AS current_stock,
			IFNULL(i.current_stock, 0) AS aggregate_stock,
			IFNULL(i.opening_stock, 0) AS opening_stock,
			IFNULL(i.minimum_stock, 0) AS minimum_stock,
			CASE
				WHEN IFNULL(sb.quantity, 0) <= 0 THEN 'Out of Stock'
				WHEN IFNULL(sb.quantity, 0) <= IFNULL(i.minimum_stock, 0) THEN 'Low Stock'
				ELSE 'In Stock'
			END AS stock_status,
			IFNULL(i.cost_price, 0) AS cost_price,
			IFNULL(i.selling_price, 0) AS selling_price,
			IFNULL(sb.quantity, 0) * IFNULL(i.cost_price, 0) AS stock_value,
			IFNULL(i.selling_price, 0) - IFNULL(i.cost_price, 0) AS expected_profit_per_unit,
			IFNULL(sb.quantity, 0) * (IFNULL(i.selling_price, 0) - IFNULL(i.cost_price, 0)) AS potential_profit,
			i.name AS view_action,
			i.name AS print_action
		FROM `tabLedgix Stock Location` l
		CROSS JOIN `tabLedgix Item` i
		LEFT JOIN `tabLedgix Stock Balance` sb
			ON sb.stock_location = l.name AND sb.item = i.name
		WHERE {conditions}
		ORDER BY
			l.branch ASC,
			l.location_name ASC,
			CASE
				WHEN IFNULL(sb.quantity, 0) <= 0 THEN 1
				WHEN IFNULL(sb.quantity, 0) <= IFNULL(i.minimum_stock, 0) THEN 2
				ELSE 3
			END,
			i.item_name ASC
		""",
		filters,
		as_dict=True,
	)


def get_conditions(filters):
	conditions = [
		"l.is_active = 1",
		"l.branch IN %(allowed_branches)s",
	]

	if filters.get("branch"):
		conditions.append("l.branch = %(branch)s")
	if filters.get("stock_location"):
		conditions.append("l.name = %(stock_location)s")
	if filters.get("item"):
		conditions.append("i.name = %(item)s")
	if filters.get("category"):
		conditions.append("i.category = %(category)s")

	if filters.get("stock_status"):
		status = filters.get("stock_status")
		if status == "In Stock":
			conditions.append("IFNULL(sb.quantity, 0) > IFNULL(i.minimum_stock, 0)")
		elif status == "Low Stock":
			conditions.append("IFNULL(sb.quantity, 0) > 0")
			conditions.append("IFNULL(sb.quantity, 0) <= IFNULL(i.minimum_stock, 0)")
		elif status == "Out of Stock":
			conditions.append("IFNULL(sb.quantity, 0) <= 0")

	if filters.get("only_active"):
		conditions.append("IFNULL(i.active, 1) = 1")

	return " AND ".join(conditions)


def get_report_summary(data):
	total_items = len({row.get("item") for row in data if row.get("item")})
	locations = len({row.get("stock_location") for row in data if row.get("stock_location")})
	total_stock_qty = sum(flt(row.get("current_stock")) for row in data)
	total_stock_value = sum(flt(row.get("stock_value")) for row in data)
	total_potential_profit = sum(flt(row.get("potential_profit")) for row in data)
	low_stock_items = sum(1 for row in data if row.get("stock_status") == "Low Stock")
	out_of_stock_items = sum(1 for row in data if row.get("stock_status") == "Out of Stock")

	return [
		{"value": total_items, "label": "Items", "datatype": "Int"},
		{"value": locations, "label": "Locations", "datatype": "Int"},
		{"value": total_stock_qty, "label": "Stock Qty", "datatype": "Float"},
		{"value": total_stock_value, "label": "Stock Value", "datatype": "Currency"},
		{"value": low_stock_items, "label": "Low Stock Rows", "datatype": "Int"},
		{"value": out_of_stock_items, "label": "Out of Stock Rows", "datatype": "Int"},
		{"value": total_potential_profit, "label": "Potential Profit", "datatype": "Currency"},
	]
