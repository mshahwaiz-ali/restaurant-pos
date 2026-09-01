from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate

from ledgix_saas.api.taxation import (
	calculate_tax_breakdown,
	get_tax_profile,
	is_tax_enabled,
	resolve_item_tax_context,
	resolve_tax_rate,
)


SNAPSHOT_FIELDS = (
	"tax_snapshot_locked",
	"item_tax_profile_snapshot",
	"tax_category_snapshot",
	"tax_basis_snapshot",
	"tax_rate_snapshot",
	"notified_retail_price_snapshot",
	"price_includes_tax_snapshot",
	"fbr_rate_description_snapshot",
	"sales_tax_withheld_at_source_per_unit_snapshot",
	"extra_tax_per_unit_snapshot",
	"further_tax_per_unit_snapshot",
	"fed_payable_per_unit_snapshot",
	"hs_code_snapshot",
	"uom_for_fbr_snapshot",
	"sales_type_snapshot",
	"scenario_id_snapshot",
	"sro_schedule_number_snapshot",
	"sro_item_serial_number_snapshot",
)
FIRED_CONTEXT_FIELDS = ("seat_no", "course", "is_course_held", "item_note")


def _format_tax_rate(rate):
	rate = flt(rate)
	return f"{int(rate)}%" if rate == int(rate) else f"{rate:g}%"


def _mapping(item):
	if not frappe.db.exists("DocType", "Ledgix Item Tax Profile"):
		return None
	return frappe.db.get_value(
		"Ledgix Item Tax Profile",
		{"item": item, "active": 1},
		[
			"name", "tax_category", "taxable", "tax_basis", "notified_retail_price",
			"hs_code", "uom_for_fbr", "sales_type", "fbr_rate_description", "scenario_id",
			"sro_schedule_number", "sro_item_serial_number",
			"sales_tax_withheld_at_source_per_unit", "extra_tax_per_unit",
			"further_tax_per_unit", "fed_payable_per_unit",
		],
		as_dict=True,
		order_by="modified desc",
	)


def build_item_fiscal_context(item, posting_date=None):
	"""Return immutable fiscal classification values for a new restaurant line."""
	posting_date = getdate(posting_date) if posting_date else None
	profile = get_tax_profile()
	mapping = _mapping(item)
	if not is_tax_enabled():
		return {
			"item_tax_profile_snapshot": None,
			"tax_category_snapshot": None,
			"tax_basis_snapshot": "Transaction Value",
			"tax_rate_snapshot": 0,
			"notified_retail_price_snapshot": 0,
			"price_includes_tax_snapshot": 0,
			"fbr_rate_description_snapshot": "0%",
			"sales_tax_withheld_at_source_per_unit_snapshot": 0,
			"extra_tax_per_unit_snapshot": 0,
			"further_tax_per_unit_snapshot": 0,
			"fed_payable_per_unit_snapshot": 0,
			"hs_code_snapshot": None,
			"uom_for_fbr_snapshot": None,
			"sales_type_snapshot": None,
			"scenario_id_snapshot": None,
			"sro_schedule_number_snapshot": None,
			"sro_item_serial_number_snapshot": None,
		}

	ctx = resolve_item_tax_context(item, profile=profile)
	tax_category = (mapping.get("tax_category") if mapping else None) or ctx.get("tax_category")
	taxable = cint(mapping.get("taxable")) if mapping else cint(ctx.get("taxable", 1))
	rate = resolve_tax_rate(tax_category, posting_date=posting_date, applies_to="Sales") if taxable else 0
	tax_basis = (mapping.get("tax_basis") if mapping else None) or "Transaction Value"
	notified = flt(mapping.get("notified_retail_price") if mapping else 0)
	if tax_basis == "Notified Retail Price" and notified <= 0:
		frappe.throw(f"Notified Retail Price is required for Third Schedule item {item}.")
	return {
		"item_tax_profile_snapshot": mapping.name if mapping else None,
		"tax_category_snapshot": tax_category,
		"tax_basis_snapshot": tax_basis,
		"tax_rate_snapshot": flt(rate, 2),
		"notified_retail_price_snapshot": notified if tax_basis == "Notified Retail Price" else 0,
		"price_includes_tax_snapshot": 1 if profile.get("price_includes_tax") else 0,
		"fbr_rate_description_snapshot": str((mapping.get("fbr_rate_description") if mapping else "") or "").strip() or _format_tax_rate(rate),
		"sales_tax_withheld_at_source_per_unit_snapshot": flt(mapping.get("sales_tax_withheld_at_source_per_unit") if mapping else 0, 2),
		"extra_tax_per_unit_snapshot": flt(mapping.get("extra_tax_per_unit") if mapping else 0, 2),
		"further_tax_per_unit_snapshot": flt(mapping.get("further_tax_per_unit") if mapping else 0, 2),
		"fed_payable_per_unit_snapshot": flt(mapping.get("fed_payable_per_unit") if mapping else 0, 2),
		"hs_code_snapshot": (mapping.get("hs_code") if mapping else None) or ctx.get("hs_code"),
		"uom_for_fbr_snapshot": (mapping.get("uom_for_fbr") if mapping else None) or ctx.get("uom_for_fbr"),
		"sales_type_snapshot": (mapping.get("sales_type") if mapping else None) or ctx.get("sales_type"),
		"scenario_id_snapshot": (mapping.get("scenario_id") if mapping else None) or ctx.get("scenario_id"),
		"sro_schedule_number_snapshot": (mapping.get("sro_schedule_number") if mapping else None) or ctx.get("sro_schedule_number"),
		" sro_item_serial_number_snapshot".strip(): (mapping.get("sro_item_serial_number") if mapping else None) or ctx.get("sro_item_serial_number"),
	}


