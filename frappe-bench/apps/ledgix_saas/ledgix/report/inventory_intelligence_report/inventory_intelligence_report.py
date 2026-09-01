# Copyright (c) 2026, Ali and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ledgix_saas.api.inventory_intelligence import get_inventory_intelligence_data


STRICT_INVENTORY_MODE = "Strict Inventory"
BILLING_ONLY_MODE = "Billing Only"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	response = get_inventory_intelligence_data(
		item=filters.item,
		from_date=filters.get("from_date"),
		to_date=filters.get("to_date"),
		mode="Overview",
		tracking_type="All",
		branch=filters.get("branch"),
		stock_location=filters.get("stock_location"),
	)
	rows = response.get("cycle_rows") or response.get("timeline") or []
	if filters.view_mode == BILLING_ONLY_MODE:
		rows = [row for row in rows if (row.get("cycle_status") or row.get("event_type")) in {"Sale", "Return"}]

	data = [to_report_row(row) for row in rows]
	return get_columns(), data, None, None, get_report_summary(filters, data, response)


def validate_filters(filters):
	if not filters.get("item"):
		frappe.throw(_("Please select an Item."))

	if not filters.get("view_mode"):
		filters.view_mode = STRICT_INVENTORY_MODE
	if filters.view_mode not in (STRICT_INVENTORY_MODE, BILLING_ONLY_MODE):
		filters.view_mode = STRICT_INVENTORY_MODE

	if filters.get("from_date") and filters.get("to_date") and getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))


