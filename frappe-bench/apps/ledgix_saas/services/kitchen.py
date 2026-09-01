from __future__ import annotations

import json

import frappe
from frappe.utils import cint, flt, getdate, now_datetime

from ledgix_saas.services.organization import ensure_branch_access
from ledgix_saas.services.restaurant_audit import log_restaurant_operation
from ledgix_saas.services.restaurant_orders import _active_order, _recalculate_item_tax, _recalculate_order, get_order_payload
from ledgix_saas.services.stock import _post_movement


ACTIVE_KDS_STATUSES = {"New", "Preparing", "Ready"}
PRODUCTION_STATUSES = {"Preparing", "Ready", "Bumped"}


def _rows(value):
	if isinstance(value, str):
		value = frappe.parse_json(value)
	return value or []


def _modifier_summary(item):
	labels = []
	for row in item.modifiers or []:
		label = row.kitchen_label_snapshot or row.option_name_snapshot or row.modifier_option
		qty = flt(row.selection_quantity)
		labels.append(f"{qty:g}x {label}" if abs(qty - 1) > 0.000001 else str(label))
	return ", ".join(labels)


def resolve_kitchen_station(branch, order_item):
	ensure_branch_access(branch)
	menu_item = frappe.db.get_value(
		"Ledgix Menu Item",
		order_item.menu_item,
		["name", "menu_section", "item"],
		as_dict=True,
	)
	if not menu_item:
		frappe.throw("Restaurant Order Item has no valid Menu Item for kitchen routing.")

	candidates = []
	for route_type, fieldname, value, specificity in (
		("Menu Item", "menu_item", menu_item.name, 0),
		("Item", "item", menu_item.item, 1),
		("Menu Section", "menu_section", menu_item.menu_section, 2),
	):
		if not value:
			continue
		for row in frappe.get_all(
			"Ledgix Kitchen Route",
			filters={"branch": branch, "route_type": route_type, fieldname: value, "is_active": 1},
			fields=["name", "kitchen_station", "priority"],
			limit_page_length=0,
		):
			candidates.append((cint(row.priority), specificity, row.name, row.kitchen_station))
	if candidates:
		for _priority, _specificity, _name, station in sorted(candidates):
			if frappe.db.exists("Ledgix Kitchen Station", {"name": station, "branch": branch, "is_active": 1}):
				return station

	station = frappe.db.get_value(
		"Ledgix Kitchen Station",
		{"branch": branch, "is_default_station": 1, "is_active": 1},
		"name",
		order_by="display_priority asc, creation asc",
	)
	if not station:
		frappe.throw(f"No Kitchen Station route/default is configured for item {order_item.display_name_snapshot or order_item.item} in Branch {branch}.")
	return station


def get_kot_payload(kot_name):
	kot = frappe.get_doc("Ledgix KOT", kot_name)
	ensure_branch_access(kot.branch)
	items = frappe.get_all(
		"Ledgix KOT Item",
		filters={"kot": kot.name},
		pluck="name",
		order_by="queued_at asc, creation asc",
		limit_page_length=0,
	)
	return {
		"name": kot.name,
		"restaurant_order": kot.restaurant_order,
		"table_session": kot.table_session,
		"branch": kot.branch,
		"stock_location": kot.stock_location,
		"action": kot.action,
		"source_kot": kot.source_kot,
		"client_fire_id": kot.client_fire_id,
		"order_type": kot.order_type,
		"restaurant_table": kot.restaurant_table_snapshot,
		"table_name": kot.table_name_snapshot,
		"server": kot.server_snapshot,
		"fired_at": kot.fired_at,
		"fired_by": kot.fired_by,
		"status": kot.status,
		"note": kot.note,
		"items": [_serialize_kot_item(frappe.get_doc("Ledgix KOT Item", name)) for name in items],
	}


def _serialize_kot_item(item):
	return {
		"name": item.name,
		"kot": item.kot,
		"restaurant_order": item.restaurant_order,
		"restaurant_order_item": item.restaurant_order_item,
		"kitchen_station": item.kitchen_station,
		"action": item.action,
		"quantity": flt(item.quantity),
		"item": item.item,
		"item_name": item.item_name_snapshot,
		"seat_no": cint(item.seat_no),
		"course": item.course,
		"is_course_held": cint(item.is_course_held),
		"kitchen_note": item.kitchen_note,
		"modifier_summary": item.modifier_summary,
		"status": item.status,
		"queued_at": item.queued_at,
		"started_at": item.started_at,
		"ready_at": item.ready_at,
		"bumped_at": item.bumped_at,
		"recipe": item.recipe,
		"recipe_version": cint(item.recipe_version),
		"consumption_status": item.consumption_status,
	}


