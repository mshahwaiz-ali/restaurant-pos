from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.services.recipe import build_consumption_plan


class TestRecipeModifierConsumption(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()

	def _gram_item(self, cost, restaurant_item_type="Ingredient", sellable=0):
		item = make_item(cost_price=cost, opening_stock=0)
		item.restaurant_item_type = restaurant_item_type
		item.is_sellable = sellable
		item.track_inventory = 1
		item.stock_uom = "Gram"
		item.save(ignore_permissions=True)
		return item

	def test_modifier_can_add_and_exclude_recipe_ingredients(self):
		base = self._gram_item(1)
		extra = self._gram_item(2)
		finished = make_item(cost_price=0, opening_stock=0)
		finished.restaurant_item_type = "Menu Item"
		finished.is_sellable = 1
		finished.track_inventory = 0
		finished.stock_uom = "Portion"
		finished.save(ignore_permissions=True)

		recipe = frappe.new_doc("Ledgix Recipe")
		recipe.finished_item = finished.name
		recipe.recipe_version = 1
		recipe.yield_quantity = 1
		recipe.output_uom = "Portion"
		recipe.is_active = 1
		recipe.append("ingredients", {
			"ingredient_item": base.name,
			"quantity": 100,
			"uom": "Gram",
			"waste_percent": 0,
			"consume_stock": 1,
		})
		recipe.insert(ignore_permissions=True)

		group = frappe.new_doc("Ledgix Modifier Group")
		group.modifier_group_code = f"MOD_{self.suffix}"
		group.modifier_group_name = f"Modifiers {self.suffix}"
		group.selection_type = "Multiple"
		group.min_selection = 0
		group.max_selection = 2
		group.is_active = 1
		group.insert(ignore_permissions=True)

		add = frappe.new_doc("Ledgix Modifier Option")
		add.modifier_group = group.name
		add.option_code = "EXTRA"
		add.option_name = "Extra"
		add.stock_effect = "Add Linked Item"
		add.linked_item = extra.name
		add.stock_quantity = 25
		add.uom = "Gram"
		add.is_active = 1
		add.insert(ignore_permissions=True)

		exclude = frappe.new_doc("Ledgix Modifier Option")
		exclude.modifier_group = group.name
		exclude.option_code = "NO_BASE"
		exclude.option_name = "No Base"
		exclude.stock_effect = "Exclude Recipe Ingredient"
		exclude.linked_item = base.name
		exclude.is_active = 1
		exclude.insert(ignore_permissions=True)

		plan = build_consumption_plan(
			finished.name,
			order_quantity=2,
			modifier_options=[add.name],
		)
		by_item = {row["ingredient_item"]: row for row in plan["ingredients"]}
		self.assertAlmostEqual(by_item[base.name]["stock_quantity"], 200, places=6)
		self.assertAlmostEqual(by_item[extra.name]["stock_quantity"], 50, places=6)

		excluded_plan = build_consumption_plan(
			finished.name,
			order_quantity=1,
			modifier_options=[exclude.name],
		)
		self.assertEqual(excluded_plan["ingredients"], [])
