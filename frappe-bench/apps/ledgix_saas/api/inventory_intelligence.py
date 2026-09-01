import frappe

from ledgix_saas.api import business_intelligence as core
from ledgix_saas.api import restaurant_inventory_scope as scope
from ledgix_saas.api.security import require_ledgix_manager_or_above


TIMELINE_RESULT_CAP = 500
LOT_RESULT_CAP = 500


@frappe.whitelist()
def get_inventory_intelligence_data(
	item=None,
	from_date=None,
	to_date=None,
	mode="Overview",
	search=None,
	tracking_type="All",
	entity_type=None,
	entity_value=None,
	branch=None,
	stock_location=None,
):
	"""Restaurant-safe inventory intelligence with authorized branch/location scope."""
	require_ledgix_manager_or_above()

	filters = core.normalize_filters(
		item=item,
		from_date=from_date,
		to_date=to_date,
		mode=mode,
		search=search,
		tracking_type=tracking_type,
		entity_type=entity_type,
		entity_value=entity_value,
	)
	filters = scope.attach_scope(filters, branch, stock_location)

	try:
		if core.should_use_serial_intelligence(filters):
			return add_scope_meta(build_serial_data_response(filters))

		if core.should_use_normal_stock_intelligence(filters):
			return add_scope_meta(build_normal_stock_data_response(filters))

		if core.should_use_mixed_intelligence(filters):
			return build_mixed_data_response(filters)

		return add_scope_meta(build_lot_data_response(filters))
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inventory Intelligence API")
		return error_response(filters)


def build_serial_data_response(filters):
	serials = scope.get_serials(filters)
	if not serials:
		response = core.empty_response(filters)
		response["story"] = {
			"title": "No serial activity found",
			"text": "No serial-based stock activity matched the current branch/location filters.",
			"tone": "neutral",
			"signals": [],
		}
		return response

	submitted = core.get_serial_reference_maps(serials)
	items = core.get_items_by_names(core.unique([row.item for row in serials if row.item]))
	scope.apply_scoped_item_balances(items, filters)
	serial_rows = core.build_serial_rows(serials, submitted, items, filters)
	timeline = core.build_serial_timeline(serials, submitted, items, filters)
	summary = core.build_serial_summary(serial_rows, filters)
	story = core.build_serial_story(summary, serial_rows, filters)
	risks = core.build_serial_risks(serials, submitted)

	return {
		"filters": filters,
		"summary": summary,
		"story": story,
		"lots": [],
		"timeline": timeline,
		"cycle_rows": timeline,
		"risks": risks,
		"meta": {
			"generated_at": str(core.now_datetime()),
			"row_count": len(serial_rows),
			"cycle_row_count": len(timeline),
		},
	}


def build_normal_stock_data_response(filters):
	base_filters = without_search(filters)
	items = scope.get_normal_stock_item_map(base_filters)
	if not items:
		return empty_normal_response(filters)

	item_names = list(items.keys())
	purchases = scope.get_normal_purchase_rows(item_names, base_filters)
	sales = scope.get_normal_sale_rows(item_names, base_filters)
	returns = scope.get_normal_return_rows(item_names, base_filters)

	items, purchases, sales, returns = filter_normal_stock_search(
		items,
		purchases,
		sales,
		returns,
		filters,
	)

	if not items:
		return empty_normal_response(filters, search_miss=True)

	if filters.get("entity_type") in ("purchase", "sale"):
		event_items = core.unique(
			[row.item for row in purchases if row.item]
			+ [row.item for row in sales if row.item]
			+ [row.item for row in returns if row.item]
		)
		items = {item_name: items[item_name] for item_name in event_items if item_name in items}

	if not items:
		return empty_normal_response(filters, search_miss=bool(filters.get("search")))

	timeline = core.build_normal_stock_timeline(purchases, sales, returns, items)
	summary = core.build_normal_stock_summary(purchases, sales, returns, items, filters)
	story = core.build_normal_stock_story(summary, timeline, filters)
	risks = core.build_normal_stock_risks(items, summary, timeline)

	return {
		"filters": filters,
		"summary": summary,
		"story": story,
		"lots": [],
		"timeline": timeline,
		"cycle_rows": timeline,
		"risks": risks,
		"meta": {
			"generated_at": str(core.now_datetime()),
			"row_count": len(items),
			"cycle_row_count": len(timeline),
		},
	}


