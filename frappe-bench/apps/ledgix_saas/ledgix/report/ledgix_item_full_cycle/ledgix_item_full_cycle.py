# Copyright (c) 2026, Ali and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.utils import flt, get_datetime, getdate

from ledgix_saas.api.inventory_intelligence import get_inventory_intelligence_data
from ledgix_saas.api.restaurant_inventory_scope import normalize_scope, scoped_balance_map
from ledgix_saas.api.security import require_ledgix_manager_or_above


STRICT_INVENTORY_MODE = "Strict Inventory"


def execute(filters=None):
	"""Compatibility lifecycle report over the restaurant-scoped intelligence engine.

	The original report carried its own purchase/sale/return/lot calculations. That
	created a second stock truth and could not safely support multiple branches. The
	UI contract is retained here while all source activity comes from the same
	branch-aware service used by Inventory Intelligence.
	"""
	require_ledgix_manager_or_above()
	filters = frappe._dict(filters or {})
	columns = get_columns()

	if not filters.get("item"):
		message = """
			<div style="padding: 20px; text-align: center; color: #667085;">
				Please select an item to view inventory intelligence.
			</div>
		"""
		return columns, [], message, None, []

	if filters.get("from_date") and filters.get("to_date"):
		if getdate(filters.from_date) > getdate(filters.to_date):
			frappe.throw("From Date cannot be after To Date.")

	item_doc = frappe.get_doc("Ledgix Item", filters.item)
	scope = normalize_scope(filters.get("branch"), filters.get("stock_location"))
	response = get_inventory_intelligence_data(
		item=filters.item,
		from_date=filters.get("from_date"),
		to_date=filters.get("to_date"),
		mode="Overview",
		tracking_type="All",
		branch=scope.get("branch"),
		stock_location=scope.get("stock_location"),
	)

	source_rows = response.get("cycle_rows") or response.get("timeline") or []
	rows = [_project_activity_row(row, scope) for row in source_rows]
	rows = [row for row in rows if row.get("event_type")]
	rows.sort(
		key=lambda row: (
			_normalize_datetime(row.get("posting_date")),
			row.get("reference_name") or "",
			row.get("row_key") or "",
		)
	)

	current_stock = flt(
		scoped_balance_map([item_doc.name], {
			"allowed_branches": scope.get("allowed_branches"),
			"branch": scope.get("branch"),
			"stock_location": scope.get("stock_location"),
		}).get(item_doc.name)
	)
	metrics = _build_metrics(rows, response, current_stock, item_doc)
	_apply_flow(rows, current_stock)
	_attach_snapshots(rows, item_doc, metrics, response, scope)

	message = None
	if not rows:
		message = """
			<div style="padding: 20px; text-align: center; color: #667085;">
				No item lifecycle activity found for the selected branch/location filters.
			</div>
		"""

	return columns, rows, message, None, get_report_summary(metrics)


