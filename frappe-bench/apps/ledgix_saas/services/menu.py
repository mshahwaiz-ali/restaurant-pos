from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from ledgix_saas.services.organization import resolve_branch_location
from ledgix_saas.services.pricing import resolve_item_price, resolve_price_list
from ledgix_saas.services.stock import get_location_stock


CHANNEL_FIELDS = {
	"Dine In": "available_dine_in",
	"Takeaway": "available_takeaway",
	"Delivery": "available_delivery",
}

CHANNEL_ALIASES = {
	"dine in": "Dine In",
	"dine-in": "Dine In",
	"dinein": "Dine In",
	"takeaway": "Takeaway",
	"take away": "Takeaway",
	"take-away": "Takeaway",
	"pickup": "Takeaway",
	"delivery": "Delivery",
}

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def normalize_channel(channel):
	value = str(channel or "Dine In").strip()
	normalized = CHANNEL_ALIASES.get(value.lower(), value)
	if normalized not in CHANNEL_FIELDS:
		frappe.throw("Order Channel must be Dine In, Takeaway or Delivery.")
	return normalized


def branch_local_datetime(branch, at_datetime=None):
	if at_datetime:
		return get_datetime(at_datetime)

	timezone = frappe.db.get_value("Ledgix Branch", branch, "timezone") or frappe.db.get_default("time_zone") or "UTC"
	try:
		return datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)
	except Exception:
		return now_datetime()


def _time_seconds(value):
	if value is None:
		return None
	if isinstance(value, timedelta):
		return int(value.total_seconds())
	if isinstance(value, time):
		return value.hour * 3600 + value.minute * 60 + value.second
	text = str(value)
	parts = text.split(":")
	try:
		hour = int(parts[0])
		minute = int(parts[1]) if len(parts) > 1 else 0
		second = int(float(parts[2])) if len(parts) > 2 else 0
		return hour * 3600 + minute * 60 + second
	except (TypeError, ValueError):
		return None


def _schedule_matches(menu, local_dt):
	schedules = list(menu.get("schedules") or [])
	if not schedules:
		return True

	current_day = DAY_NAMES[local_dt.weekday()]
	previous_day = DAY_NAMES[(local_dt.weekday() - 1) % 7]
	current_seconds = local_dt.hour * 3600 + local_dt.minute * 60 + local_dt.second

	for row in schedules:
		start = _time_seconds(row.start_time)
		end = _time_seconds(row.end_time)
		if start is None or end is None or start == end:
			continue

		if start < end:
			if row.day_of_week == current_day and start <= current_seconds < end:
				return True
		else:
			# Overnight window: e.g. Friday 18:00 → Saturday 02:00.
			if row.day_of_week == current_day and current_seconds >= start:
				return True
			if row.day_of_week == previous_day and current_seconds < end:
				return True
	return False


def menu_is_active(menu, channel, local_dt):
	channel = normalize_channel(channel)
	if not cint(menu.is_active):
		return False
	if not cint(menu.get(CHANNEL_FIELDS[channel])):
		return False
	current_date = getdate(local_dt)
	if menu.valid_from and current_date < getdate(menu.valid_from):
		return False
	if menu.valid_to and current_date > getdate(menu.valid_to):
		return False
	return _schedule_matches(menu, local_dt)


def resolve_branch_menu(branch=None, channel="Dine In", menu=None, at_datetime=None, customer=None):
	channel = normalize_channel(channel)
	branch, stock_location = resolve_branch_location(branch, None, purpose="consumption")
	local_dt = branch_local_datetime(branch, at_datetime)

	assignment_filters = {"branch": branch, "is_active": 1}
	if menu:
		assignment_filters["menu"] = menu
	assignments = frappe.get_all(
		"Ledgix Branch Menu",
		filters=assignment_filters,
		fields=["name", "menu", "price_list_override", "priority"],
		order_by="priority asc, creation asc",
		limit_page_length=0,
	)
	if not assignments:
		frappe.throw(f"No active Menu is assigned to Branch {branch}.")

	for assignment in assignments:
		menu_doc = frappe.get_doc("Ledgix Menu", assignment.menu)
		if not menu_is_active(menu_doc, channel, local_dt):
			continue
		price_list = (
			assignment.price_list_override
			or menu_doc.default_price_list
			or frappe.db.get_value("Ledgix Branch", branch, "default_price_list")
			or resolve_price_list(customer, None, "Retail")
		)
		if price_list and not frappe.db.exists("Ledgix Price List", {"name": price_list, "enabled": 1}):
			frappe.throw(f"Resolved Price List {price_list} is disabled or missing.")
		return {
			"branch": branch,
			"stock_location": stock_location,
			"channel": channel,
			"local_datetime": local_dt,
			"assignment": assignment,
			"menu": menu_doc,
			"price_list": price_list,
		}

	requested = f" {menu}" if menu else ""
	frappe.throw(f"No active{requested} Menu matches {channel} at the current branch daypart.")


