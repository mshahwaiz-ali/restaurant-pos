from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.services.organization import ensure_branch_access, get_default_branch
from ledgix_saas.services.stock import get_location_stock


def _branch(branch=None):
	branch = branch or get_default_branch()
	if not branch:
		frappe.throw("No active Branch is configured.")
	return ensure_branch_access(branch)


def _open_po_quantities(branch, stock_location=None):
	if not frappe.db.exists("DocType", "Ledgix Purchase Order"):
		return {}
	params = [branch]
	location_sql = ""
	if stock_location:
		location_sql = " AND po.stock_location=%s"
		params.append(stock_location)
	rows = frappe.db.sql(
		f"""
		SELECT po.stock_location,
		       poi.item,
		       COALESCE(SUM(poi.outstanding_stock_quantity), 0) AS outstanding_qty
		FROM `tabLedgix Purchase Order Item` poi
		INNER JOIN `tabLedgix Purchase Order` po ON po.name = poi.parent
		WHERE po.docstatus = 1
		  AND po.status IN ('Open', 'Partially Received')
		  AND po.branch = %s
		  {location_sql}
		GROUP BY po.stock_location, poi.item
		""",
		tuple(params),
		as_dict=True,
	)
	return {(row.stock_location, row.item): flt(row.outstanding_qty, 6) for row in rows}


def get_inventory_overview(branch=None, stock_location=None, query=None, below_minimum=False):
	branch = _branch(branch)
	if stock_location:
		location_branch = frappe.db.get_value(
			"Ledgix Stock Location",
			{"name": stock_location, "is_active": 1},
			"branch",
		)
		if location_branch != branch:
			frappe.throw("Stock Location does not belong to the selected Branch.")

	balance_filters = {"branch": branch}
	if stock_location:
		balance_filters["stock_location"] = stock_location
	balances = frappe.get_all(
		"Ledgix Stock Balance",
		filters=balance_filters,
		fields=["stock_location", "item", "quantity", "valuation_rate", "stock_value"],
		limit_page_length=0,
	)
	balance_map = {(row.stock_location, row.item): row for row in balances}

	rule_filters = {"branch": branch, "is_active": 1}
	if stock_location:
		rule_filters["stock_location"] = stock_location
	rules = frappe.get_all(
		"Ledgix Reorder Rule",
		filters=rule_filters,
		fields=[
			"name", "stock_location", "item", "minimum_quantity", "target_quantity",
			"preferred_supplier", "lead_time_days",
		],
		limit_page_length=0,
	) if frappe.db.exists("DocType", "Ledgix Reorder Rule") else []
	rule_map = {(row.stock_location, row.item): row for row in rules}

	keys = set(balance_map) | set(rule_map)
	if query:
		text = str(query).strip().lower()
		matched_items = set(
			frappe.get_all(
				"Ledgix Item",
				filters={"active": 1},
				or_filters=[
					["Ledgix Item", "item_name", "like", f"%{text}%"],
					["Ledgix Item", "item_code", "like", f"%{text}%"],
				],
				pluck="name",
				limit_page_length=0,
			)
		)
		keys = {key for key in keys if key[1] in matched_items}

	item_names = list({item for _location, item in keys})
	item_meta = {
		row.name: row
		for row in frappe.get_all(
			"Ledgix Item",
			filters={"name": ["in", item_names]} if item_names else {"name": "__none__"},
			fields=["name", "item_code", "item_name", "restaurant_item_type", "stock_uom", "active", "track_inventory"],
			limit_page_length=0,
		)
	}
	location_names = list({location for location, _item in keys})
	locations = {
		row.name: row
		for row in frappe.get_all(
			"Ledgix Stock Location",
			filters={"name": ["in", location_names]} if location_names else {"name": "__none__"},
			fields=["name", "location_name", "location_type"],
			limit_page_length=0,
		)
	}
	on_order = _open_po_quantities(branch, stock_location)

	rows = []
	for location, item in sorted(keys):
		meta = item_meta.get(item)
		if not meta or not int(meta.active or 0) or not int(meta.track_inventory or 0):
			continue
		balance = balance_map.get((location, item))
		rule = rule_map.get((location, item))
		current = flt(balance.quantity if balance else get_location_stock(item, location), 6)
		minimum = flt(rule.minimum_quantity if rule else 0, 6)
		target = flt(rule.target_quantity if rule else 0, 6)
		po_qty = flt(on_order.get((location, item)), 6)
		is_low = bool(rule and current <= minimum + 0.000001)
		suggested = flt(max(target - current - po_qty, 0), 6) if rule else 0
		if below_minimum and not is_low:
			continue
		location_meta = locations.get(location)
		rows.append({
			"branch": branch,
			"stock_location": location,
			"stock_location_name": location_meta.location_name if location_meta else location,
			"location_type": location_meta.location_type if location_meta else None,
			"item": item,
			"item_code": meta.item_code,
			"item_name": meta.item_name,
			"restaurant_item_type": meta.restaurant_item_type,
			"stock_uom": meta.stock_uom,
			"quantity": current,
			"valuation_rate": flt(balance.valuation_rate if balance else 0, 6),
			"stock_value": flt(balance.stock_value if balance else 0, 4),
			"reorder_rule": rule.name if rule else None,
			"minimum_quantity": minimum,
			"target_quantity": target,
			"on_purchase_order": po_qty,
			"suggested_order_quantity": suggested,
			"preferred_supplier": rule.preferred_supplier if rule else None,
			"lead_time_days": int(rule.lead_time_days or 0) if rule else 0,
			"reorder_status": "Reorder" if is_low and suggested > 0 else ("Covered by PO" if is_low else "OK"),
		})
	return {"branch": branch, "stock_location": stock_location, "items": rows}


def get_reorder_suggestions(branch=None, stock_location=None, supplier=None):
	overview = get_inventory_overview(branch, stock_location, below_minimum=True)
	rows = overview["items"]
	if supplier:
		rows = [row for row in rows if row.get("preferred_supplier") == supplier]
	return {
		"branch": overview["branch"],
		"stock_location": stock_location,
		"suggestions": rows,
		"needs_order": [row for row in rows if flt(row.get("suggested_order_quantity")) > 0],
	}
