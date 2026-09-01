from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.services.recipe import build_consumption_plan, build_recipe_snapshot


class TestRecipeCosting(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()

	def _ingredient(self, cost_per_gram):
		item = make_item(cost_price=cost_per_gram, opening_stock=0)
		item.restaurant_item_type = "Ingredient"
		item.is_sellable = 0
		item.track_inventory = 1
		item.stock_uom = "Gram"
		item.set("uom_conversions", [])
		item.append("uom_conversions", {
			"uom": "Kilogram",
			"conversion_factor": 1000,
			"is_recipe_uom": 1,
		})
		item.save(ignore_permissions=True)
		return item

	def _finished_item(self):
		item = make_item(cost_price=0, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 0
		item.stock_uom = "Portion"
		item.save(ignore_permissions=True)
		return item

	def test_recipe_cost_normalizes_uom_applies_waste_and_scales_yield(self):
		flour = self._ingredient(0.20)
		sauce = self._ingredient(0.50)
		finished = self._finished_item()

		recipe = frappe.new_doc("Ledgix Recipe")
		recipe.finished_item = finished.name
		recipe.recipe_version = 1
		recipe.recipe_name = f"Batch {self.suffix}"
		recipe.yield_quantity = 2
		recipe.output_uom = "Portion"
		recipe.is_active = 1
		recipe.append("ingredients", {
			"ingredient_item": flour.name,
			"quantity": 0.5,
			"uom": "Kilogram",
			"waste_percent": 10,
			"consume_stock": 1,
		})
		recipe.append("ingredients", {
			"ingredient_item": sauce.name,
			"quantity": 200,
			"uom": "Gram",
			"waste_percent": 0,
			"consume_stock": 1,
		})
		recipe.insert(ignore_permissions=True)

		# Flour: 500g * 1.10 * 0.20 = 110; Sauce: 200g * 0.50 = 100.
		self.assertAlmostEqual(recipe.ingredient_cost, 210, places=4)
		self.assertAlmostEqual(recipe.cost_per_serving, 105, places=4)
		self.assertAlmostEqual(recipe.ingredients[0].stock_quantity, 500, places=6)
		self.assertAlmostEqual(recipe.ingredients[0].consumption_quantity, 550, places=6)

		snapshot = build_recipe_snapshot(item=finished.name)
		self.assertEqual(snapshot["recipe"], recipe.name)
		self.assertAlmostEqual(snapshot["cost_per_serving"], 105, places=4)

		plan = build_consumption_plan(finished.name, order_quantity=1)
		by_item = {row["ingredient_item"]: row for row in plan["ingredients"]}
		self.assertAlmostEqual(by_item[flour.name]["stock_quantity"], 275, places=6)
		self.assertAlmostEqual(by_item[sauce.name]["stock_quantity"], 100, places=6)
		self.assertAlmostEqual(plan["total_cost"], 105, places=4)