def _validate_fire_replay(existing_name, order_name, action):
	row = frappe.db.get_value(
		"Ledgix KOT",
		existing_name,
		["restaurant_order", "action"],
		as_dict=True,
	)
	if not row or row.restaurant_order != order_name or row.action != action:
		frappe.throw("Client Fire ID is already used by an unrelated kitchen operation.")


def _make_kot(order, *, action, client_fire_id, note=None, source_kot=None):
	if not str(client_fire_id or "").strip():
		frappe.throw("Client Fire ID is required for idempotent kitchen operations.")
	existing = frappe.db.get_value("Ledgix KOT", {"client_fire_id": client_fire_id}, "name")
	if existing:
		_validate_fire_replay(existing, order.name, action)
		return frappe.get_doc("Ledgix KOT", existing), False

	doc = frappe.get_doc({
		"doctype": "Ledgix KOT",
		"restaurant_order": order.name,
		"table_session": order.table_session,
		"branch": order.branch,
		"stock_location": order.stock_location,
		"action": action,
		"source_kot": source_kot,
		"client_fire_id": str(client_fire_id).strip(),
		"order_type": order.order_type,
		"restaurant_table_snapshot": order.restaurant_table,
		"table_name_snapshot": order.table_name_snapshot,
		"server_snapshot": order.server,
		"note": str(note or "").strip(),
	})
	doc.flags.from_kitchen_service = True
	doc.insert(ignore_permissions=True)
	return doc, True


def _normalize_fire_selections(order_name, selections=None, release_held=False):
	if selections:
		selected = []
		seen = set()
		for raw in _rows(selections):
			if isinstance(raw, str):
				item_name = raw
				quantity = None
			else:
				item_name = raw.get("order_item") or raw.get("restaurant_order_item") or raw.get("name")
				quantity = raw.get("quantity")
			if not item_name or item_name in seen:
				frappe.throw("Each kitchen fire selection must reference one unique Restaurant Order Item.")
			seen.add(item_name)
			item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
			if item.restaurant_order != order_name:
				frappe.throw(f"Restaurant Order Item {item.name} does not belong to order {order_name}.")
			remaining = flt(item.billable_quantity - item.fired_quantity, 6)
			qty = remaining if quantity is None else flt(quantity)
			if qty <= 0 or qty > remaining + 0.000001:
				frappe.throw(f"Invalid fire quantity for Restaurant Order Item {item.name}.")
			if cint(item.is_course_held) and not cint(release_held):
				frappe.throw(f"Restaurant Order Item {item.name} is course-held. Release it explicitly before firing.")
			selected.append((item, qty))
		return selected

	selected = []
	for name in frappe.get_all(
		"Ledgix Restaurant Order Item",
		filters={"restaurant_order": order_name, "is_voided": 0},
		pluck="name",
		order_by="creation asc",
		limit_page_length=0,
	):
		item = frappe.get_doc("Ledgix Restaurant Order Item", name)
		if cint(item.is_course_held) and not cint(release_held):
			continue
		remaining = flt(item.billable_quantity - item.fired_quantity, 6)
		if remaining > 0:
			selected.append((item, remaining))
	return selected


def _create_kot_item(kot, order_item, quantity, station, *, action="Add"):
	doc = frappe.get_doc({
		"doctype": "Ledgix KOT Item",
		"kot": kot.name,
		"restaurant_order": order_item.restaurant_order,
		"restaurant_order_item": order_item.name,
		"kitchen_station": station,
		"action": action,
		"quantity": quantity,
		"item": order_item.item,
		"item_name_snapshot": order_item.display_name_snapshot or order_item.item,
		"seat_no": order_item.seat_no,
		"course": order_item.course,
		"is_course_held": order_item.is_course_held,
		"kitchen_note": order_item.item_note,
		"modifier_summary": _modifier_summary(order_item),
		"recipe": order_item.recipe,
		"recipe_version": order_item.recipe_version,
		"consumption_status": "Pending" if action == "Add" else "Not Required",
	})
	doc.flags.from_kitchen_service = True
	doc.insert(ignore_permissions=True)
	return doc


