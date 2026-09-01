from __future__ import annotations

import frappe
from frappe.utils import cint

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.kitchen import get_station_queue, set_kot_item_status
from ledgix_saas.services.kitchen_courses import get_expo_queue
from ledgix_saas.services.organization import ensure_branch_access, get_allowed_branches, get_default_branch


_ALLOWED_TRANSITIONS = {
	"New": {"Preparing", "Ready"},
	"Preparing": {"Ready"},
	"Ready": {"Bumped"},
	"Bumped": set(),
}


def _resolve_branch(branch=None):
	allowed = get_allowed_branches()
	if not allowed:
		frappe.throw("No active restaurant branch is available for this user.", frappe.PermissionError)
	branch = branch or get_default_branch()
	if branch not in allowed:
		branch = allowed[0]
	return ensure_branch_access(branch)


def _branch_options(allowed):
	rows = frappe.get_all(
		"Ledgix Branch",
		filters={"name": ["in", allowed], "is_active": 1},
		fields=["name", "branch_code", "branch_name", "timezone"],
		order_by="branch_name asc",
		limit_page_length=0,
	)
	return [dict(row) for row in rows]


def _station_options(branch):
	return [
		dict(row)
		for row in frappe.get_all(
			"Ledgix Kitchen Station",
			filters={"branch": branch, "is_active": 1},
			fields=[
				"name",
				"station_code",
				"station_name",
				"station_type",
				"display_priority",
				"target_prep_minutes",
				"show_course",
				"show_seat",
				"is_default_station",
			],
			order_by="display_priority asc, station_name asc",
			limit_page_length=0,
		)
	]


def _resolve_station(stations, station=None):
	if not stations:
		return None
	by_name = {row["name"]: row for row in stations}
	if station and station in by_name:
		return station
	for row in stations:
		if row.get("station_type") != "Expo":
			return row["name"]
	return stations[0]["name"]


@frappe.whitelist()
def get_kds_boot(branch=None, station=None, view="Station", include_ready=1):
	"""Return one server-authoritative KDS payload for station or Expo mode."""
	require_ledgix_cashier_or_above()
	allowed = get_allowed_branches()
	branch = _resolve_branch(branch)
	stations = _station_options(branch)
	view = str(view or "Station").strip().title()
	if view not in {"Station", "Expo"}:
		frappe.throw("KDS view must be Station or Expo.")
	station = _resolve_station(stations, station)
	include_ready = cint(include_ready)

	queue = []
	expo = []
	if view == "Expo":
		expo = get_expo_queue(branch, include_ready=include_ready)
	else:
		queue = get_station_queue(
			branch=branch,
			kitchen_station=station,
			include_ready=include_ready,
		) if station else []

	return {
		"branch": branch,
		"branches": _branch_options(allowed),
		"stations": stations,
		"station": station,
		"view": view,
		"include_ready": bool(include_ready),
		"queue": queue,
		"expo": expo,
		"server_time": frappe.utils.now_datetime(),
	}


@frappe.whitelist()
def transition_item(kot_item, status):
	"""Guard the public KDS state machine before delegating to kitchen service."""
	require_ledgix_cashier_or_above()
	row = frappe.db.get_value(
		"Ledgix KOT Item",
		kot_item,
		["name", "status", "action", "kitchen_station"],
		as_dict=True,
	)
	if not row:
		frappe.throw("KOT Item was not found.")
	if row.action != "Add":
		frappe.throw("Only Add KOT Items use the production-state workflow.")
	status = str(status or "").strip()
	if status == row.status:
		return set_kot_item_status(kot_item, status)
	allowed = _ALLOWED_TRANSITIONS.get(row.status, set())
	if status not in allowed:
		frappe.throw(f"KDS state cannot move from {row.status} to {status}.")
	return set_kot_item_status(kot_item, status)