def get_columns():
	return [
		{"label": "Step", "fieldname": "flow_step", "fieldtype": "Data", "width": 75},
		{"label": "Date", "fieldname": "posting_date", "fieldtype": "Datetime", "width": 150},
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Ledgix Branch", "width": 115},
		{"label": "Stock Location", "fieldname": "stock_location", "fieldtype": "Link", "options": "Ledgix Stock Location", "width": 140},
		{"label": "Event", "fieldname": "event_type", "fieldtype": "Data", "width": 115},
		{"label": "Reference", "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 145},
		{"label": "Party", "fieldname": "party", "fieldtype": "Data", "width": 165},
		{"label": "Lot / Serial", "fieldname": "lot_label", "fieldtype": "Data", "width": 125},
		{"label": "Stock Flow", "fieldname": "stock_flow", "fieldtype": "Data", "width": 115},
		{"label": "Qty In", "fieldname": "qty_in", "fieldtype": "Float", "width": 90},
		{"label": "Qty Out", "fieldname": "qty_out", "fieldtype": "Float", "width": 90},
		{"label": "Returned", "fieldname": "qty_returned", "fieldtype": "Float", "width": 95},
		{"label": "Rate", "fieldname": "rate", "fieldtype": "Currency", "width": 100},
		{"label": "Amount", "fieldname": "amount", "fieldtype": "Currency", "width": 110},
		{"label": "Profit", "fieldname": "profit", "fieldtype": "Currency", "width": 110},
		{"label": "Impact", "fieldname": "impact_type", "fieldtype": "Data", "width": 105},
		{"label": "Actions", "fieldname": "open_action", "fieldtype": "HTML", "width": 70},
	]


def _project_activity_row(source, scope):
	row = frappe._dict(source or {})
	event = _event_type(row)
	quantity = flt(
		row.get("quantity")
		or row.get("qty")
		or row.get("purchased_qty")
		or row.get("sale_qty")
		or row.get("sold_qty")
		or row.get("return_qty")
		or row.get("returned_qty")
	)

	qty_in = flt(row.get("qty_in"))
	qty_out = flt(row.get("qty_out"))
	qty_returned = flt(row.get("qty_returned"))
	if event == "PURCHASE" and not qty_in:
		qty_in = flt(row.get("purchased_qty") or quantity)
	elif event == "SALE" and not qty_out:
		qty_out = flt(row.get("sale_qty") or row.get("sold_qty") or quantity)
	elif event == "RETURN" and not qty_returned:
		qty_returned = flt(row.get("return_qty") or row.get("returned_qty") or quantity)

	previous_quantity = row.get("previous_quantity")
	adjustment_quantity = None
	if event == "ADJUSTMENT":
		adjustment_quantity = row.get("current_quantity")
		if adjustment_quantity is None:
			adjustment_quantity = row.get("quantity")
		if adjustment_quantity is None:
			adjustment_quantity = row.get("qty_in")

	reference_doctype, reference_name = _reference(row, event)
	amount = _amount(row, event)
	profit = flt(row.get("profit") or row.get("profit_amount") or row.get("gross_profit"))

	return {
		"row_key": row.get("row_name") or row.get("name") or row.get("serial_no") or row.get("lot_number"),
		"posting_date": _posting_date(row),
		"branch": row.get("branch") or scope.get("branch"),
		"stock_location": row.get("stock_location") or scope.get("stock_location"),
		"event_type": event,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"party": row.get("customer") or row.get("supplier") or row.get("party") or row.get("owner") or "",
		"lot_label": row.get("lot_number") or row.get("serial_no") or row.get("stock_lot") or "",
		"qty_in": qty_in,
		"qty_out": qty_out,
		"qty_returned": qty_returned,
		"previous_quantity": previous_quantity,
		"adjustment_quantity": adjustment_quantity,
		"rate": flt(
			row.get("rate")
			or row.get("sale_rate")
			or row.get("purchase_rate")
			or row.get("unit_cost")
			or row.get("cost_rate")
		),
		"amount": amount,
		"profit": profit,
		"details": row.get("details") or row.get("note") or row.get("reference_note") or "",
		"open_action": reference_name,
	}


def _event_type(row):
	raw = str(
		row.get("event_type")
		or row.get("cycle_status")
		or row.get("movement_source")
		or row.get("transaction_type")
		or ""
	).strip().lower()
	if "return" in raw or "refund" in raw:
		return "RETURN"
	if "purchase" in raw or "receipt" in raw or raw == "in":
		return "PURCHASE"
	if "sale" in raw or "sold" in raw or raw == "out":
		return "SALE"
	if "adjust" in raw or "opening" in raw or "manual" in raw or "transfer" in raw:
		return "ADJUSTMENT"
	return raw.upper() if raw else ""


def _reference(row, event):
	if event == "PURCHASE":
		return "Ledgix Purchase", row.get("purchase") or row.get("reference_name") or ""
	if event == "SALE":
		return "Ledgix Sale", row.get("sale") or row.get("reference_name") or ""
	if event == "RETURN":
		return "Ledgix Sales Return", row.get("sales_return") or row.get("return") or row.get("reference_name") or ""
	if event == "ADJUSTMENT":
		return "Ledgix Stock Movement", row.get("movement") or row.get("stock_movement") or row.get("reference_name") or ""
	return row.get("reference_doctype") or "", row.get("reference_name") or ""


def _posting_date(row):
	return (
		row.get("date")
		or row.get("posting_date")
		or row.get("purchase_date")
		or row.get("sale_date")
		or row.get("return_date")
		or row.get("movement_date")
		or row.get("creation")
	)


def _amount(row, event):
	if event == "PURCHASE":
		return flt(row.get("purchase_amount") or row.get("total_cost") or row.get("amount"))
	if event == "SALE":
		return flt(row.get("selling_amount") or row.get("gross_revenue") or row.get("sale_amount") or row.get("amount"))
	if event == "RETURN":
		return flt(row.get("return_amount") or row.get("amount"))
	return flt(row.get("amount"))


def _normalize_datetime(value):
	if not value:
		return get_datetime("1900-01-01 00:00:00")
	return get_datetime(value)


def _row_delta(row):
	if row.get("event_type") == "ADJUSTMENT":
		previous = row.get("previous_quantity")
		current = row.get("adjustment_quantity")
		if previous is not None and current is not None:
			return flt(current) - flt(previous)
		return 0.0
	return flt(row.get("qty_in")) - flt(row.get("qty_out")) + flt(row.get("qty_returned"))


def _apply_flow(rows, current_stock):
	opening = flt(current_stock) - sum(_row_delta(row) for row in rows)
	balance = opening
	for index, row in enumerate(rows, start=1):
		row["flow_step"] = f"#{index:03d}"
		before = balance
		if row.get("event_type") == "ADJUSTMENT" and row.get("adjustment_quantity") is not None:
			balance = flt(row.get("adjustment_quantity"))
		else:
			balance += _row_delta(row)
		row["stock_before"] = before
		row["stock_after"] = balance
		row["stock_flow"] = f"{_fmt_qty(before)} → {_fmt_qty(balance)}"
		row["impact_type"] = (
			"REVERSAL"
			if row.get("event_type") == "RETURN"
			else "INCREASE"
			if balance > before
			else "DECREASE"
			if balance < before
			else "NEUTRAL"
		)


def _fmt_qty(value):
	value = flt(value)
	return str(int(value)) if value == int(value) else f"{value:g}"


def _build_metrics(rows, response, current_stock, item_doc):
	purchases = [row for row in rows if row.get("event_type") == "PURCHASE"]
	sales = [row for row in rows if row.get("event_type") == "SALE"]
	returns = [row for row in rows if row.get("event_type") == "RETURN"]
	adjustments = [row for row in rows if row.get("event_type") == "ADJUSTMENT"]

	total_purchased = sum(flt(row.get("qty_in")) for row in purchases)
	total_sold = sum(flt(row.get("qty_out")) for row in sales)
	total_returned = sum(flt(row.get("qty_returned")) for row in returns)
	total_revenue = sum(flt(row.get("amount")) for row in sales) - sum(flt(row.get("amount")) for row in returns)
	total_profit = sum(flt(row.get("profit")) for row in rows)
	purchase_amount = sum(flt(row.get("amount")) for row in purchases)
	sale_amount = sum(flt(row.get("amount")) for row in sales)
	lots = response.get("lots") or []
	remaining_lot_qty = sum(flt(row.get("remaining_qty")) for row in lots)
	open_lots = sum(1 for row in lots if str(row.get("lot_status") or row.get("status") or "").lower() in {"open", "available", "active"})
	minimum_stock = flt(getattr(item_doc, "minimum_stock", 0))
	stock_status = "Out of Stock" if current_stock <= 0 else "Low Stock" if current_stock <= minimum_stock else "Healthy"

	return {
		"current_stock": flt(current_stock),
		"minimum_stock": minimum_stock,
		"stock_status": stock_status,
		"total_purchased": total_purchased,
		"total_sold": total_sold,
		"total_returned": total_returned,
		"total_revenue": total_revenue,
		"total_profit": total_profit,
		"profit_margin": (total_profit / total_revenue * 100) if total_revenue else 0,
		"avg_buy_rate": (purchase_amount / total_purchased) if total_purchased else 0,
		"avg_sell_rate": (sale_amount / total_sold) if total_sold else 0,
		"return_ratio": (total_returned / total_sold * 100) if total_sold else 0,
		"remaining_lot_qty": remaining_lot_qty,
		"open_lots": open_lots,
		"adjustment_count": len(adjustments),
	}


def _attach_snapshots(rows, item_doc, metrics, response, scope):
	context = frappe.as_json({
		"story": response.get("story") or {},
		"risks": response.get("risks") or [],
		"customers": [],
		"branch": scope.get("branch"),
		"stock_location": scope.get("stock_location"),
		"authorized_branch_count": len(scope.get("allowed_branches") or []),
	})

	for row in rows:
		row.update({
			"report_mode_snapshot": STRICT_INVENTORY_MODE,
			"item_code_snapshot": item_doc.name,
			"item_name_snapshot": item_doc.item_name,
			"category_snapshot": item_doc.category,
			"current_stock_snapshot": metrics["current_stock"],
			"minimum_stock_snapshot": metrics["minimum_stock"],
			"stock_status_snapshot": metrics["stock_status"],
			"total_purchased_snapshot": metrics["total_purchased"],
			"total_sold_snapshot": metrics["total_sold"],
			"total_returned_snapshot": metrics["total_returned"],
			"total_revenue_snapshot": metrics["total_revenue"],
			"total_profit_snapshot": metrics["total_profit"],
			"profit_margin_snapshot": metrics["profit_margin"],
			"avg_buy_rate_snapshot": metrics["avg_buy_rate"],
			"avg_sell_rate_snapshot": metrics["avg_sell_rate"],
			"return_ratio_snapshot": metrics["return_ratio"],
			"health_score_snapshot": metrics["stock_status"],
			"remaining_lot_qty_snapshot": metrics["remaining_lot_qty"],
			"open_lots_snapshot": metrics["open_lots"],
			"adjustment_count_snapshot": metrics["adjustment_count"],
			"intelligence_context": context,
		})


def get_report_summary(metrics):
	return [
		{"value": metrics["current_stock"], "label": "Current Stock", "datatype": "Float"},
		{"value": metrics["total_purchased"], "label": "Purchased Qty", "datatype": "Float"},
		{"value": metrics["total_sold"], "label": "Sold Qty", "datatype": "Float"},
		{"value": metrics["total_returned"], "label": "Returned Qty", "datatype": "Float"},
		{"value": metrics["total_revenue"], "label": "Revenue", "datatype": "Currency"},
		{"value": metrics["total_profit"], "label": "Profit", "datatype": "Currency"},
	]