def get_effective_item_availability(branch, item, at_datetime=None):
	local_dt = branch_local_datetime(branch, at_datetime)
	row = frappe.db.get_value(
		"Ledgix Item Availability",
		{"branch": branch, "item": item},
		["name", "status", "reason", "auto_restore_at", "updated_by", "updated_at"],
		as_dict=True,
	)
	if not row:
		return {
			"status": "Available",
			"available": True,
			"reason": "",
			"auto_restore_at": None,
			"record": None,
		}

	if row.status == "86d" and row.auto_restore_at and get_datetime(row.auto_restore_at) <= local_dt:
		return {
			"status": "Available",
			"available": True,
			"reason": "",
			"auto_restore_at": row.auto_restore_at,
			"record": row.name,
			"auto_restore_due": True,
		}

	return {
		"status": row.status or "Available",
		"available": row.status != "86d",
		"reason": row.reason or "",
		"auto_restore_at": row.auto_restore_at,
		"record": row.name,
	}


def _effective_group_rules(link, group):
	minimum = cint(group.min_selection)
	maximum = cint(group.max_selection)
	if cint(link.min_selection_override) >= 0:
		minimum = cint(link.min_selection_override)
	if cint(link.max_selection_override) >= 0:
		maximum = cint(link.max_selection_override)
	if link.required_override == "Required":
		minimum = max(minimum, 1)
	elif link.required_override == "Optional":
		minimum = 0
	return minimum, maximum


def _modifier_payload(menu_item_names):
	if not menu_item_names:
		return {}
	links = frappe.get_all(
		"Ledgix Menu Item Modifier Group",
		filters={
			"parent": ["in", menu_item_names],
			"parenttype": "Ledgix Menu Item",
			"parentfield": "modifier_groups",
		},
		fields=[
			"parent",
			"modifier_group",
			"required_override",
			"min_selection_override",
			"max_selection_override",
			"sort_order",
			"idx",
		],
		order_by="parent asc, sort_order asc, idx asc",
		limit_page_length=0,
	)
	group_names = list({row.modifier_group for row in links if row.modifier_group})
	if not group_names:
		return {}
	groups = {
		row.name: row
		for row in frappe.get_all(
			"Ledgix Modifier Group",
			filters={"name": ["in", group_names], "is_active": 1},
			fields=["name", "modifier_group_name", "selection_type", "min_selection", "max_selection"],
			limit_page_length=0,
		)
	}
	options_by_group = {name: [] for name in groups}
	for option in frappe.get_all(
		"Ledgix Modifier Option",
		filters={"modifier_group": ["in", list(groups)], "is_active": 1},
		fields=[
			"name",
			"modifier_group",
			"option_name",
			"kitchen_label",
			"price_delta",
			"stock_effect",
			"linked_item",
			"stock_quantity",
			"uom",
			"sort_order",
		],
		order_by="modifier_group asc, sort_order asc, option_name asc",
		limit_page_length=0,
	):
		options_by_group.setdefault(option.modifier_group, []).append(option)

	payload = {}
	for link in links:
		group = groups.get(link.modifier_group)
		if not group:
			continue
		minimum, maximum = _effective_group_rules(link, group)
		payload.setdefault(link.parent, []).append({
			"modifier_group": group.name,
			"name": group.modifier_group_name,
			"selection_type": group.selection_type,
			"min_selection": minimum,
			"max_selection": maximum,
			"required": minimum > 0,
			"sort_order": cint(link.sort_order),
			"options": [dict(option) for option in options_by_group.get(group.name, [])],
		})
	return payload


