from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime, time_diff_in_seconds

from ledgix_saas.services.kitchen import fire_order_items, get_station_queue
from ledgix_saas.services.organization import ensure_branch_access


def fire_course(order_name, course, *, client_fire_id, note=None):
	course = str(course or "").strip()
	if not course:
		frappe.throw("Course is required.")
	rows = frappe.get_all(
		"Ledgix Restaurant Order Item",
		filters={
			"restaurant_order": order_name,
			"course": course,
			"is_course_held": 1,
			"is_voided": 0,
		},
		fields=["name", "billable_quantity", "fired_quantity"],
		order_by="creation asc",
		limit_page_length=0,
	)
	selections = []
	for row in rows:
		remaining = flt(row.billable_quantity - row.fired_quantity, 6)
		if remaining > 0:
			selections.append({"order_item": row.name, "quantity": remaining})
	if not selections:
		frappe.throw(f"No held, unfired items remain in course {course}.")
	return fire_order_items(
		order_name,
		selections=selections,
		client_fire_id=client_fire_id,
		release_held=True,
		note=note or f"Fire course {course}",
	)


def get_expo_queue(branch, *, include_ready=True):
	ensure_branch_access(branch)
	rows = get_station_queue(branch=branch, include_ready=include_ready)
	now = now_datetime()
	orders = {}
	for row in rows:
		queued_at = row.get("queued_at")
		row["elapsed_seconds"] = max(int(time_diff_in_seconds(now, queued_at)), 0) if queued_at else 0
		order = orders.setdefault(
			row["restaurant_order"],
			{
				"restaurant_order": row["restaurant_order"],
				"order_type": row.get("order_type"),
				"table_name": row.get("table_name"),
				"server": row.get("server"),
				"oldest_queued_at": queued_at,
				"items": [],
			},
		)
		if queued_at and (not order["oldest_queued_at"] or queued_at < order["oldest_queued_at"]):
			order["oldest_queued_at"] = queued_at
		order["items"].append(row)

	result = list(orders.values())
	for order in result:
		oldest = order.get("oldest_queued_at")
		order["elapsed_seconds"] = max(int(time_diff_in_seconds(now, oldest)), 0) if oldest else 0
		order["ready_count"] = sum(1 for item in order["items"] if item.get("status") == "Ready")
		order["active_count"] = len(order["items"])
	result.sort(key=lambda row: row.get("oldest_queued_at") or now)
	return result