def _posting_date_for_order_item(doc, posting_date=None):
	if posting_date:
		return getdate(posting_date)
	if not doc.get("restaurant_order"):
		return None
	opened_at = frappe.db.get_value("Ledgix Restaurant Order", doc.restaurant_order, "opened_at")
	return getdate(opened_at) if opened_at else None


def capture_restaurant_item_tax_snapshot(doc, posting_date=None):
	"""Lock every fiscal value needed to settle/FBR-post this order item later."""
	if cint(doc.get("tax_snapshot_locked")):
		return
	values = build_item_fiscal_context(doc.item, _posting_date_for_order_item(doc, posting_date))
	for fieldname, value in values.items():
		doc.set(fieldname, value)
	doc.tax_snapshot_locked = 1
	recalculate_restaurant_item_tax(doc)


def recalculate_restaurant_item_tax(doc):
	"""Recalculate derived amounts using only the already-locked fiscal snapshot."""
	qty = flt(doc.billable_quantity, 6)
	transaction_amount = flt(doc.amount, 2)
	tax_basis = doc.tax_basis_snapshot or "Transaction Value"
	basis_amount = (
		flt(flt(doc.notified_retail_price_snapshot) * qty, 2)
		if tax_basis == "Notified Retail Price"
		else transaction_amount
	)
	breakdown = calculate_tax_breakdown(
		basis_amount,
		flt(doc.tax_rate_snapshot),
		price_includes_tax=bool(cint(doc.price_includes_tax_snapshot)),
	)
	sales_tax = flt(breakdown.get("tax_amount"), 2)
	withheld = flt(flt(doc.sales_tax_withheld_at_source_per_unit_snapshot) * qty, 2)
	extra_tax = flt(flt(doc.extra_tax_per_unit_snapshot) * qty, 2)
	further_tax = flt(flt(doc.further_tax_per_unit_snapshot) * qty, 2)
	fed_payable = flt(flt(doc.fed_payable_per_unit_snapshot) * qty, 2)
	invoice_tax = flt(sales_tax + extra_tax + further_tax + fed_payable, 2)

	doc.taxable_amount = flt(breakdown.get("taxable_amount"), 2)
	doc.sales_tax_amount = sales_tax
	doc.sales_tax_withheld_at_source = withheld
	doc.extra_tax_amount = extra_tax
	doc.further_tax_amount = further_tax
	doc.fed_payable_amount = fed_payable
	doc.tax_amount = invoice_tax
	doc.net_amount = flt(
		transaction_amount if cint(doc.price_includes_tax_snapshot) else transaction_amount + invoice_tax,
		2,
	)


def before_insert_order_item(doc, method=None):
	capture_restaurant_item_tax_snapshot(doc)


def validate_order_item_tax_snapshot(doc, method=None):
	before = doc.get_doc_before_save()
	if before:
		changed = [field for field in SNAPSHOT_FIELDS if before.get(field) != doc.get(field)]
		if changed and not getattr(doc.flags, "allow_snapshot_refresh", False):
			frappe.throw(
				"Restaurant Order Item fiscal snapshots are immutable after creation.",
				frappe.PermissionError,
			)
		if flt(before.get("fired_quantity"), 6) > 0:
			context_changed = [field for field in FIRED_CONTEXT_FIELDS if before.get(field) != doc.get(field)]
			if context_changed:
				frappe.throw(
					"Seat, course, hold state and kitchen note are locked after the item is fired. Void/re-add the item for a kitchen-visible change."
				)
	if not cint(doc.get("tax_snapshot_locked")):
		capture_restaurant_item_tax_snapshot(doc)
	recalculate_restaurant_item_tax(doc)
