from __future__ import annotations

import frappe
from frappe.utils import get_datetime

from ledgix_saas.api.security import (
	require_ledgix_cashier_or_above,
	require_ledgix_manager_or_above,
)
from ledgix_saas.services.menu import (
	build_menu_catalog,
	get_effective_item_availability,
	normalize_channel,
)
from ledgix_saas.services.organization import ensure_branch_access, resolve_branch_location


@frappe.whitelist()
def get_restaurant_menu(
	branch=None,
	stock_location=None,
	channel="Dine In",
	menu=None,
	at_datetime=None,
	customer=None,
):
	"""Return the authoritative menu catalog for one branch/daypart/channel."""
	require_ledgix_cashier_or_above()
	return build_menu_catalog(
		branch=branch,
		stock_location=stock_location,
		channel=channel,
		menu=menu,
		at_datetime=at_datetime,
		customer=customer,
	)


@frappe.whitelist()
def get_branch_menu_options(branch=None, channel="Dine In", at_datetime=None):
	"""Return active menu choices without exposing inactive/unassigned menus."""
	require_ledgix_cashier_or_above()
	channel = normalize_channel(channel)
	branch, _stock_location = resolve_branch_location(branch, None, purpose="consumption")

	from ledgix_saas.services.menu import branch_local_datetime, menu_is_active

	local_dt = branch_local_datetime(branch, at_datetime)
	assignments = frappe.get_all(
		"Ledgix Branch Menu",
		filters={"branch": branch, "is_active": 1},
		fields=["name", "menu", "price_list_override", "priority"],
		order_by="priority asc, creation asc",
		limit_page_length=0,
	)
	options = []
	for assignment in assignments:
		menu_doc = frappe.get_doc("Ledgix Menu", assignment.menu)
		if not menu_is_active(menu_doc, channel, local_dt):
			continue
		options.append({
			"assignment": assignment.name,
			"menu": menu_doc.name,
			"menu_code": menu_doc.menu_code,
			"menu_name": menu_doc.menu_name,
			"priority": assignment.priority,
			"price_list": assignment.price_list_override or menu_doc.default_price_list,
		})
	return {
		"branch": branch,
		"channel": channel,
		"local_datetime": str(local_dt),
		"menus": options,
	}


@frappe.whitelist()
def set_item_availability(
	branch,
	item,
	status="86d",
	reason=None,
	auto_restore_at=None,
):
	"""Set or clear the canonical branch-level 86 state for an item."""
	require_ledgix_manager_or_above()
	branch = ensure_branch_access(branch)
	if not frappe.db.exists("Ledgix Branch", {"name": branch, "is_active": 1}):
		frappe.throw("Branch must be active.")
	if not frappe.db.exists("Ledgix Item", {"name": item, "active": 1}):
		frappe.throw("Item must be active.")

	status = str(status or "Available").strip()
	if status not in {"Available", "86d"}:
		frappe.throw("Availability Status must be Available or 86d.")
	if status == "86d" and not str(reason or "").strip():
		frappe.throw("Reason is required when an item is 86d.")

	key = f"{branch}::{item}"
	if frappe.db.exists("Ledgix Item Availability", key):
		doc = frappe.get_doc("Ledgix Item Availability", key)
	else:
		doc = frappe.new_doc("Ledgix Item Availability")
		doc.branch = branch
		doc.item = item

	doc.status = status
	doc.reason = str(reason or "").strip()
	doc.auto_restore_at = get_datetime(auto_restore_at) if auto_restore_at else None
	doc.save(ignore_permissions=True)

	return {
		"branch": branch,
		"item": item,
		**get_effective_item_availability(branch, item),
	}


@frappe.whitelist()
def get_item_availability(branch, item, at_datetime=None):
	require_ledgix_cashier_or_above()
	branch = ensure_branch_access(branch)
	return {
		"branch": branch,
		"item": item,
		**get_effective_item_availability(branch, item, at_datetime),
	}
