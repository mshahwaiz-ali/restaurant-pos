from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate

from ledgix_saas.api.fbr_settings import get_fbr_settings_internal
from ledgix_saas.api.taxation import calculate_tax_breakdown
from ledgix_saas.services.restaurant_tax_snapshots import build_item_fiscal_context


CHARGE_CONFIG = {
	"Service Charge": {"order_field": "service_charge", "branch_field": "service_charge_item"},
	"Tip": {"order_field": "tip_amount", "branch_field": "tip_item"},
}


def _configured_item(order, charge_type):
	config = CHARGE_CONFIG.get(charge_type)
	if not config:
		frappe.throw("Unsupported Restaurant Charge Type.")
	fieldname = config["branch_field"]
	if not frappe.get_meta("Ledgix Branch").has_field(fieldname):
		frappe.throw(f"Branch field {fieldname} is not installed yet. Run the Restaurant migration before using charges.")
	item = frappe.db.get_value("Ledgix Branch", order.branch, fieldname)
	if not item:
		frappe.throw(f"Configure a fiscal Ledgix Item for {charge_type} on Branch {order.branch}.")
	meta = frappe.db.get_value(
		"Ledgix Item",
		{"name": item, "active": 1},
		["name", "item_name", "track_inventory", "tracking_type"],
		as_dict=True,
	)
	if not meta:
		frappe.throw(f"Configured {charge_type} item must be active.")
	if cint(meta.track_inventory):
		frappe.throw(f"Configured {charge_type} item must be non-stock.")
	if meta.tracking_type and meta.tracking_type != "Normal":
		frappe.throw(f"Configured {charge_type} item cannot use lot/serial tracking.")
	return meta


def _validate_fbr_classification(context, charge_type):
	settings = get_fbr_settings_internal() or {}
	if not cint(settings.get("enabled")):
		return
	mode = settings.get("mode") or "Disabled"
	if mode not in {"Sandbox", "Production"}:
		return
	missing = []
	for fieldname, label in (
		("hs_code_snapshot", "HS Code"),
		("uom_for_fbr_snapshot", "FBR UOM"),
		("sales_type_snapshot", "Sales Type"),
	):
		if not str(context.get(fieldname) or "").strip():
			missing.append(label)
	if mode == "Sandbox" and not str(context.get("scenario_id_snapshot") or "").strip():
		missing.append("Scenario ID")
	if missing:
		frappe.throw(f"Configured {charge_type} item is missing FBR classification: {', '.join(missing)}.")


def _calculate_amounts(context, amount):
	amount = flt(amount, 2)
	tax_basis = context.get("tax_basis_snapshot") or "Transaction Value"
	basis_amount = (
		flt(context.get("notified_retail_price_snapshot"), 2)
		if tax_basis == "Notified Retail Price"
		else amount
	)
	breakdown = calculate_tax_breakdown(
		basis_amount,
		flt(context.get("tax_rate_snapshot")),
		price_includes_tax=bool(cint(context.get("price_includes_tax_snapshot"))),
	)
	sales_tax = flt(breakdown.get("tax_amount"), 2)
	withheld = flt(context.get("sales_tax_withheld_at_source_per_unit_snapshot"), 2)
	extra_tax = flt(context.get("extra_tax_per_unit_snapshot"), 2)
	further_tax = flt(context.get("further_tax_per_unit_snapshot"), 2)
	fed_payable = flt(context.get("fed_payable_per_unit_snapshot"), 2)
	invoice_tax = flt(sales_tax + extra_tax + further_tax + fed_payable, 2)
	net_amount = flt(
		amount if cint(context.get("price_includes_tax_snapshot")) else amount + invoice_tax,
		2,
	)
	return {
		"amount": amount,
		"taxable_amount": flt(breakdown.get("taxable_amount"), 2),
		"sales_tax_amount": sales_tax,
		"sales_tax_withheld_at_source": withheld,
		"extra_tax_amount": extra_tax,
		"further_tax_amount": further_tax,
		"fed_payable_amount": fed_payable,
		"tax_amount": invoice_tax,
		"net_amount": net_amount,
	}


def _existing_charge(order_name, charge_type):
	name = frappe.db.get_value(
		"Ledgix Restaurant Order Charge",
		{"restaurant_order": order_name, "charge_type": charge_type},
		"name",
	)
	return frappe.get_doc("Ledgix Restaurant Order Charge", name) if name else None


