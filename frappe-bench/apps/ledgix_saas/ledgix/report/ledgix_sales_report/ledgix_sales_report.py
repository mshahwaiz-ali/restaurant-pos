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
				No sales data found for selected filters.
			</div>
		"""

	return columns, data, message, None, summary


def _prepare_scope(filters):
	allowed = get_allowed_branches()
	if filters.get("branch"):
		if filters.branch not in allowed:
			frappe.throw("You are not allowed to view sales for this Branch.", frappe.PermissionError)
		allowed = [filters.branch]
	filters.allowed_branches = tuple(allowed or ["__NO_ALLOWED_BRANCH__"])

	if filters.get("stock_location"):
		location_branch = frappe.db.get_value("Ledgix Stock Location", filters.stock_location, "branch")
		if not location_branch or location_branch not in allowed:
			frappe.throw("You are not allowed to view this Stock Location.", frappe.PermissionError)
		if filters.get("branch") and location_branch != filters.branch:
			frappe.throw("Stock Location does not belong to the selected Branch.")


def get_columns():
	return [
		{"label": "Sale ID", "fieldname": "sale", "fieldtype": "Link", "options": "Ledgix Sale", "width": 135},
		{"label": "Invoice No", "fieldname": "invoice_number", "fieldtype": "Data", "width": 130},
		{"label": "Date", "fieldname": "sale_date", "fieldtype": "Date", "width": 105},
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Ledgix Branch", "width": 120},
		{"label": "Stock Location", "fieldname": "stock_location", "fieldtype": "Link", "options": "Ledgix Stock Location", "width": 145},
		{"label": "Channel", "fieldname": "sale_channel", "fieldtype": "Data", "width": 95},
		{"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Ledgix Customer", "width": 180},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 105},
		{"label": "Items", "fieldname": "items_count", "fieldtype": "Int", "width": 80},
		{"label": "Total Qty", "fieldname": "total_qty", "fieldtype": "Float", "width": 110},
		{"label": "Total Amount", "fieldname": "total_amount", "fieldtype": "Currency", "width": 135},
		{"label": "Total Profit", "fieldname": "total_profit", "fieldtype": "Currency", "width": 130},
		{"label": "Avg Sale Value", "fieldname": "avg_sale_value", "fieldtype": "Currency", "width": 135},
		{"label": "View", "fieldname": "view_action", "fieldtype": "HTML", "width": 60},
		{"label": "Print", "fieldname": "print_action", "fieldtype": "HTML", "width": 60},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			s.name AS sale,
			s.invoice_number,
			s.sale_date,
			s.branch,
			s.stock_location,
			s.sale_channel,
			s.customer,
			CASE
				WHEN s.docstatus = 0 THEN 'Draft'
				WHEN s.docstatus = 1 THEN 'Submitted'
				WHEN s.docstatus = 2 THEN 'Cancelled'
			END AS status,
			COUNT(si.name) AS items_count,
			IFNULL(SUM(si.quantity), 0) AS total_qty,
			IFNULL(s.total_amount, 0) AS total_amount,
			IFNULL(s.total_profit, 0) AS total_profit,
			CASE
				WHEN IFNULL(SUM(si.quantity), 0) > 0
				THEN IFNULL(s.total_amount, 0) / IFNULL(SUM(si.quantity), 0)
				ELSE 0
			END AS avg_sale_value,
			s.name AS view_action,
			s.name AS print_action
		FROM `tabLedgix Sale` s
		LEFT JOIN `tabLedgix Sale Item` si ON si.parent = s.name
		WHERE {conditions}
		GROUP BY
			s.name,
			s.invoice_number,
			s.sale_date,
			s.branch,
			s.stock_location,
			s.sale_channel,
			s.customer,
			s.docstatus,
			s.total_amount,
			s.total_profit
		ORDER BY s.sale_date DESC, s.creation DESC
		""",
		filters,
		as_dict=True,
	)


def get_conditions(filters):
	conditions = ["s.branch IN %(allowed_branches)s"]

	if filters.get("branch"):
		conditions.append("s.branch = %(branch)s")
	if filters.get("stock_location"):
		conditions.append("s.stock_location = %(stock_location)s")
	if filters.get("from_date"):
		conditions.append("s.sale_date >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("s.sale_date <= %(to_date)s")
	if filters.get("customer"):
		conditions.append("s.customer = %(customer)s")
	if filters.get("sale_channel"):
		conditions.append("s.sale_channel = %(sale_channel)s")

	if filters.get("docstatus"):
		status_map = {"Draft": 0, "Submitted": 1, "Cancelled": 2}
		filters["docstatus_value"] = status_map.get(filters.get("docstatus"))
		conditions.append("s.docstatus = %(docstatus_value)s")

	return " AND ".join(conditions)


def get_report_summary(data):
	total_sales = len(data)
	total_items = sum(row.get("items_count") or 0 for row in data)
	total_qty = sum(row.get("total_qty") or 0 for row in data)
	total_amount = sum(row.get("total_amount") or 0 for row in data)
	total_profit = sum(row.get("total_profit") or 0 for row in data)
	avg_sale_value = total_amount / total_sales if total_sales else 0
	branches = len({row.get("branch") for row in data if row.get("branch")})

	return [
		{"value": total_sales, "label": "Sales", "datatype": "Int"},
		{"value": branches, "label": "Branches", "datatype": "Int"},
		{"value": total_items, "label": "Line Items", "datatype": "Int"},
		{"value": total_qty, "label": "Total Qty", "datatype": "Float"},
		{"value": total_amount, "label": "Total Amount", "datatype": "Currency"},
		{"value": total_profit, "label": "Total Profit", "datatype": "Currency"},
		{"value": avg_sale_value, "label": "Avg Sale Value", "datatype": "Currency"},
	]