def filter_normal_stock_search(items, purchases, sales, returns, filters):
	search = normalized_search(filters)
	entity_type = filters.get("entity_type")
	if not search or entity_type not in (None, "item"):
		return items, purchases, sales, returns

	item_fields = (
		"name",
		"item_code",
		"item_name",
		"sku",
		"barcode",
		"category",
		"stock_status",
	)
	item_matches = {
		name
		for name, row in items.items()
		if row_matches_search(row, item_fields, search)
	}

	purchases = filter_activity_rows(
		purchases,
		("purchase", "supplier", "purchase_invoice", "item", "row_name", "branch", "stock_location"),
		search,
		item_matches,
	)
	sales = filter_activity_rows(
		sales,
		("sale", "customer", "sale_invoice", "item", "row_name", "branch", "stock_location"),
		search,
		item_matches,
	)
	returns = filter_activity_rows(
		returns,
		("sales_return", "original_sale", "customer", "item", "row_name", "branch", "stock_location"),
		search,
		item_matches,
	)

	matched_items = set(item_matches)
	for row in purchases + sales + returns:
		if row.get("item"):
			matched_items.add(row.get("item"))

	items = {name: row for name, row in items.items() if name in matched_items}
	return items, purchases, sales, returns


def build_lot_data_response(filters):
	search = normalized_search(filters)
	base_filters = without_search(filters)
	lots = scope.get_lots(base_filters)
	if not lots:
		return empty_lot_response(filters, search_miss=bool(search))

	allocations = core.get_allocations(lots)
	submitted = core.get_submitted_reference_maps(lots, allocations)
	items = core.get_item_map(lots, allocations)
	scope.apply_scoped_item_balances(items, filters)

	if not search or filters.get("entity_type") in ("lot", "purchase", "sale"):
		return assemble_lot_response(
			lots,
			allocations,
			submitted,
			items,
			filters,
		)

	base_lot_rows = core.build_lot_rows(lots, allocations, submitted, items, base_filters)
	matching_cycle_rows = core.build_cycle_rows(lots, allocations, submitted, items, filters)
	matched_lot_names = {
		row.get("lot_number")
		for row in matching_cycle_rows
		if row.get("lot_number")
	}

	lot_row_fields = (
		"lot_number",
		"item",
		"item_name",
		"supplier",
		"purchase",
		"lot_status",
		"source_status",
	)
	matched_lot_names.update(
		row.get("lot_number")
		for row in base_lot_rows
		if row.get("lot_number") and row_matches_search(row, lot_row_fields, search)
	)

	item_fields = ("name", "item_code", "item_name", "sku", "barcode", "category", "stock_status")
	matched_items = {
		name
		for name, row in items.items()
		if row_matches_search(row, item_fields, search)
	}
	matched_lot_names.update(lot.name for lot in lots if lot.item in matched_items)
	matched_lot_names.discard(None)

	if not matched_lot_names:
		return empty_lot_response(filters, search_miss=True)

	matched_lots = [lot for lot in lots if lot.name in matched_lot_names]
	matched_allocations = [row for row in allocations if row.stock_lot in matched_lot_names]
	matched_submitted = core.get_submitted_reference_maps(matched_lots, matched_allocations)
	matched_items_map = core.get_item_map(matched_lots, matched_allocations)
	scope.apply_scoped_item_balances(matched_items_map, filters)
	return assemble_lot_response(
		matched_lots,
		matched_allocations,
		matched_submitted,
		matched_items_map,
		base_filters,
		response_filters=filters,
	)


def assemble_lot_response(
	lots,
	allocations,
	submitted,
	items,
	build_filters,
	response_filters=None,
):
	response_filters = response_filters or build_filters
	lot_rows = core.build_lot_rows(lots, allocations, submitted, items, build_filters)
	timeline = core.build_timeline(lots, allocations, submitted, items, build_filters)
	cycle_rows = core.build_cycle_rows(lots, allocations, submitted, items, build_filters)
	risks = core.build_risks(lots, allocations, submitted, items, lot_rows)
	summary = core.build_summary(lot_rows, items, response_filters)
	story = core.build_story(summary, lot_rows, response_filters)

	return {
		"filters": response_filters,
		"summary": summary,
		"story": story,
		"lots": lot_rows,
		"timeline": timeline,
		"cycle_rows": cycle_rows,
		"risks": risks,
		"meta": {
			"generated_at": str(core.now_datetime()),
			"row_count": len(lot_rows),
			"cycle_row_count": len(cycle_rows),
		},
	}


def filter_activity_rows(rows, fields, search, item_matches):
	return [
		row
		for row in rows
		if row.get("item") in item_matches or row_matches_search(row, fields, search)
	]


