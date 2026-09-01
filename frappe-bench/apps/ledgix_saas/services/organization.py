from __future__ import annotations

import frappe
from frappe import _


PRIVILEGED_ROLES = {"System Manager", "Ledgix Admin"}


def _profile_branch_fields_available():
	if not frappe.db.exists("DocType", "Ledgix User Profile"):
		return False
	meta = frappe.get_meta("Ledgix User Profile")
	return meta.has_field("default_branch") and meta.has_field("allowed_branches")


def _get_active_profile(user=None):
	user = user or frappe.session.user
	if not _profile_branch_fields_available():
		return None
	return frappe.db.get_value(
		"Ledgix User Profile",
		{"user": user, "is_active": 1},
		["name", "default_branch", "default_stock_location"],
		as_dict=True,
	)


def _active_branch(branch):
	if not branch:
		return None
	return frappe.db.get_value(
		"Ledgix Branch",
		{"name": branch, "is_active": 1},
		"name",
	)


def get_default_branch(user=None):
	user = user or frappe.session.user
	profile = _get_active_profile(user)
	if profile and _active_branch(profile.default_branch):
		return profile.default_branch

	return frappe.db.get_value(
		"Ledgix Branch",
		{"is_active": 1},
		"name",
		order_by="creation asc",
	)


def get_default_stock_location(branch=None, purpose=None, user=None):
	user = user or frappe.session.user
	branch = branch or get_default_branch(user)
	if not branch:
		return None

	profile = _get_active_profile(user)
	if profile and profile.default_stock_location:
		profile_location = frappe.db.get_value(
			"Ledgix Stock Location",
			{
				"name": profile.default_stock_location,
				"branch": branch,
				"is_active": 1,
			},
			"name",
		)
		if profile_location:
			return profile_location

	purpose_filters = {"branch": branch, "is_active": 1}
	if purpose == "receiving":
		purpose_filters["is_default_receiving"] = 1
	elif purpose == "consumption":
		purpose_filters["is_default_consumption"] = 1

	if purpose in {"receiving", "consumption"}:
		purpose_location = frappe.db.get_value(
			"Ledgix Stock Location",
			purpose_filters,
			"name",
			order_by="creation asc",
		)
		if purpose_location:
			return purpose_location

	configured = frappe.db.get_value("Ledgix Branch", branch, "default_stock_location")
	if configured and frappe.db.exists(
		"Ledgix Stock Location",
		{"name": configured, "branch": branch, "is_active": 1},
	):
		return configured

	return frappe.db.get_value(
		"Ledgix Stock Location",
		{"branch": branch, "is_active": 1},
		"name",
		order_by="creation asc",
	)


def get_allowed_branches(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if roles.intersection(PRIVILEGED_ROLES):
		return frappe.get_all(
			"Ledgix Branch",
			filters={"is_active": 1},
			pluck="name",
			limit_page_length=0,
		)

	if not _profile_branch_fields_available():
		fallback = get_default_branch(user)
		return [fallback] if fallback else []

	profile = _get_active_profile(user)
	if not profile:
		return []

	allowed = frappe.get_all(
		"Ledgix User Branch Access",
		filters={"parent": profile.name, "parenttype": "Ledgix User Profile"},
		pluck="branch",
		limit_page_length=0,
	)
	if profile.default_branch and profile.default_branch not in allowed:
		allowed.append(profile.default_branch)

	active = set(
		frappe.get_all(
			"Ledgix Branch",
			filters={"name": ["in", allowed], "is_active": 1},
			pluck="name",
			limit_page_length=0,
		)
	) if allowed else set()
	return [branch for branch in allowed if branch in active]


def ensure_branch_access(branch, user=None):
	if not branch:
		frappe.throw(_("Branch is required."))

	user = user or frappe.session.user
	if not _active_branch(branch):
		frappe.throw(_("Branch {0} is inactive or does not exist.").format(branch))
	if branch not in get_allowed_branches(user):
		frappe.throw(
			_("User {0} is not allowed to access branch {1}.").format(user, branch),
			frappe.PermissionError,
		)
	return branch


def resolve_branch_location(
	branch=None,
	stock_location=None,
	*,
	purpose=None,
	user=None,
	enforce_access=True,
	require_location=True,
):
	"""Resolve and validate one authoritative branch/location context.

	A supplied location is allowed to determine the branch, but a supplied branch
	can never be silently changed to match a conflicting location.
	"""
	user = user or frappe.session.user

	if stock_location:
		location = frappe.db.get_value(
			"Ledgix Stock Location",
			stock_location,
			["name", "branch", "is_active"],
			as_dict=True,
		)
		if not location or not int(location.is_active or 0):
			frappe.throw(_("Stock Location {0} is inactive or does not exist.").format(stock_location))
		if branch and location.branch != branch:
			frappe.throw(
				_("Stock Location {0} does not belong to Branch {1}.").format(stock_location, branch)
			)
		branch = branch or location.branch

	branch = branch or get_default_branch(user)
	if not branch:
		frappe.throw(_("No active restaurant branch is configured."))

	if enforce_access:
		ensure_branch_access(branch, user)
	elif not _active_branch(branch):
		frappe.throw(_("Branch {0} is inactive or does not exist.").format(branch))

	if not stock_location:
		stock_location = get_default_stock_location(branch, purpose=purpose, user=user)

	if require_location and not stock_location:
		frappe.throw(_("No active stock location is configured for Branch {0}.").format(branch))

	if stock_location:
		location_branch = frappe.db.get_value(
			"Ledgix Stock Location",
			{"name": stock_location, "is_active": 1},
			"branch",
		)
		if location_branch != branch:
			frappe.throw(
				_("Stock Location {0} does not belong to Branch {1}.").format(stock_location, branch)
			)

	return branch, stock_location