def _post_locked_consumption(kot, kot_item, order_item, quantity):
	rows = frappe.get_all(
		"Ledgix Restaurant Order Consumption",
		filters={"restaurant_order_item": order_item.name},
		fields=["ingredient_item", "stock_uom", "quantity_per_unit", "cost_rate", "line_cost_per_unit"],
		order_by="creation asc",
		limit_page_length=0,
	)
	if not rows:
		kot_item.consumption_status = "Not Required"
		kot_item.flags.allow_consumption_state_update = True
		kot_item.save(ignore_permissions=True)
		return

	for row in rows:
		stock_quantity = flt(flt(row.quantity_per_unit) * flt(quantity), 6)
		if stock_quantity <= 0:
			continue
		consumption = frappe.get_doc({
			"doctype": "Ledgix KOT Consumption",
			"kot_item": kot_item.name,
			"restaurant_order_item": order_item.name,
			"branch": kot.branch,
			"stock_location": kot.stock_location,
			"ingredient_item": row.ingredient_item,
			"stock_uom": row.stock_uom,
			"stock_quantity": stock_quantity,
			"cost_rate": row.cost_rate,
			"line_cost": flt(flt(row.cost_rate) * stock_quantity, 4),
		})
		consumption.flags.from_kitchen_service = True
		consumption.insert(ignore_permissions=True)
		movement = _post_movement(
			item=row.ingredient_item,
			quantity=stock_quantity,
			movement_type="OUT",
			reference_doctype="Ledgix KOT Consumption",
			reference_name=consumption.name,
			source="Kitchen Consumption",
			branch=kot.branch,
			stock_location=kot.stock_location,
			rate=row.cost_rate,
			note=f"Kitchen fire {kot.name} / {order_item.name}",
		)
		consumption.status = "Posted"
		consumption.out_movement = movement
		consumption.posted_at = now_datetime()
		consumption.flags.allow_posting_state_update = True
		consumption.save(ignore_permissions=True)

	kot_item.consumption_status = "Posted"
	kot_item.consumption_posted_at = now_datetime()
	kot_item.flags.allow_consumption_state_update = True
	kot_item.save(ignore_permissions=True)


def _set_order_status(order, status):
	if order.status == status:
		return
	order.status = status
	order.flags.allow_status_transition = True
	order.save(ignore_permissions=True)


def _publish_kitchen_update(branch, *, station=None, order=None, kot=None, action=None):
	payload = {"branch": branch, "station": station, "restaurant_order": order, "kot": kot, "action": action}
	frappe.publish_realtime("ledgix_kds_update", payload)
	if order:
		frappe.publish_realtime("ledgix_restaurant_order_update", {"branch": branch, "restaurant_order": order, "action": action})


def fire_order_items(order_name, selections=None, *, client_fire_id, release_held=False, note=None):
	order = _active_order(order_name)
	existing = frappe.db.get_value("Ledgix KOT", {"client_fire_id": client_fire_id}, "name") if client_fire_id else None
	if existing:
		_validate_fire_replay(existing, order.name, "Add")
		return {"kot": get_kot_payload(existing), "order": get_order_payload(order.name), "idempotent_replay": True}

	selected = _normalize_fire_selections(order.name, selections=selections, release_held=release_held)
	if not selected:
		frappe.throw("No unfired Restaurant Order Item quantity is available for this kitchen fire.")

	kot, _ = _make_kot(order, action="Add", client_fire_id=client_fire_id, note=note)
	stations = set()
	for order_item, quantity in selected:
		station = resolve_kitchen_station(order.branch, order_item)
		stations.add(station)
		kot_item = _create_kot_item(kot, order_item, quantity, station, action="Add")
		_post_locked_consumption(kot, kot_item, order_item, quantity)
		order_item.fired_quantity = flt(order_item.fired_quantity + quantity, 6)
		order_item.kitchen_status = "Fired"
		if cint(release_held):
			order_item.is_course_held = 0
		order_item.flags.allow_operational_mutation = True
		order_item.save(ignore_permissions=True)

	_set_order_status(order, "In Kitchen")
	log_restaurant_operation(
		"Kitchen Fire",
		branch=order.branch,
		table_session=order.table_session,
		restaurant_order=order.name,
		reason=note,
		request_id=f"kitchen-fire:{client_fire_id}",
		metadata={"kot": kot.name, "stations": sorted(stations), "item_count": len(selected)},
	)
	for station in stations:
		_publish_kitchen_update(order.branch, station=station, order=order.name, kot=kot.name, action="Add")
	return {"kot": get_kot_payload(kot.name), "order": get_order_payload(order.name), "idempotent_replay": False}


