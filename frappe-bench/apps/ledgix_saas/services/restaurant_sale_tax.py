from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from ledgix_saas.services.restaurant_charges import build_charge_fiscal_rows
from ledgix_saas.services.restaurant_fiscal import build_discounted_fiscal_rows


def _append_tax_detail(sale, sale_row, row):
	sale_row.item_tax_profile_snapshot = row.get("item_tax_profile_snapshot")
	sale_row.tax_basis_snapshot = row.get("tax_basis")
	sale_row.tax_rate_snapshot = flt(row.get("tax_rate"), 2)
	sale_row.notified_retail_price_snapshot = flt(row.get("notified_retail_price"), 2)
	sale.append("tax_details", {
		"sale": sale.name,
		"sale_item_row": sale_row.name,
		"item": row["item"],
		"qty": flt(row.get("qty")),
		"rate": flt(row.get("rate", row.get("effective_rate")), 2),
		"gross_amount": flt(row.get("gross_amount"), 2),
		"discount_amount": flt(row.get("discount_amount"), 2),
		"tax_basis": row.get("tax_basis") or "Transaction Value",
		"notified_retail_price": flt(row.get("notified_retail_price"), 2),
		"taxable_amount": flt(row.get("taxable_amount"), 2),
		"tax_category": row.get("tax_category"),
		"tax_rate": flt(row.get("tax_rate"), 2),
		"fbr_rate_description": row.get("fbr_rate_description"),
		"tax_amount": flt(row.get("tax_amount_fbr", row.get("tax_amount")), 2),
		"sales_tax_withheld_at_source": flt(row.get("sales_tax_withheld_at_source_fbr", row.get("sales_tax_withheld_at_source")), 2),
		"extra_tax": flt(row.get("extra_tax_fbr", row.get("extra_tax")), 2),
		"further_tax": flt(row.get("further_tax_fbr", row.get("further_tax")), 2),
		"fed_payable": flt(row.get("fed_payable_fbr", row.get("fed_payable")), 2),
		"net_amount": flt(row.get("net_amount"), 2),
		"price_includes_tax": cint(row.get("price_includes_tax")),
		"hs_code": row.get("hs_code"),
		"uom_for_fbr": row.get("uom_for_fbr"),
		"sales_type": row.get("sales_type"),
		"scenario_id": row.get("scenario_id"),
		"sro_schedule_number": row.get("sro_schedule_number"),
		"sro_item_serial_number": row.get("sro_item_serial_number"),
	})


def apply_restaurant_sale_tax_snapshot(sale):
	"""Build Sale/FBR rows from locked item and mapped charge snapshots."""
	if not sale.restaurant_order:
		frappe.throw("Restaurant Sale requires a Restaurant Order reference.")

	order = frappe.get_doc("Ledgix Restaurant Order", sale.restaurant_order)
	if order.branch != sale.branch or order.stock_location != sale.stock_location:
		frappe.throw("Restaurant Sale operating context must match the source Restaurant Order.")

	item_fiscal = build_discounted_fiscal_rows(order.name, flt(sale.discount_amount))
	charge_fiscal = build_charge_fiscal_rows(
		order,
		service_charge=flt(sale.get("service_charge")),
		tip_amount=flt(sale.get("tip_amount")),
		persist=False,
	)
	items_by_order_item = {row["restaurant_order_item"]: row for row in item_fiscal["rows"]}
	charges_by_name = {row["restaurant_order_charge"]: row for row in charge_fiscal["rows"]}

	sale.set("tax_details", [])
	seen_items = set()
	seen_charges = set()
	for sale_row in sale.items:
		order_item_name = sale_row.get("restaurant_order_item")
		charge_name = sale_row.get("restaurant_order_charge")
		if order_item_name:
			if charge_name or order_item_name in seen_items:
				frappe.throw("Restaurant Sale item lineage is ambiguous or duplicated.")
			row = items_by_order_item.get(order_item_name)
			if not row:
				frappe.throw(f"Restaurant Order Item {order_item_name} is not billable on {order.name}.")
			seen_items.add(order_item_name)
			if sale_row.item != row["item"] or abs(flt(sale_row.quantity) - flt(row["qty"])) > 0.000001:
				frappe.throw(f"Sale line does not match Restaurant Order Item {order_item_name}.")
			if abs(flt(sale_row.rate) - flt(row["effective_rate"])) > 0.01:
				frappe.throw(f"Sale discounted rate does not match Restaurant Order Item {order_item_name}.")
			_append_tax_detail(sale, sale_row, {**row, "rate": row["effective_rate"]})
		elif charge_name:
			if charge_name in seen_charges:
				frappe.throw("Restaurant Sale charge lineage is duplicated.")
			row = charges_by_name.get(charge_name)
			if not row:
				frappe.throw(f"Restaurant Order Charge {charge_name} is not payable on {order.name}.")
			seen_charges.add(charge_name)
			if sale_row.item != row["item"] or abs(flt(sale_row.quantity) - 1) > 0.000001:
				frappe.throw(f"Sale line does not match Restaurant Order Charge {charge_name}.")
			if abs(flt(sale_row.rate) - flt(row["amount"])) > 0.01:
				frappe.throw(f"Sale amount does not match Restaurant Order Charge {charge_name}.")
			_append_tax_detail(sale, sale_row, row)
		else:
			frappe.throw("Every Restaurant Sale line requires an Order Item or Order Charge reference.")

	if set(items_by_order_item) != seen_items:
		missing = ", ".join(sorted(set(items_by_order_item) - seen_items))
		frappe.throw(f"Restaurant Sale is missing billable Order Items: {missing}")
	if set(charges_by_name) != seen_charges:
		missing = ", ".join(sorted(set(charges_by_name) - seen_charges))
		frappe.throw(f"Restaurant Sale is missing payable Order Charges: {missing}")

	sale.total_amount = flt(item_fiscal["total_amount"] + charge_fiscal["base_amount"], 2)
	sale.tax_amount = flt(item_fiscal["tax_amount"] + charge_fiscal["tax_amount"], 2)
	sale.grand_total = flt(item_fiscal["net_total"] + charge_fiscal["net_total"], 2)
	if abs(flt(sale.grand_total) - flt(order.grand_total)) > 0.01:
		frappe.throw(
			f"Restaurant Sale total {flt(sale.grand_total):.2f} does not match source check total {flt(order.grand_total):.2f}."
		)
	return {
		"summary": {
			"total_tax_amount": sale.tax_amount,
			"grand_total": sale.grand_total,
		},
		"validation": {"valid": True, "warnings": []},
	}