def row_matches_search(row, fields, search):
	return search in " ".join(str(row.get(field) or "") for field in fields).lower()


def normalized_search(filters):
	return str(filters.get("search") or "").strip().lower()


def without_search(filters):
	base_filters = dict(filters)
	base_filters["search"] = None
	return base_filters


def empty_normal_response(filters, search_miss=False):
	response = core.empty_response(filters)
	response["story"] = {
		"title": "No normal stock activity found" if search_miss else "No normal stock found",
		"text": (
			"No Normal Stock item or submitted purchase, sale, return, customer, or supplier activity matched the current branch/location search."
			if search_miss
			else "No quantity-only Normal Stock items matched the current branch/location filters."
		),
		"tone": "neutral",
		"signals": [],
	}
	return response


def empty_lot_response(filters, search_miss=False):
	response = core.empty_response(filters)
	response["story"] = {
		"title": "No lot activity found" if search_miss else "No lot stock found",
		"text": (
			"No Lot Based item, lot, submitted transaction, customer, or supplier activity matched the current branch/location search."
			if search_miss
			else "No Lot Based stock activity matched the current branch/location filters."
		),
		"tone": "neutral",
		"signals": [],
	}
	return response


def error_response(filters):
	response = core.empty_response(filters)
	response["story"] = {
		"title": "Inventory Intelligence could not load",
		"text": "The server could not calculate this inventory view. Try again, then check the Error Log if the problem continues.",
		"tone": "critical",
		"signals": [],
	}
	response["meta"]["load_error"] = True
	return add_scope_meta(response)


def build_mixed_data_response(filters):
	lot_response = add_scope_meta(build_lot_data_response(dict(filters)))

	normal_filters = dict(filters)
	normal_filters["tracking_type"] = "Normal Stock"
	normal_response = add_scope_meta(build_normal_stock_data_response(normal_filters))

	serial_filters = dict(filters)
	serial_filters["tracking_type"] = "Serial Based"
	serial_response = add_scope_meta(build_serial_data_response(serial_filters))

	responses = [normal_response, lot_response, serial_response]
	timeline = []
	for response in responses:
		timeline.extend(response.get("cycle_rows") or response.get("timeline") or [])
	timeline.sort(
		key=lambda row: core.normalize_datetime(
			row.get("date") or row.get("purchase_date") or row.get("sale_date") or row.get("return_date")
		),
		reverse=True,
	)

	summary = core.merge_summaries([response.get("summary") or {} for response in responses])
	risks = []
	for response in responses:
		risks.extend(response.get("risks") or [])

	loaded_timeline = timeline[:TIMELINE_RESULT_CAP]
	cap_reached = len(timeline) > TIMELINE_RESULT_CAP or any(
		(response.get("meta") or {}).get("timeline_cap_reached")
		for response in responses
	)
	lot_meta = lot_response.get("meta") or {}
	return {
		"filters": filters,
		"summary": summary,
		"story": core.build_mixed_story(summary, responses),
		"lots": lot_response.get("lots") or [],
		"timeline": loaded_timeline,
		"cycle_rows": loaded_timeline,
		"risks": risks[:100],
		"meta": {
			"generated_at": str(core.now_datetime()),
			"row_count": summary.get("lot_count", 0),
			"cycle_row_count": len(loaded_timeline),
			"timeline_loaded_count": len(loaded_timeline),
			"timeline_result_cap": TIMELINE_RESULT_CAP,
			"timeline_cap_reached": bool(cap_reached),
			"lot_loaded_count": lot_meta.get("lot_loaded_count", len(lot_response.get("lots") or [])),
			"lot_result_cap": LOT_RESULT_CAP,
			"lot_cap_reached": bool(lot_meta.get("lot_cap_reached")),
		},
	}


def add_scope_meta(response):
	response = response or {}
	rows = response.get("cycle_rows") or response.get("timeline") or []
	lots = response.get("lots") or []
	filters = response.get("filters") or {}
	meta = response.setdefault("meta", {})
	meta["branch"] = filters.get("branch")
	meta["stock_location"] = filters.get("stock_location")
	meta["authorized_branch_count"] = len(filters.get("allowed_branches") or [])
	meta["timeline_loaded_count"] = len(rows)
	meta["timeline_result_cap"] = TIMELINE_RESULT_CAP
	meta["timeline_cap_reached"] = len(rows) >= TIMELINE_RESULT_CAP
	meta["lot_loaded_count"] = len(lots)
	meta["lot_result_cap"] = LOT_RESULT_CAP
	meta["lot_cap_reached"] = len(lots) >= LOT_RESULT_CAP
	return response
