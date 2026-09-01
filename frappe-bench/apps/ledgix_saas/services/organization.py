from __future__ import annotations

import frappe
from frappe import _


PRIVILEGED_ROLES = {"System Manager", "Ledgix Admin"}


def get_default_branch(user=None):
	user = user or frappe.session.user
	profile = frappe.db.get_value(
		"Ledgix User Profile",
		{"user": user, "is_active": 1},
		["name", "default_branch"],
		as_dict=True,
	)
	if profile and profile.default_branch:
		return profile.default_branch

	return frappe.db.get_value(
		"Ledgix Branch",
		{"is_active": 1},
		"name",
		order_by="creation asc",
	)


def get_default_stock_location(branch=None, purpose=None):
	branch = branch or get_default_branch()
	if not branch:
		return None

	configured = frappe.db.get_value("Ledgix Branch", branch, "default_stock_location")
	if configured and frappe.db.exists(
		"Ledgix Stock Location",
		{"name": configured, "branch": branch, "is_active": 1},
	):
		return configured

	filters = {"branch": branch, "is_active": 1}
	if purpose == "receiving":
		filters["is_default_receiving"] = 1
	elif purpose == "consumption":
		filters["is_default_consumption"] = 1

	return frappe.db.get_value(
		"Ledgix Stock Location",
		filters,
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

	profile = frappe.db.get_value(
		"Ledgix User Profile",
		{"user": user, "is_active": 1},
		["name", "default_branch"],
		as_dict=True,
	)
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
	return allowed


def ensure_branch_access(branch, user=None):
	if not branch:
		frappe.throw(_("Branch is required."))

	user = user or frappe.session.user
	if branch not in get_allowed_branches(user):
		frappe.throw(
			_("User {0} is not allowed to access branch {1}.").format(user, branch),
			frappe.PermissionError,
		)
	return branch
