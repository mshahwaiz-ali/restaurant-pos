# Copyright (c) 2026, Ali and contributors
# For license information, please see license.txt

import frappe

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
				No low stock items found. Inventory looks healthy for the selected branch/location filters.
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
		{"label": "Item", "fieldname": "item", "fieldtype": "Link", "options": "Ledgix Item", "width": 150},
		{"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 190},
		{"label": "Category", "fieldname": "category", "fieldtype": "Data", "width": 145},
		{"label": "Current Stock", "fieldname": "current_stock", "fieldtype": "Float", "width": 120},
		{"label": "Minimum Stock", "fieldname": "minimum_stock", "fieldtype": "Float", "width": 125},
		{"label": "Shortage Qty", "fieldname": "shortage_qty", "fieldtype": "Float", "width": 120},
		{"label": "Cost Price", "fieldname": "cost_price", "fieldtype": "Currency", "width": 115},
		{"label": "Selling Price", "fieldname": "selling_price", "fieldtype": "Currency", "width": 120},
		{"label": "Stock Value", "fieldname": "stock_value", "fieldtype": "Currency", "width": 125},
		{"label": "Potential Sales Gap", "fieldname": "potential_sales_gap", "fieldtype": "Currency", "width": 150},
		{"label": "Risk Status", "fieldname": "risk_status", "fieldtype": "Data", "width": 125},
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
			IFNULL(sb.quantity, 0) AS current_stock,
			IFNULL(i.minimum_stock, 0) AS minimum_stock,
			GREATEST(IFNULL(i.minimum_stock, 0) - IFNULL(sb.quantity, 0), 0) AS shortage_qty,
			IFNULL(i.cost_price, 0) AS cost_price,
			IFNULL(i.selling_price, 0) AS selling_price,
			IFNULL(sb.quantity, 0) * IFNULL(i.cost_price, 0) AS stock_value,
			GREATEST(IFNULL(i.minimum_stock, 0) - IFNULL(sb.quantity, 0), 0) * IFNULL(i.selling_price, 0) AS potential_sales_gap,
			CASE
				WHEN IFNULL(sb.quantity, 0) <= 0 THEN 'Out of Stock'
				WHEN IFNULL(sb.quantity, 0) < IFNULL(i.minimum_stock, 0) THEN 'Low Stock'
				WHEN IFNULL(sb.quantity, 0) = IFNULL(i.minimum_stock, 0) THEN 'At Minimum'
				ELSE 'Healthy'
			END AS risk_status,
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
				WHEN IFNULL(sb.quantity, 0) < IFNULL(i.minimum_stock, 0) THEN 2
				WHEN IFNULL(sb.quantity, 0) = IFNULL(i.minimum_stock, 0) THEN 3
				ELSE 4
			END,
			shortage_qty DESC,
			i.item_name ASC
		""",
		filters,
		as_dict=True,
	)


def get_conditions(filters):
	conditions = [
		"l.is_active = 1",
		"l.branch IN %(allowed_branches)s",
		"IFNULL(i.minimum_stock, 0) > 0",
		"IFNULL(sb.quantity, 0) <= IFNULL(i.minimum_stock, 0)",
	]

	if filters.get("branch"):
		conditions.append("l.branch = %(branch)s")
	if filters.get("stock_location"):
		conditions.append("l.name = %(stock_location)s")
	if filters.get("category"):
		conditions.append("i.category = %(category)s")
	if filters.get("item"):
		conditions.append("i.name = %(item)s")
	if filters.get("only_active"):
		conditions.append("IFNULL(i.active, 1) = 1")

	if filters.get("risk_status"):
		if filters.get("risk_status") == "Out of Stock":
			conditions.append("IFNULL(sb.quantity, 0) <= 0")
		elif filters.get("risk_status") == "Low Stock":
			conditions.append("IFNULL(sb.quantity, 0) > 0")
			conditions.append("IFNULL(sb.quantity, 0) < IFNULL(i.minimum_stock, 0)")
		elif filters.get("risk_status") == "At Minimum":
			conditions.append("IFNULL(sb.quantity, 0) = IFNULL(i.minimum_stock, 0)")

	return " AND ".join(conditions)


def get_report_summary(data):
	total_items = len({row.get("item") for row in data if row.get("item")})
	locations = len({row.get("stock_location") for row in data if row.get("stock_location")})
	out_of_stock = sum(1 for row in data if row.get("risk_status") == "Out of Stock")
	low_stock = sum(1 for row in data if row.get("risk_status") == "Low Stock")
	at_minimum = sum(1 for row in data if row.get("risk_status") == "At Minimum")
	total_shortage = sum(row.get("shortage_qty") or 0 for row in data)
	potential_sales_gap = sum(row.get("potential_sales_gap") or 0 for row in data)

	return [
		{"value": total_items, "label": "Risk Items", "datatype": "Int"},
		{"value": locations, "label": "Locations", "datatype": "Int"},
		{"value": out_of_stock, "label": "Out of Stock Rows", "datatype": "Int"},
		{"value": low_stock, "label": "Low Stock Rows", "datatype": "Int"},
		{"value": at_minimum, "label": "At Minimum Rows", "datatype": "Int"},
		{"value": total_shortage, "label": "Shortage Qty", "datatype": "Float"},
		{"value": potential_sales_gap, "label": "Sales Gap", "datatype": "Currency"},
	]
