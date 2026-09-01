from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from ledgix_saas.api.taxation import calculate_tax_breakdown


FISCAL_ITEM_FIELDS = [
	"name",
	"item",
	"billable_quantity",
	"amount",
	"line_unit_rate",
	"list_rate",
	"rate",
	"modifier_unit_total",
	"price_list_snapshot",
	"item_price_reference",
	"recipe_cost_per_unit",
	"seat_no",
	"course",
	"fired_quantity",
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
]


def get_billable_order_items(order_name):
	return [
		row
		for row in frappe.get_all(
			"Ledgix Restaurant Order Item",
			filters={"restaurant_order": order_name, "is_voided": 0},
			fields=FISCAL_ITEM_FIELDS,
			order_by="creation asc",
			limit_page_length=0,
		)
		if flt(row.billable_quantity) > 0
	]


def _discount_allocations(rows, discount_amount):
	discount_amount = flt(discount_amount, 2)
	gross_total = flt(sum(flt(row.amount) for row in rows), 2)
	if discount_amount < 0:
		frappe.throw("Discount cannot be negative.")
	if discount_amount > gross_total + 0.005:
		frappe.throw("Discount cannot exceed the billable item subtotal.")
	if not rows or discount_amount <= 0:
		return {row.name: 0.0 for row in rows}, gross_total

	allocations = {}
	remaining = discount_amount
	eligible = [row for row in rows if flt(row.amount) > 0]
	for index, row in enumerate(eligible):
		if index == len(eligible) - 1:
			allocated = remaining
		else:
			allocated = flt(discount_amount * flt(row.amount) / gross_total, 2) if gross_total else 0
			allocated = min(allocated, remaining, flt(row.amount))
		allocations[row.name] = flt(allocated, 2)
		remaining = flt(remaining - allocated, 2)
	for row in rows:
		allocations.setdefault(row.name, 0.0)
	return allocations, gross_total


def build_discounted_fiscal_rows(order_name, discount_amount=0):
	"""Build payable/FBR rows using only locked Restaurant Order Item fiscal data.

	This mirrors the existing POS discount policy: allocate the sale-level discount
	proportionally across item transaction values, then recalculate ordinary sales
	tax from each locked tax rate/basis. Per-unit special tax components remain
	quantity-based. No current tax/pricing master is consulted.
	"""
	rows = get_billable_order_items(order_name)
	if not rows:
		frappe.throw("Restaurant Order has no billable items.")
	for row in rows:
		if not cint(row.tax_snapshot_locked):
			frappe.throw(f"Restaurant Order Item {row.name} is missing its locked fiscal snapshot.")

	allocations, gross_total = _discount_allocations(rows, discount_amount)
	fiscal_rows = []
	invoice_tax_total = 0.0
	net_total = 0.0
	for row in rows:
		qty = flt(row.billable_quantity, 6)
		discount = flt(allocations.get(row.name), 2)
		transaction_amount = flt(max(flt(row.amount) - discount, 0), 2)
		tax_basis = row.tax_basis_snapshot or "Transaction Value"
		if tax_basis == "Notified Retail Price":
			basis_amount = flt(flt(row.notified_retail_price_snapshot) * qty, 2)
		else:
			basis_amount = transaction_amount

		breakdown = calculate_tax_breakdown(
			basis_amount,
			flt(row.tax_rate_snapshot),
			price_includes_tax=bool(cint(row.price_includes_tax_snapshot)),
		)
		sales_tax = flt(breakdown.get("tax_amount"), 2)
		withheld = flt(flt(row.sales_tax_withheld_at_source_per_unit_snapshot) * qty, 2)
		extra_tax = flt(flt(row.extra_tax_per_unit_snapshot) * qty, 2)
		further_tax = flt(flt(row.further_tax_per_unit_snapshot) * qty, 2)
		fed_payable = flt(flt(row.fed_payable_per_unit_snapshot) * qty, 2)
		invoice_tax = flt(sales_tax + extra_tax + further_tax + fed_payable, 2)
		net_amount = flt(
			transaction_amount if cint(row.price_includes_tax_snapshot) else transaction_amount + invoice_tax,
			2,
		)
		invoice_tax_total += invoice_tax
		net_total += net_amount
		fiscal_rows.append({
			"restaurant_order_item": row.name,
			"item": row.item,
			"qty": qty,
			"original_gross_amount": flt(row.amount, 2),
			"gross_amount": transaction_amount,
			"discount_amount": discount,
			"effective_rate": flt(transaction_amount / qty, 2) if qty else 0,
			"tax_basis": tax_basis,
			"notified_retail_price": flt(row.notified_retail_price_snapshot, 2),
			"taxable_amount": flt(breakdown.get("taxable_amount"), 2),
			"tax_category": row.tax_category_snapshot,
			"tax_rate": flt(row.tax_rate_snapshot, 2),
			"fbr_rate_description": row.fbr_rate_description_snapshot,
			"tax_amount": sales_tax,
			"sales_tax_withheld_at_source": withheld,
			"extra_tax": extra_tax,
			"further_tax": further_tax,
			"fed_payable": fed_payable,
			"invoice_tax": invoice_tax,
			"net_amount": net_amount,
			"price_includes_tax": cint(row.price_includes_tax_snapshot),
			"item_tax_profile_snapshot": row.item_tax_profile_snapshot,
			"hs_code": row.hs_code_snapshot,
			"uom_for_fbr": row.uom_for_fbr_snapshot,
			"sales_type": row.sales_type_snapshot,
			"scenario_id": row.scenario_id_snapshot,
			"sro_schedule_number": row.sro_schedule_number_snapshot,
			"sro_item_serial_number": row.sro_item_serial_number_snapshot,
			"price_list_snapshot": row.price_list_snapshot,
			"item_price_reference": row.item_price_reference,
			"list_rate": flt(row.list_rate, 2),
			"base_rate_snapshot": flt(row.rate, 2),
			"modifier_unit_total_snapshot": flt(row.modifier_unit_total, 2),
			"line_unit_rate_snapshot": flt(row.line_unit_rate, 2),
			"cost_price": flt(row.recipe_cost_per_unit, 4),
			"seat_no": cint(row.seat_no),
			"course": row.course,
			"fired_quantity": flt(row.fired_quantity, 6),
		})

	return {
		"rows": fiscal_rows,
		"gross_total": gross_total,
		"discount_amount": flt(discount_amount, 2),
		"total_amount": flt(sum(flt(row["gross_amount"]) for row in fiscal_rows), 2),
		"tax_amount": flt(invoice_tax_total, 2),
		"net_total": flt(net_total, 2),
	}
