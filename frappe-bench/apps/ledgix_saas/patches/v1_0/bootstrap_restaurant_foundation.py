from __future__ import annotations

import frappe
from frappe.utils import flt


DEFAULT_BRAND_CODE = "DEFAULT"
DEFAULT_BRANCH_CODE = "MAIN"
DEFAULT_LOCATION_CODE = "MAIN"


def execute():
	"""Create the single-restaurant compatibility foundation.

	This patch is intentionally additive. Existing retail transactions keep their
	current behavior; the branch/location-aware posting engine is introduced in the
	next migration after these master records are proven healthy.
	"""
	brand = _ensure_default_brand()
	branch = _ensure_default_branch(brand)
	location = _ensure_default_location(branch)
	_ensure_branch_default_location(branch, location)
	_seed_stock_balances(branch, location)


def _ensure_default_brand():
	if frappe.db.exists("Ledgix Restaurant Brand", DEFAULT_BRAND_CODE):
		return DEFAULT_BRAND_CODE

	doc = frappe.new_doc("Ledgix Restaurant Brand")
	doc.brand_code = DEFAULT_BRAND_CODE
	doc.brand_name = "Default Restaurant"
	doc.is_active = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_default_branch(brand):
	if frappe.db.exists("Ledgix Branch", DEFAULT_BRANCH_CODE):
		return DEFAULT_BRANCH_CODE

	doc = frappe.new_doc("Ledgix Branch")
	doc.restaurant_brand = brand
	doc.branch_code = DEFAULT_BRANCH_CODE
	doc.branch_name = "Main Branch"
	doc.is_active = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_default_location(branch):
	existing = frappe.db.get_value(
		"Ledgix Stock Location",
		{"branch": branch, "location_code": DEFAULT_LOCATION_CODE},
		"name",
	)
	if existing:
		return existing

	doc = frappe.new_doc("Ledgix Stock Location")
	doc.branch = branch
	doc.location_code = DEFAULT_LOCATION_CODE
	doc.location_name = "Main Store"
	doc.location_type = "Store"
	doc.is_active = 1
	doc.is_default_receiving = 1
	doc.is_default_consumption = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_branch_default_location(branch, location):
	if frappe.db.get_value("Ledgix Branch", branch, "default_stock_location"):
		return
	frappe.db.set_value(
		"Ledgix Branch",
		branch,
		"default_stock_location",
		location,
		update_modified=False,
	)


def _seed_stock_balances(branch, location):
	"""Snapshot existing single-location Item balances into the new balance table.

	The movement ledger is still authoritative history. This seed only gives the
	location-aware engine a deterministic starting balance for the compatibility
	branch before movement posting is switched over.
	"""
	for item in frappe.get_all(
		"Ledgix Item",
		fields=["name", "current_stock", "cost_price"],
		limit_page_length=0,
	):
		if frappe.db.exists(
			"Ledgix Stock Balance",
			{"stock_location": location, "item": item.name},
		):
			continue

		doc = frappe.new_doc("Ledgix Stock Balance")
		doc.branch = branch
		doc.stock_location = location
		doc.item = item.name
		doc.quantity = flt(item.current_stock)
		doc.valuation_rate = max(flt(item.cost_price), 0)
		doc.insert(ignore_permissions=True)
