from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cint, flt

from ledgix_saas.services.recipe import build_recipe_snapshot
from ledgix_saas.services.uom import to_stock_qty


def build_locked_order_consumption(item, *, recipe=None, modifier_rows=None):
	"""Build the per-unit ingredient plan that becomes part of an order-item snapshot.

	This runs at Restaurant Order Item creation time. Modifier effects are read
	from the already-snapshotted order modifier rows, not from mutable modifier
	masters. The resulting rows are persisted and KOT fire consumes only those
	persisted rows.
	"""
	snapshot = build_recipe_snapshot(item=item, recipe=recipe) if recipe else None
	yield_quantity = flt(snapshot.get("yield_quantity")) if snapshot else 1.0
	if yield_quantity <= 0:
		frappe.throw("Recipe snapshot yield quantity must be greater than zero.")

	consumption = defaultdict(float)
	cost_rates = {}
	excluded = set()
	for row in modifier_rows or []:
		stock_effect = row.get("stock_effect")
		linked_item = row.get("linked_item")
		selection_quantity = flt(row.get("selection_quantity") or 1)
		if stock_effect == "Exclude Recipe Ingredient" and linked_item:
			excluded.add(linked_item)
		elif stock_effect == "Add Linked Item" and linked_item:
			stock_qty = to_stock_qty(linked_item, flt(row.get("stock_quantity")), row.get("uom"))
			consumption[linked_item] += stock_qty * selection_quantity
			cost_rates[linked_item] = flt(frappe.db.get_value("Ledgix Item", linked_item, "cost_price"))

	for ingredient in (snapshot or {}).get("ingredients", []):
		if not cint(ingredient.get("consume_stock")):
			continue
		ingredient_item = ingredient.get("ingredient_item")
		if ingredient_item in excluded:
			continue
		consumption[ingredient_item] += flt(ingredient.get("consumption_quantity")) / yield_quantity
		cost_rates[ingredient_item] = flt(ingredient.get("cost_price"))

	rows = []
	for ingredient_item in sorted(consumption):
		quantity = flt(consumption[ingredient_item], 6)
		if quantity <= 0:
			continue
		cost_rate = flt(cost_rates.get(ingredient_item), 6)
		rows.append({
			"ingredient_item": ingredient_item,
			"stock_uom": frappe.db.get_value("Ledgix Item", ingredient_item, "stock_uom"),
			"quantity_per_unit": quantity,
			"cost_rate": cost_rate,
			"line_cost_per_unit": flt(quantity * cost_rate, 4),
		})
	return rows


def persist_order_consumption_snapshot(order_item):
	if frappe.db.exists("Ledgix Restaurant Order Consumption", {"restaurant_order_item": order_item.name}):
		return
	rows = build_locked_order_consumption(
		order_item.item,
		recipe=order_item.recipe,
		modifier_rows=[row.as_dict() for row in (order_item.modifiers or [])],
	)
	for row in rows:
		doc = frappe.get_doc({
			"doctype": "Ledgix Restaurant Order Consumption",
			"restaurant_order_item": order_item.name,
			**row,
		})
		doc.flags.from_restaurant_order_service = True
		doc.insert(ignore_permissions=True)
