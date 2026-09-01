from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cint, flt, getdate, nowdate

from ledgix_saas.services.uom import to_stock_qty


def get_active_recipe(item, transaction_date=None):
	transaction_date = getdate(transaction_date or nowdate())
	rows = frappe.get_all(
		"Ledgix Recipe",
		filters={"finished_item": item, "is_active": 1},
		fields=["name", "effective_from", "effective_to", "recipe_version"],
		order_by="recipe_version desc, modified desc",
		limit_page_length=0,
	)
	matches = []
	for row in rows:
		if row.effective_from and transaction_date < getdate(row.effective_from):
			continue
		if row.effective_to and transaction_date > getdate(row.effective_to):
			continue
		matches.append(row)
	if not matches:
		return None
	if len(matches) > 1:
		frappe.throw(
			f"More than one active Recipe matches item {item} on {transaction_date}. Resolve recipe effective dates before continuing."
		)
	return frappe.get_doc("Ledgix Recipe", matches[0].name)


def build_recipe_snapshot(item=None, recipe=None, transaction_date=None):
	if recipe:
		recipe_doc = frappe.get_doc("Ledgix Recipe", recipe)
	else:
		recipe_doc = get_active_recipe(item, transaction_date)
	if not recipe_doc:
		return None

	ingredients = []
	for row in recipe_doc.ingredients:
		cost_price = flt(frappe.db.get_value("Ledgix Item", row.ingredient_item, "cost_price"))
		ingredients.append({
			"ingredient_item": row.ingredient_item,
			"recipe_quantity": flt(row.quantity),
			"uom": row.uom,
			"stock_quantity": flt(row.stock_quantity),
			"waste_percent": flt(row.waste_percent),
			"consumption_quantity": flt(row.consumption_quantity),
			"consume_stock": cint(row.consume_stock),
			"cost_price": cost_price,
			"ingredient_cost": flt(row.ingredient_cost),
		})

	return {
		"recipe": recipe_doc.name,
		"recipe_version": cint(recipe_doc.recipe_version),
		"finished_item": recipe_doc.finished_item,
		"recipe_name": recipe_doc.recipe_name,
		"effective_from": recipe_doc.effective_from,
		"effective_to": recipe_doc.effective_to,
		"yield_quantity": flt(recipe_doc.yield_quantity),
		"output_uom": recipe_doc.output_uom,
		"ingredient_cost": flt(recipe_doc.ingredient_cost),
		"cost_per_serving": flt(recipe_doc.cost_per_serving),
		"costed_at": recipe_doc.costed_at,
		"ingredients": ingredients,
	}


def build_consumption_plan(item, order_quantity=1, modifier_options=None, transaction_date=None):
	"""Build, but do not post, the stock plan for a fired restaurant item.

	Quantities are returned in each ingredient's canonical Stock UOM. The caller
	must snapshot this plan on the operational order/KOT before posting movements;
	that later snapshot is what makes kitchen fire idempotent and historically
	stable even if recipe masters change after the ticket was fired.
	"""
	order_quantity = flt(order_quantity)
	if order_quantity <= 0:
		frappe.throw("Order quantity must be greater than zero.")

	snapshot = build_recipe_snapshot(item=item, transaction_date=transaction_date)
	if not snapshot:
		return {
			"recipe": None,
			"finished_item": item,
			"order_quantity": order_quantity,
			"ingredients": [],
			"total_cost": 0,
		}

	yield_quantity = flt(snapshot["yield_quantity"])
	if yield_quantity <= 0:
		frappe.throw(f"Recipe {snapshot['recipe']} has invalid yield quantity.")
	multiplier = order_quantity / yield_quantity
	consumption = defaultdict(float)
	cost_rates = {}
	excluded = set()

	selected = _normalize_modifier_options(modifier_options)
	for selected_row in selected:
		option = frappe.db.get_value(
			"Ledgix Modifier Option",
			{"name": selected_row["modifier_option"], "is_active": 1},
			[
				"stock_effect",
				"linked_item",
				"stock_quantity",
				"uom",
			],
			as_dict=True,
		)
		if not option:
			frappe.throw(f"Modifier Option {selected_row['modifier_option']} is inactive or missing.")
		if option.stock_effect == "Exclude Recipe Ingredient" and option.linked_item:
			excluded.add(option.linked_item)
		elif option.stock_effect == "Add Linked Item" and option.linked_item:
			stock_qty = to_stock_qty(option.linked_item, flt(option.stock_quantity), option.uom)
			consumption[option.linked_item] += stock_qty * order_quantity * flt(selected_row["quantity"])
			cost_rates[option.linked_item] = flt(frappe.db.get_value("Ledgix Item", option.linked_item, "cost_price"))

	for ingredient in snapshot["ingredients"]:
		if not cint(ingredient["consume_stock"]):
			continue
		if ingredient["ingredient_item"] in excluded:
			continue
		consumption[ingredient["ingredient_item"]] += flt(ingredient["consumption_quantity"]) * multiplier
		cost_rates[ingredient["ingredient_item"]] = flt(ingredient["cost_price"])

	rows = []
	total_cost = 0.0
	for ingredient_item in sorted(consumption):
		quantity = flt(consumption[ingredient_item], 6)
		if quantity <= 0:
			continue
		cost_rate = flt(cost_rates.get(ingredient_item))
		line_cost = flt(quantity * cost_rate, 4)
		total_cost += line_cost
		rows.append({
			"ingredient_item": ingredient_item,
			"stock_uom": frappe.db.get_value("Ledgix Item", ingredient_item, "stock_uom"),
			"stock_quantity": quantity,
			"cost_rate": cost_rate,
			"line_cost": line_cost,
		})

	return {
		"recipe": snapshot["recipe"],
		"recipe_version": snapshot["recipe_version"],
		"finished_item": item,
		"order_quantity": order_quantity,
		"yield_quantity": yield_quantity,
		"cost_per_serving_snapshot": flt(snapshot["cost_per_serving"]),
		"ingredients": rows,
		"total_cost": flt(total_cost, 4),
		"selected_modifiers": selected,
	}


def _normalize_modifier_options(modifier_options):
	rows = frappe.parse_json(modifier_options) if isinstance(modifier_options, str) else (modifier_options or [])
	normalized = []
	for row in rows:
		if isinstance(row, str):
			name = row
			quantity = 1
		else:
			name = row.get("modifier_option") or row.get("option") or row.get("name")
			quantity = flt(row.get("quantity") or 1)
		if not name or quantity <= 0:
			continue
		normalized.append({"modifier_option": name, "quantity": quantity})
	return normalized


def recipe_margin(recipe=None, item=None, selling_rate=None, transaction_date=None):
	snapshot = build_recipe_snapshot(item=item, recipe=recipe, transaction_date=transaction_date)
	if not snapshot:
		return None
	selling_rate = flt(selling_rate)
	cost = flt(snapshot["cost_per_serving"])
	margin = selling_rate - cost
	return {
		**snapshot,
		"selling_rate": selling_rate,
		"contribution_margin": flt(margin, 4),
		"food_cost_percent": flt((cost / selling_rate * 100) if selling_rate else 0, 2),
		"gross_margin_percent": flt((margin / selling_rate * 100) if selling_rate else 0, 2),
	}