def _refresh_kot_header(kot_name):
	kot = frappe.get_doc("Ledgix KOT", kot_name)
	statuses = frappe.get_all("Ledgix KOT Item", filters={"kot": kot.name}, pluck="status", limit_page_length=0)
	if not statuses:
		return
	if all(status in {"Bumped", "Voided", "Recalled"} for status in statuses):
		status = "Bumped" if any(row == "Bumped" for row in statuses) else "Voided"
	elif all(status in {"Ready", "Bumped", "Voided"} for status in statuses):
		status = "Ready"
	elif any(status == "Preparing" for status in statuses):
		status = "Preparing"
	else:
		status = "New"
	if kot.status != status:
		kot.status = status
		kot.flags.allow_kitchen_state_transition = True
		kot.save(ignore_permissions=True)


def _refresh_restaurant_item_kitchen_state(order_item_name):
	item = frappe.get_doc("Ledgix Restaurant Order Item", order_item_name)
	add_rows = frappe.get_all(
		"Ledgix KOT Item",
		filters={"restaurant_order_item": item.name, "action": "Add"},
		fields=["quantity", "status"],
		limit_page_length=0,
	)
	prepared = sum(flt(row.quantity) for row in add_rows if row.status in PRODUCTION_STATUSES)
	ready = sum(flt(row.quantity) for row in add_rows if row.status in {"Ready", "Bumped"})
	item.prepared_quantity = flt(min(prepared, item.fired_quantity), 6)
	item.ready_quantity = flt(min(ready, item.fired_quantity), 6)
	if cint(item.is_voided):
		item.kitchen_status = "Voided"
	elif item.ready_quantity >= flt(item.billable_quantity) - 0.000001 and flt(item.billable_quantity) > 0:
		item.kitchen_status = "Ready"
	elif item.prepared_quantity > 0:
		item.kitchen_status = "Preparing"
	elif item.fired_quantity > 0:
		item.kitchen_status = "Fired"
	else:
		item.kitchen_status = "Held" if cint(item.is_course_held) else "Not Sent"
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	return item


def _refresh_restaurant_order_kitchen_state(order_name):
	order = _active_order(order_name)
	items = [
		frappe.get_doc("Ledgix Restaurant Order Item", name)
		for name in frappe.get_all(
			"Ledgix Restaurant Order Item",
			filters={"restaurant_order": order.name, "is_voided": 0},
			pluck="name",
			limit_page_length=0,
		)
	]
	billable = [item for item in items if flt(item.billable_quantity) > 0]
	if billable and all(flt(item.ready_quantity) >= flt(item.billable_quantity) - 0.000001 for item in billable):
		status = "Ready"
	elif any(flt(item.ready_quantity) > 0 for item in billable):
		status = "Partially Ready"
	elif any(flt(item.fired_quantity) > 0 for item in billable):
		status = "In Kitchen"
	else:
		status = "Open"
	_set_order_status(order, status)
	return order


def set_kot_item_status(kot_item_name, status):
	kot_item = frappe.get_doc("Ledgix KOT Item", kot_item_name)
	kot = frappe.get_doc("Ledgix KOT", kot_item.kot)
	ensure_branch_access(kot.branch)
	status = str(status or "").strip()
	if status not in {"New", "Preparing", "Ready", "Bumped"}:
		frappe.throw("Unsupported KDS production state.")
	if kot_item.action != "Add":
		frappe.throw("Only Add KOT Items use the production-state workflow.")
	if kot_item.status == status:
		return get_kot_payload(kot.name)

	kot_item.status = status
	now = now_datetime()
	if status == "Preparing":
		kot_item.started_at = kot_item.started_at or now
	elif status == "Ready":
		kot_item.started_at = kot_item.started_at or now
		kot_item.ready_at = kot_item.ready_at or now
	elif status == "Bumped":
		kot_item.started_at = kot_item.started_at or now
		kot_item.ready_at = kot_item.ready_at or now
		kot_item.bumped_at = kot_item.bumped_at or now
	kot_item.state_changed_by = frappe.session.user
	kot_item.flags.allow_kitchen_state_transition = True
	kot_item.save(ignore_permissions=True)
	_refresh_kot_header(kot.name)
	_refresh_restaurant_item_kitchen_state(kot_item.restaurant_order_item)
	order = _refresh_restaurant_order_kitchen_state(kot.restaurant_order)
	log_restaurant_operation(
		"Kitchen State",
		branch=kot.branch,
		table_session=kot.table_session,
		restaurant_order=kot.restaurant_order,
		restaurant_order_item=kot_item.restaurant_order_item,
		metadata={"kot": kot.name, "kot_item": kot_item.name, "status": status},
	)
	_publish_kitchen_update(kot.branch, station=kot_item.kitchen_station, order=order.name, kot=kot.name, action=status)
	return get_kot_payload(kot.name)


