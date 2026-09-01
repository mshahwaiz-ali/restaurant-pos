from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from ledgix_saas.services.menu import build_menu_catalog, normalize_channel, resolve_branch_menu
from ledgix_saas.services.organization import get_allowed_branches, resolve_branch_location


ACTIVE_SESSION_STATUSES = ("Open", "Closing")
ACTIVE_ORDER_STATUSES = ("Draft", "Open", "In Kitchen", "Partially Ready", "Ready", "Served")


def _open_shift(branch):
	filters = {"status": "Open", "docstatus": 0}
	meta = frappe.get_meta("Ledgix POS Shift")
	if meta.has_field("opened_by"):
		filters["opened_by"] = frappe.session.user
	if meta.has_field("branch"):
		filters["branch"] = branch
	return frappe.db.get_value("Ledgix POS Shift", filters, "name", order_by="creation desc")


def _branch_options():
	allowed = get_allowed_branches()
	if not allowed:
		return []
	rows = frappe.get_all(
		"Ledgix Branch",
		filters={"name": ["in", allowed], "is_active": 1},
		fields=["name", "branch_code", "branch_name", "timezone", "currency"],
		order_by="branch_name asc",
		limit_page_length=0,
	)
	return [dict(row) for row in rows]


def get_table_map(branch):
	branch, _ = resolve_branch_location(branch, None, purpose="consumption")
	floors = frappe.get_all(
		"Ledgix Floor",
		filters={"branch": branch, "is_active": 1},
		fields=["name", "floor_code", "floor_name", "sort_order"],
		order_by="sort_order asc, floor_name asc",
		limit_page_length=0,
	)
	tables = frappe.get_all(
		"Ledgix Restaurant Table",
		filters={"branch": branch, "is_active": 1},
		fields=[
			"name", "floor", "table_code", "table_name", "capacity", "shape", "sort_order",
			"position_x", "position_y", "display_width", "display_height",
		],
		order_by="floor asc, sort_order asc, table_name asc",
		limit_page_length=0,
	)
	table_names = [row.name for row in tables]
	sessions = frappe.get_all(
		"Ledgix Table Session",
		filters={"restaurant_table": ["in", table_names], "status": ["in", list(ACTIVE_SESSION_STATUSES)]},
		fields=["name", "restaurant_table", "status", "covers", "server", "customer", "guest_name", "opened_at"],
		order_by="opened_at desc",
		limit_page_length=0,
	) if table_names else []
	session_by_table = {}
	for session in sessions:
		session_by_table.setdefault(session.restaurant_table, session)

	session_names = [row.name for row in sessions]
	orders = frappe.get_all(
		"Ledgix Restaurant Order",
		filters={"table_session": ["in", session_names], "status": ["in", list(ACTIVE_ORDER_STATUSES)]},
		fields=["name", "table_session", "status", "server", "covers", "grand_total", "opened_at", "split_from_order"],
		order_by="opened_at asc",
		limit_page_length=0,
	) if session_names else []
	orders_by_session = {}
	for order in orders:
		orders_by_session.setdefault(order.table_session, []).append(order)

	floor_payload = []
	for floor in floors:
		floor_tables = []
		for table in tables:
			if table.floor != floor.name:
				continue
			session = session_by_table.get(table.name)
			check_rows = orders_by_session.get(session.name, []) if session else []
			state = "Available"
			if session:
				state = "Closing" if session.status == "Closing" else "Occupied"
				if check_rows and all(row.status == "Ready" for row in check_rows):
					state = "Ready"
			floor_tables.append({
				**dict(table),
				"state": state,
				"table_session": session.name if session else None,
				"session_status": session.status if session else None,
				"covers": cint(session.covers) if session else 0,
				"server": session.server if session else None,
				"guest_name": session.guest_name if session else None,
				"opened_at": session.opened_at if session else None,
				"open_checks": len(check_rows),
				"session_total": flt(sum(flt(row.grand_total) for row in check_rows), 2),
				"checks": [dict(row) for row in check_rows],
			})
		floor_payload.append({**dict(floor), "tables": floor_tables})
	return {"branch": branch, "floors": floor_payload}


def get_open_checks(branch, *, order_type=None):
	branch, _ = resolve_branch_location(branch, None, purpose="consumption")
	filters = {"branch": branch, "status": ["in", list(ACTIVE_ORDER_STATUSES)]}
	if order_type:
		filters["order_type"] = normalize_channel(order_type)
	rows = frappe.get_all(
		"Ledgix Restaurant Order",
		filters=filters,
		fields=[
			"name", "order_type", "status", "table_session", "restaurant_table", "table_name_snapshot",
			"server", "cashier", "covers", "customer", "pickup_name", "contact_phone", "promised_at",
			"subtotal", "modifier_total", "discount_amount", "service_charge", "tip_amount", "tax_amount", "grand_total",
			"opened_at", "split_from_order",
		],
		order_by="opened_at desc",
		limit_page_length=0,
	)
	return [dict(row) for row in rows]


def get_restaurant_pos_boot(branch=None, channel="Dine In", menu=None, customer=None):
	channel = normalize_channel(channel)
	branch, stock_location = resolve_branch_location(branch, None, purpose="consumption")
	resolved = resolve_branch_menu(branch=branch, channel=channel, menu=menu, customer=customer)
	catalog = build_menu_catalog(
		branch=branch,
		stock_location=stock_location,
		channel=channel,
		menu=resolved["menu"].name,
		customer=customer,
	)
	return {
		"product": "Ledgix Restaurant",
		"branch": branch,
		"stock_location": stock_location,
		"branches": _branch_options(),
		"channel": channel,
		"menu": resolved["menu"].name,
		"menu_name": resolved["menu"].menu_name,
		"price_list": resolved["price_list"],
		"local_datetime": str(resolved["local_datetime"]),
		"active_shift": _open_shift(branch),
		"table_map": get_table_map(branch) if channel == "Dine In" else {"branch": branch, "floors": []},
		"open_checks": get_open_checks(branch, order_type=channel),
		"catalog": catalog,
	}