def get_columns():
	return [
		{"label": _("Lot / Serial"), "fieldname": "lot_no", "fieldtype": "Data", "width": 130},
		{"label": _("Stock Status"), "fieldname": "lot_status", "fieldtype": "Data", "width": 105},
		{"label": _("Row Type"), "fieldname": "row_type", "fieldtype": "Data", "width": 90},
		{"label": _("Status"), "fieldname": "cycle_status", "fieldtype": "Data", "width": 115},
		{"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 115},
		{"label": _("Loss"), "fieldname": "loss", "fieldtype": "Currency", "width": 105},
		{"label": _("Current Qty"), "fieldname": "current_lot_qty", "fieldtype": "Float", "precision": 3, "width": 115},
		{"label": _("Purchased Qty"), "fieldname": "purchased_qty", "fieldtype": "Float", "precision": 3, "width": 118},
		{"label": _("Sale Qty"), "fieldname": "sale_qty", "fieldtype": "Float", "precision": 3, "width": 95},
		{"label": _("Return Qty"), "fieldname": "return_qty", "fieldtype": "Float", "precision": 3, "width": 105},
		{"label": _("Net Sold Qty"), "fieldname": "net_sold_qty", "fieldtype": "Float", "precision": 3, "width": 110},
		{"label": _("Unit Cost"), "fieldname": "unit_cost", "fieldtype": "Currency", "width": 105},
		{"label": _("Total Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 115},
		{"label": _("Selling Amount"), "fieldname": "selling_amount", "fieldtype": "Currency", "width": 125},
		{"label": _("Return Amount"), "fieldname": "return_amount", "fieldtype": "Currency", "width": 125},
		{"label": _("Purchase No"), "fieldname": "purchase_no", "fieldtype": "Link", "options": "Ledgix Purchase", "width": 135},
		{"label": _("Purchase Invoice"), "fieldname": "purchase_invoice", "fieldtype": "Data", "width": 135},
		{"label": _("Purchase Date"), "fieldname": "purchase_date", "fieldtype": "Date", "width": 110},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Ledgix Supplier", "width": 145},
		{"label": _("Purchase Rate"), "fieldname": "purchase_rate", "fieldtype": "Currency", "width": 115},
		{"label": _("Purchase Amount"), "fieldname": "purchase_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Sale No"), "fieldname": "sale_no", "fieldtype": "Link", "options": "Ledgix Sale", "width": 135},
		{"label": _("Sale Invoice"), "fieldname": "sale_invoice", "fieldtype": "Data", "width": 120},
		{"label": _("Sale Date"), "fieldname": "sale_date", "fieldtype": "Date", "width": 105},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Ledgix Customer", "width": 145},
		{"label": _("Return No"), "fieldname": "return_no", "fieldtype": "Link", "options": "Ledgix Sales Return", "width": 135},
		{"label": _("Return Date"), "fieldname": "return_date", "fieldtype": "Date", "width": 105},
		{"label": _("Return Reason / Note"), "fieldname": "return_reason", "fieldtype": "Data", "width": 220},
	]


def to_report_row(row):
	row = frappe._dict(row or {})
	purchased_qty = flt(row.get("purchased_qty"))
	unit_cost = flt(row.get("unit_cost") or row.get("cost_rate"))
	profit_value = flt(row.get("profit"))
	gross_profit = flt(row.get("gross_profit"))
	if not profit_value and gross_profit:
		profit_value = max(gross_profit, 0)
	loss_value = flt(row.get("loss"))
	if not loss_value and gross_profit < 0:
		loss_value = abs(gross_profit)

	return {
		"lot_no": row.get("lot_number") or row.get("serial_no") or row.get("item") or "",
		"lot_status": row.get("lot_status") or row.get("serial_status") or row.get("reference_status") or "",
		"row_type": row.get("row_type") or "",
		"cycle_status": row.get("cycle_status") or row.get("event_type") or "",
		"profit": profit_value,
		"loss": loss_value,
		"current_lot_qty": flt(row.get("current_lot_qty") or row.get("remaining_qty")),
		"purchased_qty": purchased_qty,
		"sale_qty": flt(row.get("sale_qty") or row.get("sold_qty")),
		"return_qty": flt(row.get("return_qty") or row.get("returned_qty")),
		"net_sold_qty": flt(row.get("net_sold_qty")),
		"unit_cost": unit_cost,
		"total_cost": flt(row.get("total_cost")),
		"selling_amount": flt(row.get("selling_amount") or row.get("gross_revenue")),
		"return_amount": flt(row.get("return_amount")),
		"purchase_no": row.get("purchase") or "",
		"purchase_invoice": row.get("purchase_invoice") or "",
		"purchase_date": row.get("purchase_date") or "",
		"supplier": row.get("supplier") or "",
		"purchase_rate": flt(row.get("purchase_rate") or row.get("cost_rate") or unit_cost),
		"purchase_amount": flt(row.get("purchase_amount") or (purchased_qty * unit_cost)),
		"sale_no": row.get("sale") or "",
		"sale_invoice": row.get("sale_invoice") or "",
		"sale_date": row.get("sale_date") or "",
		"customer": row.get("customer") or "",
		"return_no": row.get("sales_return") or "",
		"return_date": row.get("return_date") or "",
		"return_reason": row.get("return_reason") or row.get("note") or "",
	}


def get_report_summary(filters, data, response):
	profit = sum(flt(row.get("profit")) for row in data)
	loss = sum(flt(row.get("loss")) for row in data)
	net_profit = profit - loss
	return [
		{"value": len(data), "label": _("Activity Rows"), "datatype": "Int"},
		{"value": sum(flt(row.get("purchased_qty")) for row in data if row.get("cycle_status") == "Purchase"), "label": _("Purchased Qty"), "datatype": "Float"},
		{"value": sum(flt(row.get("sale_qty")) for row in data if row.get("cycle_status") == "Sale"), "label": _("Sale Qty"), "datatype": "Float"},
		{"value": sum(flt(row.get("return_qty")) for row in data if row.get("cycle_status") == "Return"), "label": _("Return Qty"), "datatype": "Float"},
		{"value": net_profit, "label": _("Net Profit"), "datatype": "Currency"},
		{"value": (response.get("summary") or {}).get("current_qty", 0), "label": _("Current Qty"), "datatype": "Float"},
	]
