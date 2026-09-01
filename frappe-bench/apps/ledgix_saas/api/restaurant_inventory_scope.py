from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.api import business_intelligence as core
from ledgix_saas.services.organization import ensure_branch_access, get_allowed_branches


LOT_FIELDS = list(core.LOT_FIELDS) + ["branch", "stock_location"]
SERIAL_FIELDS = list(core.SERIAL_FIELDS) + ["branch", "stock_location"]


def normalize_scope(branch=None, stock_location=None):
	allowed = get_allowed_branches()
	branch = str(branch or "").strip() or None
	stock_location = str(stock_location or "").strip() or None

	if branch:
		ensure_branch_access(branch)
		allowed = [branch]

	if stock_location:
		location = frappe.db.get_value(
			"Ledgix Stock Location",
			{"name": stock_location, "is_active": 1},
			["name", "branch"],
			as_dict=True,
		)
		if not location:
			frappe.throw("Selected Stock Location is inactive or does not exist.")
		if location.branch not in allowed:
			frappe.throw("You are not allowed to view this Stock Location.", frappe.PermissionError)
		if branch and location.branch != branch:
			frappe.throw("Stock Location does not belong to the selected Branch.")
		branch = branch or location.branch
		allowed = [location.branch]

	return {
		"branch": branch,
		"stock_location": stock_location,
		"allowed_branches": tuple(allowed or ["__NO_ALLOWED_BRANCH__"]),
	}


def attach_scope(filters, branch=None, stock_location=None):
	scope = normalize_scope(branch, stock_location)
	filters = dict(filters or {})
	filters.update(scope)
	return filters


def scoped_balance_map(item_names, filters):
	item_names = core.unique(item_names or [])
	if not item_names:
		return {}

	conditions = [
		"sb.item IN %(item_names)s",
		"sb.branch IN %(allowed_branches)s",
	]
	params = {
		"item_names": tuple(item_names),
		"allowed_branches": filters.get("allowed_branches"),
	}
	if filters.get("branch"):
		conditions.append("sb.branch = %(branch)s")
		params["branch"] = filters.get("branch")
	if filters.get("stock_location"):
		conditions.append("sb.stock_location = %(stock_location)s")
		params["stock_location"] = filters.get("stock_location")

	rows = frappe.db.sql(
		f"""
		SELECT sb.item,
		       COALESCE(SUM(sb.quantity), 0) AS quantity
		FROM `tabLedgix Stock Balance` sb
		WHERE {' AND '.join(conditions)}
		GROUP BY sb.item
		""",
		params,
		as_dict=True,
	)
	return {row.item: flt(row.quantity) for row in rows}


def apply_scoped_item_balances(items, filters):
	items = items or {}
	balances = scoped_balance_map(list(items.keys()), filters)
	for name, row in items.items():
		row["aggregate_stock"] = flt(row.get("current_stock"))
		row["current_stock"] = flt(balances.get(name))
		minimum = flt(row.get("minimum_stock"))
		current = flt(row.get("current_stock"))
		row["stock_status"] = (
			"Out of Stock"
			if current <= 0
			else "Low Stock"
			if current <= minimum
			else "In Stock"
		)
	return items


def get_normal_stock_item_map(filters):
	item_filters = {"tracking_type": "Normal"}
	if filters.get("item"):
		item_filters["name"] = filters.get("item")

	rows = frappe.get_all(
		"Ledgix Item",
		filters=item_filters,
		fields=[
			"name",
			"item_code",
			"item_name",
			"barcode",
			"category",
			"unit",
			"current_stock",
			"minimum_stock",
			"stock_status",
			"active",
			"sku",
			"tracking_type",
		],
		order_by="modified desc",
		limit_page_length=1 if filters.get("item") else 5000,
	)

	items = {row.name: row for row in rows}
	apply_scoped_item_balances(items, filters)

	search = (filters.get("search") or "").lower()
	if search and filters.get("entity_type") not in ("purchase", "sale"):
		items = {
			name: row
			for name, row in items.items()
			if search in " ".join(
				str(row.get(field) or "")
				for field in (
					"name",
					"item_code",
					"item_name",
					"sku",
					"barcode",
					"stock_status",
				)
			).lower()
		}
	return items


def _append_parent_scope(conditions, params, alias, filters):
	conditions.append(f"{alias}.branch IN %(allowed_branches)s")
	params["allowed_branches"] = filters.get("allowed_branches")
	if filters.get("branch"):
		conditions.append(f"{alias}.branch = %(branch)s")
		params["branch"] = filters.get("branch")
	if filters.get("stock_location"):
		conditions.append(f"{alias}.stock_location = %(stock_location)s")
		params["stock_location"] = filters.get("stock_location")


