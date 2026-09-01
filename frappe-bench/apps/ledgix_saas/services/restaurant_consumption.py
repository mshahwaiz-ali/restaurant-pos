from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cint, flt

from ledgix_saas.services.recipe import build_recipe_snapshot
from ledgix_saas.services.uom import to_stock_qty


def build_locked_order_consumption(item, *, recipe=None, modifier_rows=None):
	"""Build the per-unit stock plan that becomes part of an order-item snapshot.

	Recipe-backed menu items consume their locked ingredients. A restaurant item
	without a recipe but with inventory tracking (for example a bottled drink)
	consumes itself one-for-one at kitchen fire. Non-stock items create no stock
	movement. Modifier effects are read from already-snapshotted order rows.
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

	if snapshot:
		for ingredient in snapshot.get("ingredients", []):
			if not cint(ingredient.get("consume_stock")):
				continue
			ingredient_item = ingredient.get("ingredient_item")
			if ingredient_item in excluded:
				continue
			consumption[ingredient_item] += flt(ingredient.get("consumption_quantity")) / yield_quantity
			cost_rates[ingredient_item] = flt(ingredient.get("cost_price"))
	else:
		item_meta = frappe.db.get_value(
			"Ledgix Item",
			item,
			["track_inventory", "stock_uom", "cost_price"],
			as_dict=True,
		)
		if item_meta and cint(item_meta.track_inventory):
			consumption[item] += 1.0
			cost_rates[item] = flt(item_meta.cost_price)

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


def _copy_origin_snapshot(origin_order_item):
	if not origin_order_item:
		return []
	return [
		{
			"ingredient_item": row.ingredient_item,
			"stock_uom": row.stock_uom,
			"quantity_per_unit": flt(row.quantity_per_unit, 6),
			"cost_rate": flt(row.cost_rate, 6),
			"line_cost_per_unit": flt(row.line_cost_per_unit, 4),
		}
		for row in frappe.get_all(
			"Ledgix Restaurant Order Consumption",
			filters={"restaurant_order_item": origin_order_item},
			fields=["ingredient_item", "stock_uom", "quantity_per_unit", "cost_rate", "line_cost_per_unit"],
			order_by="creation asc",
			limit_page_length=0,
		)
	]


def persist_order_consumption_snapshot(order_item):
	if frappe.db.exists("Ledgix Restaurant Order Consumption", {"restaurant_order_item": order_item.name}):
		return

	# A quantity-split clone inherits the original line's historical stock truth
	# verbatim. Never reinterpret a split line using today's recipe/modifier master.
	rows = _copy_origin_snapshot(order_item.origin_order_item)
	if not rows:
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

	# Persisted consumption rows are the authoritative historical cost basis. This
	# gives direct-stock items a cost snapshot and includes modifier-linked stock.
	cost_per_unit = flt(sum(flt(row["line_cost_per_unit"]) for row in rows), 4)
	billable_quantity = flt(order_item.billable_quantity, 6)
	frappe.db.set_value(
		"Ledgix Restaurant Order Item",
		order_item.name,
		{
			"recipe_cost_per_unit": cost_per_unit,
			"estimated_cost": flt(cost_per_unit * billable_quantity, 4),
			"estimated_profit": flt(flt(order_item.amount) - (cost_per_unit * billable_quantity), 4),
		},
		update_modified=False,
	)