def build_menu_catalog(branch=None, stock_location=None, channel="Dine In", menu=None, at_datetime=None, customer=None):
	resolved = resolve_branch_menu(branch, channel, menu, at_datetime, customer)
	branch = resolved["branch"]
	if stock_location:
		branch, stock_location = resolve_branch_location(branch, stock_location, purpose="consumption")
	else:
		stock_location = resolved["stock_location"]
	menu_doc = resolved["menu"]
	channel = resolved["channel"]
	price_list = resolved["price_list"]

	sections = frappe.get_all(
		"Ledgix Menu Section",
		filters={"menu": menu_doc.name, "is_active": 1},
		fields=["name", "section_code", "section_name", "sort_order"],
		order_by="sort_order asc, section_name asc",
		limit_page_length=0,
	)
	section_names = [row.name for row in sections]
	if not section_names:
		return _catalog_response(resolved, stock_location, sections, [], price_list)

	item_filters = {
		"menu": menu_doc.name,
		"menu_section": ["in", section_names],
		"is_active": 1,
		CHANNEL_FIELDS[channel]: 1,
	}
	menu_items = frappe.get_all(
		"Ledgix Menu Item",
		filters=item_filters,
		fields=[
			"name",
			"menu_section",
			"item",
			"display_name",
			"display_image",
			"display_description",
			"sort_order",
		],
		order_by="menu_section asc, sort_order asc, display_name asc",
		limit_page_length=0,
	)
	modifier_map = _modifier_payload([row.name for row in menu_items])
	item_names = list({row.item for row in menu_items if row.item})
	item_meta = {
		row.name: row
		for row in frappe.get_all(
			"Ledgix Item",
			filters={"name": ["in", item_names], "active": 1, "is_sellable": 1},
			fields=[
				"name",
				"item_code",
				"item_name",
				"category",
				"image",
				"restaurant_item_type",
				"track_inventory",
				"stock_uom",
				"current_stock",
			],
			limit_page_length=0,
		)
	}

	catalog_items = []
	for menu_item in menu_items:
		item = item_meta.get(menu_item.item)
		if not item:
			continue
		availability = get_effective_item_availability(branch, item.name, resolved["local_datetime"])
		location_stock = get_location_stock(item.name, stock_location) if cint(item.track_inventory) else None
		price = resolve_item_price(
			item.name,
			customer=customer,
			price_list=price_list,
			sale_channel="Retail",
			transaction_date=getdate(resolved["local_datetime"]),
		)
		catalog_items.append({
			"menu_item": menu_item.name,
			"section": menu_item.menu_section,
			"item": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"display_name": menu_item.display_name or item.item_name,
			"display_image": menu_item.display_image or item.image,
			"description": menu_item.display_description or "",
			"restaurant_item_type": item.restaurant_item_type,
			"track_inventory": cint(item.track_inventory),
			"stock_uom": item.stock_uom,
			"location_stock": location_stock,
			"aggregate_stock": flt(item.current_stock),
			"stock_warning": "Out of Stock" if cint(item.track_inventory) and flt(location_stock) <= 0 else "",
			"availability_status": availability["status"],
			"available": bool(availability["available"]),
			"unavailable_reason": availability["reason"],
			"auto_restore_at": availability.get("auto_restore_at"),
			"rate": flt(price.get("rate"), 2),
			"list_rate": flt(price.get("list_rate"), 2),
			"price_list": price.get("price_list"),
			"item_price_reference": price.get("item_price_reference"),
			"sort_order": cint(menu_item.sort_order),
			"modifier_groups": modifier_map.get(menu_item.name, []),
		})

	return _catalog_response(resolved, stock_location, sections, catalog_items, price_list)


def _catalog_response(resolved, stock_location, sections, items, price_list):
	section_payload = []
	items_by_section = {}
	for item in items:
		items_by_section.setdefault(item["section"], []).append(item)
	for section in sections:
		section_payload.append({
			"section": section.name,
			"code": section.section_code,
			"name": section.section_name,
			"sort_order": cint(section.sort_order),
			"items": items_by_section.get(section.name, []),
		})
	menu_doc = resolved["menu"]
	return {
		"branch": resolved["branch"],
		"stock_location": stock_location,
		"channel": resolved["channel"],
		"local_datetime": str(resolved["local_datetime"]),
		"menu": {
			"name": menu_doc.name,
			"code": menu_doc.menu_code,
			"label": menu_doc.menu_name,
			"assignment": resolved["assignment"].name,
			"price_list": price_list,
		},
		"sections": section_payload,
		"items": items,
	}