def get_station_queue(*, branch, kitchen_station=None, include_ready=True):
	ensure_branch_access(branch)
	filters = {"status": ["in", ["New", "Preparing"] + (["Ready"] if cint(include_ready) else [])]}
	if kitchen_station:
		station_branch = frappe.db.get_value("Ledgix Kitchen Station", {"name": kitchen_station, "is_active": 1}, "branch")
		if station_branch != branch:
			frappe.throw("Kitchen Station must be active and belong to the selected Branch.")
		filters["kitchen_station"] = kitchen_station
	rows = frappe.get_all(
		"Ledgix KOT Item",
		filters=filters,
		fields=[
			"name", "kot", "restaurant_order", "restaurant_order_item", "kitchen_station", "action", "quantity",
			"item", "item_name_snapshot", "seat_no", "course", "is_course_held", "kitchen_note", "modifier_summary",
			"status", "queued_at", "started_at", "ready_at",
		],
		order_by="queued_at asc, creation asc",
		limit_page_length=0,
	)
	result = []
	for row in rows:
		kot = frappe.db.get_value(
			"Ledgix KOT",
			row.kot,
			["branch", "order_type", "table_name_snapshot", "server_snapshot", "fired_at"],
			as_dict=True,
		)
		if not kot or kot.branch != branch:
			continue
		result.append({**dict(row), "order_type": kot.order_type, "table_name": kot.table_name_snapshot, "server": kot.server_snapshot, "fired_at": kot.fired_at})
	return result


def void_kitchen_item(order_item_name, *, quantity=None, reason, client_fire_id):
	order_item = frappe.get_doc("Ledgix Restaurant Order Item", order_item_name)
	order = _active_order(order_item.restaurant_order)
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw("Kitchen void reason is required.")
	if not client_fire_id:
		frappe.throw("Client Fire ID is required for idempotent kitchen voids.")
	existing = frappe.db.get_value("Ledgix KOT", {"client_fire_id": client_fire_id}, "name")
	if existing:
		_validate_fire_replay(existing, order.name, "Void")
		return {"kot": get_kot_payload(existing), "order": get_order_payload(order.name), "idempotent_replay": True}

	remaining = flt(order_item.billable_quantity)
	void_qty = remaining if quantity is None else flt(quantity)
	if void_qty <= 0 or void_qty > remaining + 0.000001:
		frappe.throw("Kitchen void quantity must be positive and cannot exceed the remaining billable quantity.")
	fired_available = flt(order_item.fired_quantity - order_item.void_quantity, 6)
	if void_qty > fired_available + 0.000001:
		frappe.throw("Kitchen void quantity cannot exceed the fired, non-voided quantity.")

	kot, _ = _make_kot(order, action="Void", client_fire_id=client_fire_id, note=reason)
	station = resolve_kitchen_station(order.branch, order_item)
	void_item = _create_kot_item(kot, order_item, void_qty, station, action="Void")
	prepared = flt(order_item.prepared_quantity) > 0
	if prepared:
		void_item.status = "Voided"
		void_item.consumption_status = "Waste"
		void_item.flags.allow_kitchen_state_transition = True
		void_item.flags.allow_consumption_state_update = True
		void_item.save(ignore_permissions=True)
	else:
		consumptions = frappe.get_all(
			"Ledgix Restaurant Order Consumption",
			filters={"restaurant_order_item": order_item.name},
			fields=["ingredient_item", "stock_uom", "quantity_per_unit", "cost_rate"],
			limit_page_length=0,
		)
		for row in consumptions:
			stock_quantity = flt(flt(row.quantity_per_unit) * void_qty, 6)
			if stock_quantity <= 0:
				continue
			reversal = frappe.get_doc({
				"doctype": "Ledgix KOT Consumption",
				"kot_item": void_item.name,
				"restaurant_order_item": order_item.name,
				"branch": order.branch,
				"stock_location": order.stock_location,
				"ingredient_item": row.ingredient_item,
				"stock_uom": row.stock_uom,
				"stock_quantity": stock_quantity,
				"cost_rate": row.cost_rate,
				"line_cost": flt(flt(row.cost_rate) * stock_quantity, 4),
			})
			reversal.flags.from_kitchen_service = True
			reversal.insert(ignore_permissions=True)
			movement = _post_movement(
				item=row.ingredient_item,
				quantity=stock_quantity,
				movement_type="IN",
				reference_doctype="Ledgix KOT Consumption",
				reference_name=reversal.name,
				source="Kitchen Reversal",
				branch=order.branch,
				stock_location=order.stock_location,
				rate=row.cost_rate,
				note=f"Pre-preparation void {kot.name} / {order_item.name}: {reason}",
			)
			reversal.status = "Reversed"
			reversal.reversal_movement = movement
			reversal.reversed_at = now_datetime()
			reversal.flags.allow_posting_state_update = True
			reversal.save(ignore_permissions=True)
		void_item.status = "Voided"
		void_item.consumption_status = "Reversed" if consumptions else "Not Required"
		void_item.consumption_reversed_at = now_datetime() if consumptions else None
		void_item.flags.allow_kitchen_state_transition = True
		void_item.flags.allow_consumption_state_update = True
		void_item.save(ignore_permissions=True)

	order_item.void_quantity = flt(order_item.void_quantity + void_qty, 6)
	order_item.void_reason = reason
	order_item.voided_by = frappe.session.user
	order_item.voided_at = now_datetime()
	order_item.flags.allow_kitchen_void = True
	order_item.flags.allow_operational_mutation = True
	order_item.save(ignore_permissions=True)
	_recalculate_item_tax(order_item)
	order_item.flags.allow_operational_mutation = True
	order_item.save(ignore_permissions=True)
	_recalculate_order(order.name)
	_refresh_kot_header(kot.name)
	_refresh_restaurant_item_kitchen_state(order_item.name)
	_refresh_restaurant_order_kitchen_state(order.name)
	log_restaurant_operation(
		"Kitchen Void",
		branch=order.branch,
		table_session=order.table_session,
		restaurant_order=order.name,
		restaurant_order_item=order_item.name,
		reason=reason,
		request_id=f"kitchen-void:{client_fire_id}",
		metadata={"kot": kot.name, "quantity": void_qty, "consequence": "Waste" if prepared else "Stock Reversal"},
	)
	_publish_kitchen_update(order.branch, station=station, order=order.name, kot=kot.name, action="Void")
	return {"kot": get_kot_payload(kot.name), "order": get_order_payload(order.name), "idempotent_replay": False}


