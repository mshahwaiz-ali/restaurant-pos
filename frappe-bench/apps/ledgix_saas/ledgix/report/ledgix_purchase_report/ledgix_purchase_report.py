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
				No purchase data found for selected filters.
			</div>
		"""

	return columns, data, message, None, summary


def _prepare_scope(filters):
	allowed = get_allowed_branches()
	if filters.get("branch"):
		if filters.branch not in allowed:
			frappe.throw("You are not allowed to view purchases for this Branch.", frappe.PermissionError)
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
		{"label": "Purchase ID", "fieldname": "purchase", "fieldtype": "Link", "options": "Ledgix Purchase", "width": 145},
		{"label": "Invoice No", "fieldname": "invoice_number", "fieldtype": "Data", "width": 130},
		{"label": "Date", "fieldname": "purchase_date", "fieldtype": "Date", "width": 105},
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Ledgix Branch", "width": 120},
		{"label": "Receiving Location", "fieldname": "stock_location", "fieldtype": "Link", "options": "Ledgix Stock Location", "width": 150},
		{"label": "Supplier", "fieldname": "supplier", "fieldtype": "Link", "options": "Ledgix Supplier", "width": 180},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 105},
		{"label": "Items", "fieldname": "items_count", "fieldtype": "Int", "width": 80},
		{"label": "Total Qty", "fieldname": "total_qty", "fieldtype": "Float", "width": 110},
		{"label": "Total Cost", "fieldname": "total_cost", "fieldtype": "Currency", "width": 135},
		{"label": "Avg Cost", "fieldname": "avg_cost", "fieldtype": "Currency", "width": 120},
		{"label": "View", "fieldname": "view_action", "fieldtype": "HTML", "width": 60},
		{"label": "Print", "fieldname": "print_action", "fieldtype": "HTML", "width": 60},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			p.name AS purchase,
			p.invoice_number,
			p.purchase_date,
			p.branch,
			p.stock_location,
			p.supplier,
			CASE
				WHEN p.docstatus = 0 THEN 'Draft'
				WHEN p.docstatus = 1 THEN 'Submitted'
				WHEN p.docstatus = 2 THEN 'Cancelled'
			END AS status,
			COUNT(pi.name) AS items_count,
			IFNULL(SUM(pi.quantity), 0) AS total_qty,
			IFNULL(SUM(pi.amount), 0) AS total_cost,
			CASE
				WHEN IFNULL(SUM(pi.quantity), 0) > 0
				THEN IFNULL(SUM(pi.amount), 0) / IFNULL(SUM(pi.quantity), 0)
				ELSE 0
			END AS avg_cost,
			p.name AS view_action,
			p.name AS print_action
		FROM `tabLedgix Purchase` p
		LEFT JOIN `tabLedgix Purchase Item` pi ON pi.parent = p.name
		WHERE {conditions}
		GROUP BY
			p.name,
			p.invoice_number,
			p.purchase_date,
			p.branch,
			p.stock_location,
			p.supplier,
			p.docstatus
		ORDER BY p.purchase_date DESC, p.creation DESC
		""",
		filters,
		as_dict=True,
	)


def get_conditions(filters):
	conditions = ["p.branch IN %(allowed_branches)s"]

	if filters.get("branch"):
		conditions.append("p.branch = %(branch)s")
	if filters.get("stock_location"):
		conditions.append("p.stock_location = %(stock_location)s")
	if filters.get("from_date"):
		conditions.append("p.purchase_date >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("p.purchase_date <= %(to_date)s")
	if filters.get("supplier"):
		conditions.append("p.supplier = %(supplier)s")

	if filters.get("docstatus"):
		status_map = {"Draft": 0, "Submitted": 1, "Cancelled": 2}
		filters["docstatus_value"] = status_map.get(filters.get("docstatus"))
		conditions.append("p.docstatus = %(docstatus_value)s")

	return " AND ".join(conditions)


def get_report_summary(data):
	total_purchases = len(data)
	total_items = sum(row.get("items_count") or 0 for row in data)
	total_qty = sum(row.get("total_qty") or 0 for row in data)
	total_cost = sum(row.get("total_cost") or 0 for row in data)
	avg_cost = total_cost / total_qty if total_qty else 0
	branches = len({row.get("branch") for row in data if row.get("branch")})

	return [
		{"value": total_purchases, "label": "Purchases", "datatype": "Int"},
		{"value": branches, "label": "Branches", "datatype": "Int"},
		{"value": total_items, "label": "Line Items", "datatype": "Int"},
		{"value": total_qty, "label": "Total Qty", "datatype": "Float"},
		{"value": total_cost, "label": "Total Cost", "datatype": "Currency"},
		{"value": avg_cost, "label": "Avg Cost", "datatype": "Currency"},
	]
