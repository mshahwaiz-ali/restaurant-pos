from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from ledgix_saas.services.restaurant_fiscal import build_discounted_fiscal_rows


def apply_restaurant_sale_tax_snapshot(sale):
	"""Build Sale/FBR rows from locked order snapshots plus the approved discount."""
	if not sale.restaurant_order:
		frappe.throw("Restaurant Sale requires a Restaurant Order reference.")

	order = frappe.get_doc("Ledgix Restaurant Order", sale.restaurant_order)
	if order.branch != sale.branch or order.stock_location != sale.stock_location:
		frappe.throw("Restaurant Sale operating context must match the source Restaurant Order.")
	if flt(sale.get("service_charge")) or flt(sale.get("tip_amount")):
		frappe.throw(
			"Service Charge / Tip require fiscal charge-item mapping before settlement. "
			"They cannot be added as an unclassified invoice amount."
		)

	fiscal = build_discounted_fiscal_rows(order.name, flt(sale.discount_amount))
	fiscal_by_item = {row["restaurant_order_item"]: row for row in fiscal["rows"]}

	sale.set("tax_details", [])
	seen = set()
	for sale_row in sale.items:
		order_item_name = sale_row.get("restaurant_order_item")
		if not order_item_name or order_item_name in seen:
			frappe.throw("Every Restaurant Sale line requires one unique Restaurant Order Item reference.")
		seen.add(order_item_name)
		row = fiscal_by_item.get(order_item_name)
		if not row:
			frappe.throw(f"Restaurant Order Item {order_item_name} is not an active billable line on {order.name}.")
		if sale_row.item != row["item"]:
			frappe.throw(f"Sale line item does not match Restaurant Order Item {order_item_name}.")
		if abs(flt(sale_row.quantity) - flt(row["qty"])) > 0.000001:
			frappe.throw(f"Sale quantity does not match Restaurant Order Item {order_item_name}.")
		if abs(flt(sale_row.rate) - flt(row["effective_rate"])) > 0.01:
			frappe.throw(f"Sale discounted rate does not match Restaurant Order Item {order_item_name}.")

		sale_row.item_tax_profile_snapshot = row["item_tax_profile_snapshot"]
		sale_row.tax_basis_snapshot = row["tax_basis"]
		sale_row.tax_rate_snapshot = flt(row["tax_rate"], 2)
		sale_row.notified_retail_price_snapshot = flt(row["notified_retail_price"], 2)
		sale.append("tax_details", {
			"sale": sale.name,
			"sale_item_row": sale_row.name,
			"item": row["item"],
			"qty": flt(row["qty"]),
			"rate": flt(row["effective_rate"], 2),
			"gross_amount": flt(row["gross_amount"], 2),
			"discount_amount": flt(row["discount_amount"], 2),
			"tax_basis": row["tax_basis"],
			"notified_retail_price": flt(row["notified_retail_price"], 2),
			"taxable_amount": flt(row["taxable_amount"], 2),
			"tax_category": row["tax_category"],
			"tax_rate": flt(row["tax_rate"], 2),
			"fbr_rate_description": row["fbr_rate_description"],
			"tax_amount": flt(row["tax_amount"], 2),
			"sales_tax_withheld_at_source": flt(row["sales_tax_withheld_at_source"], 2),
			"extra_tax": flt(row["extra_tax"], 2),
			"further_tax": flt(row["further_tax"], 2),
			"fed_payable": flt(row["fed_payable"], 2),
			"net_amount": flt(row["net_amount"], 2),
			"price_includes_tax": cint(row["price_includes_tax"]),
			"hs_code": row["hs_code"],
			"uom_for_fbr": row["uom_for_fbr"],
			"sales_type": row["sales_type"],
			"scenario_id": row["scenario_id"],
			"sro_schedule_number": row["sro_schedule_number"],
			"sro_item_serial_number": row["sro_item_serial_number"],
		})

	if set(fiscal_by_item) != seen:
		missing = ", ".join(sorted(set(fiscal_by_item) - seen))
		frappe.throw(f"Restaurant Sale is missing billable Order Items: {missing}")

	sale.total_amount = flt(fiscal["total_amount"], 2)
	sale.tax_amount = flt(fiscal["tax_amount"], 2)
	sale.grand_total = flt(fiscal["net_total"], 2)
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
