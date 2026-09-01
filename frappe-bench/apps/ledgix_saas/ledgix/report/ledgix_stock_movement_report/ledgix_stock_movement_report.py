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
				No stock movement data found for the selected filters.
			</div>
		"""

	return columns, data, message, None, summary


def _prepare_scope(filters):
	allowed = get_allowed_branches()
	if filters.get("branch"):
		if filters.branch not in allowed:
			frappe.throw("You are not allowed to view movements for this Branch.", frappe.PermissionError)
		allowed = [filters.branch]
	filters.allowed_branches = tuple(allowed or ["__NO_ALLOWED_BRANCH__"])

	if filters.get("stock_location"):
		location_branch = frappe.db.get_value(
			"Ledgix Stock Location",
			filters.stock_location,
			"branch",
		)
		if not location_branch or location_branch not in allowed:
			frappe.throw("You are not allowed to view this Stock Location.", frappe.PermissionError)
		if filters.get("branch") and location_branch != filters.branch:
			frappe.throw("Stock Location does not belong to the selected Branch.")


def get_columns():
	return [
		{"label": "Movement ID", "fieldname": "movement", "fieldtype": "Link", "options": "Ledgix Stock Movement", "width": 155},
		{"label": "Date", "fieldname": "movement_date", "fieldtype": "Datetime", "width": 155},
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Ledgix Branch", "width": 120},
		{"label": "Stock Location", "fieldname": "stock_location", "fieldtype": "Link", "options": "Ledgix Stock Location", "width": 150},
		{"label": "Item", "fieldname": "item", "fieldtype": "Link", "options": "Ledgix Item", "width": 190},
		{"label": "Movement Type", "fieldname": "movement_type", "fieldtype": "Data", "width": 130},
		{"label": "Source", "fieldname": "movement_source", "fieldtype": "Data", "width": 115},
		{"label": "Qty", "fieldname": "quantity", "fieldtype": "Float", "width": 95},
		{"label": "Valuation Rate", "fieldname": "valuation_rate", "fieldtype": "Currency", "width": 120},
		{"label": "Reference Type", "fieldname": "reference_doctype", "fieldtype": "Data", "width": 145},
		{"label": "Reference ID", "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 150},
		{"label": "Reference Note", "fieldname": "reference_note", "fieldtype": "Data", "width": 180},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 105},
		{"label": "Created By", "fieldname": "owner", "fieldtype": "Data", "width": 180},
		{"label": "View", "fieldname": "view_action", "fieldtype": "HTML", "width": 60},
		{"label": "Print", "fieldname": "print_action", "fieldtype": "HTML", "width": 60},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	return frappe.db.sql(
		f"""
		SELECT
			sm.name AS movement,
			sm.movement_date,
			sm.branch,
			sm.stock_location,
			sm.item,
			sm.movement_type,
			sm.movement_source,
			IFNULL(sm.quantity, 0) AS quantity,
			IFNULL(sm.valuation_rate, 0) AS valuation_rate,
			sm.reference_doctype,
			sm.reference_name,
			sm.reference_note,
			CASE
				WHEN sm.docstatus = 0 THEN 'Draft'
				WHEN sm.docstatus = 1 THEN 'Submitted'
				WHEN sm.docstatus = 2 THEN 'Cancelled'
				ELSE 'Unknown'
			END AS status,
			sm.owner,
			sm.name AS view_action,
			sm.name AS print_action
		FROM `tabLedgix Stock Movement` sm
		WHERE {conditions}
		ORDER BY sm.movement_date DESC, sm.creation DESC
		""",
		filters,
		as_dict=True,
	)


def get_conditions(filters):
	conditions = ["sm.branch IN %(allowed_branches)s"]

	if filters.get("branch"):
		conditions.append("sm.branch = %(branch)s")
	if filters.get("stock_location"):
		conditions.append("sm.stock_location = %(stock_location)s")
	if filters.get("from_date"):
		conditions.append("DATE(sm.movement_date) >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("DATE(sm.movement_date) <= %(to_date)s")
	if filters.get("item"):
		conditions.append("sm.item = %(item)s")
	if filters.get("movement_type"):
		conditions.append("sm.movement_type = %(movement_type)s")
	if filters.get("movement_source"):
		conditions.append("sm.movement_source = %(movement_source)s")
	if filters.get("reference_doctype"):
		conditions.append("sm.reference_doctype = %(reference_doctype)s")
	if filters.get("reference_name"):
		conditions.append("sm.reference_name = %(reference_name)s")

	if filters.get("docstatus"):
		status_map = {"Draft": 0, "Submitted": 1, "Cancelled": 2}
		docstatus = status_map.get(filters.get("docstatus"))
		if docstatus is not None:
			filters["docstatus_value"] = docstatus
			conditions.append("sm.docstatus = %(docstatus_value)s")

	return " AND ".join(conditions)


def get_report_summary(data):
	total_movements = len(data)
	in_qty = sum(row.get("quantity") or 0 for row in data if row.get("movement_type") == "IN")
	out_qty = sum(row.get("quantity") or 0 for row in data if row.get("movement_type") == "OUT")
	adjustment_delta = 0
	for row in data:
		if row.get("movement_type") != "ADJUSTMENT":
			continue
		movement = row.get("movement")
		previous = frappe.db.get_value("Ledgix Stock Movement", movement, "previous_quantity")
		adjustment_delta += (row.get("quantity") or 0) - (previous or 0)

	return [
		{"value": total_movements, "label": "Movements", "datatype": "Int"},
		{"value": in_qty, "label": "Total IN", "datatype": "Float"},
		{"value": out_qty, "label": "Total OUT", "datatype": "Float"},
		{"value": adjustment_delta, "label": "Adjustment Delta", "datatype": "Float"},
		{"value": in_qty - out_qty + adjustment_delta, "label": "Net Qty Delta", "datatype": "Float"},
	]