def _context_from_doc(doc):
	return {
		"item_tax_profile_snapshot": doc.item_tax_profile_snapshot,
		"tax_category_snapshot": doc.tax_category_snapshot,
		"tax_basis_snapshot": doc.tax_basis_snapshot,
		"tax_rate_snapshot": flt(doc.tax_rate_snapshot, 2),
		"notified_retail_price_snapshot": flt(doc.notified_retail_price_snapshot, 2),
		"price_includes_tax_snapshot": cint(doc.price_includes_tax_snapshot),
		"fbr_rate_description_snapshot": doc.fbr_rate_description_snapshot,
		"sales_tax_withheld_at_source_per_unit_snapshot": flt(doc.sales_tax_withheld_at_source_per_unit_snapshot, 2),
		"extra_tax_per_unit_snapshot": flt(doc.extra_tax_per_unit_snapshot, 2),
		"further_tax_per_unit_snapshot": flt(doc.further_tax_per_unit_snapshot, 2),
		"fed_payable_per_unit_snapshot": flt(doc.fed_payable_per_unit_snapshot, 2),
		"hs_code_snapshot": doc.hs_code_snapshot,
		"uom_for_fbr_snapshot": doc.uom_for_fbr_snapshot,
		"sales_type_snapshot": doc.sales_type_snapshot,
		"scenario_id_snapshot": doc.scenario_id_snapshot,
		"sro_schedule_number_snapshot": doc.sro_schedule_number_snapshot,
		"sro_item_serial_number_snapshot": doc.sro_item_serial_number_snapshot,
	}


def _row_payload(order, charge_type, amount, *, persist=False):
	amount = flt(amount, 2)
	if amount < 0:
		frappe.throw(f"{charge_type} cannot be negative.")
	existing = _existing_charge(order.name, charge_type) if frappe.db.exists("DocType", "Ledgix Restaurant Order Charge") else None
	if amount <= 0 and not existing:
		return None

	if existing:
		item = existing.item
		item_name = existing.item_name_snapshot or item
		context = _context_from_doc(existing)
	else:
		item_meta = _configured_item(order, charge_type)
		item = item_meta.name
		item_name = item_meta.item_name or item
		context = build_item_fiscal_context(item, getdate(order.opened_at) if order.opened_at else None)
	_validate_fbr_classification(context, charge_type)

	amounts = _calculate_amounts(context, amount)
	payload = {
		"restaurant_order_charge": existing.name if existing else None,
		"charge_type": charge_type,
		"item": item,
		"item_name_snapshot": item_name,
		**context,
		**amounts,
	}
	if not persist:
		return payload

	if existing:
		for fieldname, value in amounts.items():
			existing.set(fieldname, value)
		existing.flags.allow_charge_amount_update = True
		existing.save(ignore_permissions=True)
		payload["restaurant_order_charge"] = existing.name
		return payload

	doc = frappe.get_doc({
		"doctype": "Ledgix Restaurant Order Charge",
		"restaurant_order": order.name,
		"charge_type": charge_type,
		"item": item,
		"item_name_snapshot": item_name,
		"tax_snapshot_locked": 1,
		**context,
		**amounts,
	})
	doc.flags.from_restaurant_settlement_service = True
	doc.insert(ignore_permissions=True)
	payload["restaurant_order_charge"] = doc.name
	return payload


def build_charge_fiscal_rows(order, service_charge=0, tip_amount=0, *, persist=False):
	rows = []
	for charge_type, amount in (("Service Charge", service_charge), ("Tip", tip_amount)):
		row = _row_payload(order, charge_type, amount, persist=persist)
		if not row or flt(row["amount"]) <= 0:
			continue
		rows.append({
			**row,
			"qty": 1.0,
			"rate": flt(row["amount"], 2),
			"gross_amount": flt(row["amount"], 2),
			"discount_amount": 0.0,
			"tax_basis": row["tax_basis_snapshot"] or "Transaction Value",
			"notified_retail_price": flt(row["notified_retail_price_snapshot"], 2),
			"tax_category": row["tax_category_snapshot"],
			"tax_rate": flt(row["tax_rate_snapshot"], 2),
			"fbr_rate_description": row["fbr_rate_description_snapshot"],
			"tax_amount_fbr": flt(row["sales_tax_amount"], 2),
			"sales_tax_withheld_at_source_fbr": flt(row["sales_tax_withheld_at_source"], 2),
			"extra_tax_fbr": flt(row["extra_tax_amount"], 2),
			"further_tax_fbr": flt(row["further_tax_amount"], 2),
			"fed_payable_fbr": flt(row["fed_payable_amount"], 2),
			"price_includes_tax": cint(row["price_includes_tax_snapshot"]),
			"hs_code": row["hs_code_snapshot"],
			"uom_for_fbr": row["uom_for_fbr_snapshot"],
			"sales_type": row["sales_type_snapshot"],
			"scenario_id": row["scenario_id_snapshot"],
			"sro_schedule_number": row["sro_schedule_number_snapshot"],
			"sro_item_serial_number": row["sro_item_serial_number_snapshot"],
		})
	return {
		"rows": rows,
		"base_amount": flt(sum(flt(row["amount"]) for row in rows), 2),
		"tax_amount": flt(sum(flt(row["tax_amount"]) for row in rows), 2),
		"net_total": flt(sum(flt(row["net_amount"]) for row in rows), 2),
	}