def recall_kot(source_kot_name, *, client_fire_id, reason):
	source = frappe.get_doc("Ledgix KOT", source_kot_name)
	order = _active_order(source.restaurant_order)
	ensure_branch_access(order.branch)
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw("Recall reason is required.")
	existing = frappe.db.get_value("Ledgix KOT", {"client_fire_id": client_fire_id}, "name") if client_fire_id else None
	if existing:
		_validate_fire_replay(existing, order.name, "Recall")
		return {"kot": get_kot_payload(existing), "order": get_order_payload(order.name), "idempotent_replay": True}

	kot, _ = _make_kot(order, action="Recall", client_fire_id=client_fire_id, note=reason, source_kot=source.name)
	stations = set()
	for source_item_name in frappe.get_all("Ledgix KOT Item", filters={"kot": source.name, "action": "Add"}, pluck="name", limit_page_length=0):
		source_item = frappe.get_doc("Ledgix KOT Item", source_item_name)
		if source_item.status == "Bumped":
			continue
		order_item = frappe.get_doc("Ledgix Restaurant Order Item", source_item.restaurant_order_item)
		recall = _create_kot_item(kot, order_item, source_item.quantity, source_item.kitchen_station, action="Recall")
		recall.status = "Recalled"
		recall.flags.allow_kitchen_state_transition = True
		recall.save(ignore_permissions=True)
		stations.add(source_item.kitchen_station)
	if not stations:
		frappe.throw("No active, unbumped kitchen lines are available to recall from this KOT.")
	kot.status = "Voided"
	kot.flags.allow_kitchen_state_transition = True
	kot.save(ignore_permissions=True)
	log_restaurant_operation(
		"Kitchen Recall",
		branch=order.branch,
		table_session=order.table_session,
		restaurant_order=order.name,
		reason=reason,
		request_id=f"kitchen-recall:{client_fire_id}",
		metadata={"source_kot": source.name, "recall_kot": kot.name},
	)
	for station in stations:
		_publish_kitchen_update(order.branch, station=station, order=order.name, kot=kot.name, action="Recall")
	return {"kot": get_kot_payload(kot.name), "order": get_order_payload(order.name), "idempotent_replay": False}