def get_normal_purchase_rows(item_names, filters):
	if not item_names or filters.get("entity_type") == "sale":
		return []

	conditions = ["p.docstatus = 1", "pi.item IN %(item_names)s"]
	params = {"item_names": tuple(item_names)}
	_append_parent_scope(conditions, params, "p", filters)

	if filters.get("entity_type") == "purchase" and filters.get("entity_value"):
		conditions.append("p.name = %(purchase)s")
		params["purchase"] = filters.get("entity_value")

	core.append_sql_date_condition(conditions, params, "p.purchase_date", filters)
	core.append_sql_search_condition(
		conditions,
		params,
		filters,
		("p.name", "p.supplier", "p.invoice_number", "pi.item"),
		allow_for_entities=(None, "item"),
	)

	return frappe.db.sql(
		f"""
		SELECT
			pi.name AS row_name,
			pi.parent AS purchase,
			p.branch,
			p.stock_location,
			p.supplier AS supplier,
			p.purchase_date AS purchase_date,
			p.invoice_number AS purchase_invoice,
			pi.item AS item,
			pi.quantity AS quantity,
			pi.rate AS rate,
			pi.amount AS amount,
			pi.total_amount AS total_amount,
			pi.creation AS creation
		FROM `tabLedgix Purchase Item` pi
		INNER JOIN `tabLedgix Purchase` p ON p.name = pi.parent
		WHERE {' AND '.join(conditions)}
		ORDER BY p.purchase_date ASC, pi.creation ASC
		LIMIT 2000
		""",
		params,
		as_dict=True,
	)


def get_normal_sale_rows(item_names, filters):
	if not item_names or filters.get("entity_type") == "purchase":
		return []

	conditions = ["s.docstatus = 1", "si.item IN %(item_names)s"]
	params = {"item_names": tuple(item_names)}
	_append_parent_scope(conditions, params, "s", filters)

	if filters.get("entity_type") == "sale" and filters.get("entity_value"):
		conditions.append("s.name = %(sale)s")
		params["sale"] = filters.get("entity_value")

	core.append_sql_date_condition(conditions, params, "s.sale_date", filters)
	core.append_sql_search_condition(
		conditions,
		params,
		filters,
		("s.name", "s.customer", "s.invoice_number", "si.item"),
		allow_for_entities=(None, "item"),
	)

	return frappe.db.sql(
		f"""
		SELECT
			si.name AS row_name,
			si.parent AS sale,
			s.branch,
			s.stock_location,
			s.customer AS customer,
			s.sale_date AS sale_date,
			s.invoice_number AS sale_invoice,
			si.item AS item,
			si.quantity AS quantity,
			si.rate AS rate,
			si.amount AS amount,
			si.cost_price AS cost_price,
			si.item_total_profit AS item_total_profit,
			si.creation AS creation
		FROM `tabLedgix Sale Item` si
		INNER JOIN `tabLedgix Sale` s ON s.name = si.parent
		WHERE {' AND '.join(conditions)}
		ORDER BY s.sale_date ASC, si.creation ASC
		LIMIT 2000
		""",
		params,
		as_dict=True,
	)


def get_normal_return_rows(item_names, filters):
	if not item_names or filters.get("entity_type") == "purchase":
		return []

	conditions = ["r.docstatus = 1", "ri.item IN %(item_names)s"]
	params = {"item_names": tuple(item_names)}
	_append_parent_scope(conditions, params, "r", filters)

	if filters.get("entity_type") == "sale" and filters.get("entity_value"):
		conditions.append("r.original_sale = %(sale)s")
		params["sale"] = filters.get("entity_value")

	core.append_sql_date_condition(conditions, params, "DATE(r.creation)", filters)
	core.append_sql_search_condition(
		conditions,
		params,
		filters,
		("r.name", "r.original_sale", "r.customer", "ri.item"),
		allow_for_entities=(None, "item"),
	)

	return frappe.db.sql(
		f"""
		SELECT
			ri.name AS row_name,
			ri.parent AS sales_return,
			r.branch,
			r.stock_location,
			r.original_sale AS original_sale,
			r.customer AS customer,
			DATE(r.creation) AS return_date,
			ri.item AS item,
			ri.quantity AS quantity,
			ri.rate AS rate,
			ri.amount AS amount,
			ri.cost_price AS cost_price,
			ri.item_total_profit AS item_total_profit,
			ri.creation AS creation
		FROM `tabLedgix Sales Return Item` ri
		INNER JOIN `tabLedgix Sales Return` r ON r.name = ri.parent
		WHERE {' AND '.join(conditions)}
		ORDER BY r.creation ASC, ri.creation ASC
		LIMIT 2000
		""",
		params,
		as_dict=True,
	)


