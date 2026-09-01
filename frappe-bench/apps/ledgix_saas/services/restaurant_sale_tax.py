from __future__ import annotations

import frappe
from frappe.utils import cint, flt


def apply_restaurant_sale_tax_snapshot(sale):
	"""Build Sale/FBR tax rows only from the locked Restaurant Order Item snapshots."""
	if not sale.restaurant_order:
		frappe.throw("Restaurant Sale requires a Restaurant Order reference.")

	order = frappe.get_doc("Ledgix Restaurant Order", sale.restaurant_order)
	if order.branch != sale.branch or order.stock_location != sale.stock_location:
		frappe.throw("Restaurant Sale operating context must match the source Restaurant Order.")

	order_items = {
		row.name: row
		for row in frappe.get_all(
			"Ledgix Restaurant Order Item",
			filters={"restaurant_order": order.name, "is_voided": 0},
			fields=[
				"name", "item", "billable_quantity", "amount", "taxable_amount",
				"sales_tax_amount", "sales_tax_withheld_at_source", "extra_tax_amount",
				"further_tax_amount", "fed_payable_amount", "tax_amount", "net_amount",
				"item_tax_profile_snapshot", "tax_category_snapshot", "tax_basis_snapshot",
				"tax_rate_snapshot", "notified_retail_price_snapshot", "price_includes_tax_snapshot",
				"fbr_rate_description_snapshot", "hs_code_snapshot", "uom_for_fbr_snapshot",
				"sales_type_snapshot", "scenario_id_snapshot", "sro_schedule_number_snapshot",
				"sro_item_serial_number_snapshot", "tax_snapshot_locked",
			],
			limit_page_length=0,
		)
		if flt(row.billable_quantity) > 0
	}

	sale.set("tax_details", [])
	seen = set()
	item_net_total = 0.0
	invoice_tax_total = 0.0
	for sale_row in sale.items:
		order_item_name = sale_row.get("restaurant_order_item")
		if not order_item_name or order_item_name in seen:
			frappe.throw("Every Restaurant Sale line requires one unique Restaurant Order Item reference.")
		seen.add(order_item_name)
		order_item = order_items.get(order_item_name)
		if not order_item:
			frappe.throw(f"Restaurant Order Item {order_item_name} is not an active billable line on {order.name}.")
		if not cint(order_item.tax_snapshot_locked):
			frappe.throw(f"Restaurant Order Item {order_item.name} is missing its locked fiscal snapshot.")
		if sale_row.item != order_item.item:
			frappe.throw(f"Sale line item does not match Restaurant Order Item {order_item.name}.")
		if abs(flt(sale_row.quantity) - flt(order_item.billable_quantity)) > 0.000001:
			frappe.throw(f"Sale quantity does not match Restaurant Order Item {order_item.name}.")

		sale_row.item_tax_profile_snapshot = order_item.item_tax_profile_snapshot
		sale_row.tax_basis_snapshot = order_item.tax_basis_snapshot
		sale_row.tax_rate_snapshot = flt(order_item.tax_rate_snapshot, 2)
		sale_row.notified_retail_price_snapshot = flt(order_item.notified_retail_price_snapshot, 2)

		item_net_total += flt(order_item.net_amount)
		invoice_tax_total += flt(order_item.tax_amount)
		sale.append("tax_details", {
			"sale": sale.name,
			"sale_item_row": sale_row.name,
			"item": order_item.item,
			"qty": flt(order_item.billable_quantity),
			"rate": flt(sale_row.rate, 2),
			"gross_amount": flt(order_item.amount, 2),
			"discount_amount": 0,
			"tax_basis": order_item.tax_basis_snapshot or "Transaction Value",
			"notified_retail_price": flt(order_item.notified_retail_price_snapshot, 2),
			"taxable_amount": flt(order_item.taxable_amount, 2),
			"tax_category": order_item.tax_category_snapshot,
			"tax_rate": flt(order_item.tax_rate_snapshot, 2),
			"fbr_rate_description": order_item.fbr_rate_description_snapshot,
			"tax_amount": flt(order_item.sales_tax_amount, 2),
			"sales_tax_withheld_at_source": flt(order_item.sales_tax_withheld_at_source, 2),
			"extra_tax": flt(order_item.extra_tax_amount, 2),
			"further_tax": flt(order_item.further_tax_amount, 2),
			"fed_payable": flt(order_item.fed_payable_amount, 2),
			"net_amount": flt(order_item.net_amount, 2),
			"price_includes_tax": cint(order_item.price_includes_tax_snapshot),
			"hs_code": order_item.hs_code_snapshot,
			"uom_for_fbr": order_item.uom_for_fbr_snapshot,
			"sales_type": order_item.sales_type_snapshot,
			"scenario_id": order_item.scenario_id_snapshot,
			"sro_schedule_number": order_item.sro_schedule_number_snapshot,
			"sro_item_serial_number": order_item.sro_item_serial_number_snapshot,
		})

	if set(order_items) != seen:
		missing = ", ".join(sorted(set(order_items) - seen))
		frappe.throw(f"Restaurant Sale is missing billable Order Items: {missing}")

	sale.tax_amount = flt(invoice_tax_total, 2)
	sale.grand_total = flt(
		item_net_total
		- flt(sale.discount_amount)
		+ flt(sale.get("service_charge"))
		+ flt(sale.get("tip_amount")),
		2,
	)
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
