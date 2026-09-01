from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item


class TestRecipeVersions(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()

	def _ingredient(self):
		item = make_item(cost_price=1, opening_stock=0)
		item.restaurant_item_type = "Ingredient"
		item.is_sellable = 0
		item.stock_uom = "Gram"
		item.save(ignore_permissions=True)
		return item

	def _finished(self):
		item = make_item(cost_price=0, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 0
		item.stock_uom = "Portion"
		item.save(ignore_permissions=True)
		return item

	def _recipe(self, finished, ingredient, version, start, end):
		recipe = frappe.new_doc("Ledgix Recipe")
		recipe.finished_item = finished.name
		recipe.recipe_version = version
		recipe.recipe_name = f"Version {version} {self.suffix}"
		recipe.effective_from = start
		recipe.effective_to = end
		recipe.yield_quantity = 1
		recipe.output_uom = "Portion"
		recipe.is_active = 1
		recipe.append("ingredients", {
			"ingredient_item": ingredient.name,
			"quantity": 100,
			"uom": "Gram",
			"waste_percent": 0,
			"consume_stock": 1,
		})
		return recipe

	def test_active_recipe_effective_ranges_cannot_overlap(self):
		ingredient = self._ingredient()
		finished = self._finished()
		first = self._recipe(finished, ingredient, 1, "2026-01-01", "2026-06-30")
		first.insert(ignore_permissions=True)

		overlap = self._recipe(finished, ingredient, 2, "2026-06-01", "2026-12-31")
		with self.assertRaises(frappe.ValidationError):
			overlap.insert(ignore_permissions=True)

		next_version = self._recipe(finished, ingredient, 2, "2026-07-01", None)
		next_version.insert(ignore_permissions=True)
		self.assertEqual(next_version.recipe_version, 2)