def get_lots(filters):
	lot_filters = {"branch": ["in", filters.get("allowed_branches")]}
	tracking_type = filters.get("tracking_type") or "All"
	entity_type = filters.get("entity_type")
	entity_value = filters.get("entity_value")

	if tracking_type in ("Normal Stock", "Serial Based"):
		return []
	if filters.get("branch"):
		lot_filters["branch"] = filters.get("branch")
	if filters.get("stock_location"):
		lot_filters["stock_location"] = filters.get("stock_location")

	if entity_type == "lot" and entity_value:
		lot_filters["name"] = entity_value
	elif entity_type == "purchase" and entity_value:
		lot_filters["purchase"] = entity_value
	elif entity_type == "sale" and entity_value:
		lot_names = frappe.get_all(
			"Ledgix Stock Lot Allocation",
			filters={"sale": entity_value, "is_reversed": 0},
			pluck="stock_lot",
			limit_page_length=5000,
		)
		lot_names = core.unique(lot_names)
		if not lot_names:
			return []
		lot_filters["name"] = ["in", lot_names]
	elif filters.get("item"):
		lot_filters["item"] = filters.get("item")

	if tracking_type in ("All", "Lot Based"):
		item_names = frappe.get_all(
			"Ledgix Item",
			filters={"tracking_type": "Lot Based"},
			pluck="name",
			limit_page_length=5000,
		)
		if not item_names:
			return []
		if lot_filters.get("item") and lot_filters.get("item") not in item_names:
			return []
		if not lot_filters.get("item"):
			lot_filters["item"] = ["in", item_names]

	if filters.get("from_date") and filters.get("to_date"):
		lot_filters["purchase_date"] = ["between", [filters.get("from_date"), filters.get("to_date")]]
	elif filters.get("from_date"):
		lot_filters["purchase_date"] = [">=", filters.get("from_date")]
	elif filters.get("to_date"):
		lot_filters["purchase_date"] = ["<=", filters.get("to_date")]

	lots = frappe.get_all(
		"Ledgix Stock Lot",
		filters=lot_filters,
		fields=LOT_FIELDS,
		order_by="purchase_date desc, creation desc",
		limit_page_length=500,
	)

	search = (filters.get("search") or "").lower()
	if search and entity_type not in ("lot", "purchase", "sale"):
		lots = [
			lot
			for lot in lots
			if search
			in " ".join(
				str(lot.get(field) or "")
				for field in (
					"name",
					"item",
					"supplier",
					"purchase",
					"status",
					"branch",
					"stock_location",
				)
			).lower()
		]
	return lots


def get_serials(filters):
	serial_filters = {"branch": ["in", filters.get("allowed_branches")]}
	entity_type = filters.get("entity_type")
	entity_value = filters.get("entity_value")

	if filters.get("branch"):
		serial_filters["branch"] = filters.get("branch")
	if filters.get("stock_location"):
		serial_filters["stock_location"] = filters.get("stock_location")

	if entity_type == "serial" and entity_value:
		serial_filters["name"] = entity_value
	elif entity_type == "purchase" and entity_value:
		serial_filters["purchase"] = entity_value
	elif entity_type == "sale" and entity_value:
		serial_filters["sale"] = entity_value
	elif filters.get("item"):
		serial_filters["item"] = filters.get("item")
	elif filters.get("tracking_type") == "Serial Based":
		item_names = frappe.get_all(
			"Ledgix Item",
			filters={"tracking_type": "Serial Based"},
			pluck="name",
			limit_page_length=5000,
		)
		if not item_names:
			return []
		serial_filters["item"] = ["in", item_names]

	serials = frappe.get_all(
		"Ledgix Stock Serial",
		filters=serial_filters,
		fields=SERIAL_FIELDS,
		order_by="purchase_date desc, creation desc",
		limit_page_length=1000,
	)

	if entity_type == "serial" and entity_value:
		serials = [row for row in serials if row.name == entity_value or row.serial_no == entity_value]

	search = (filters.get("search") or "").lower()
	if search and entity_type != "serial":
		serials = [
			row
			for row in serials
			if search
			in " ".join(
				str(row.get(field) or "")
				for field in (
					"name",
					"serial_no",
					"item",
					"status",
					"purchase",
					"supplier",
					"sale",
					"customer",
					"sales_return",
					"branch",
					"stock_location",
				)
			).lower()
		]

	return [row for row in serials if core.serial_matches_date_range(row, filters)]
