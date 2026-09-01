from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item


class TestModifierStockEffect(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()

	def test_add_linked_item_requires_valid_item_uom_conversion(self):
		suffix = uuid4().hex[:8].upper()
		ingredient = make_item(cost_price=1, opening_stock=0)
		ingredient.restaurant_item_type = "Ingredient"
		ingredient.is_sellable = 0
		ingredient.stock_uom = "Gram"
		ingredient.append("uom_conversions", {
			"uom": "Kilogram",
			"conversion_factor": 1000,
			"is_recipe_uom": 1,
		})
		ingredient.save(ignore_permissions=True)

		group = frappe.new_doc("Ledgix Modifier Group")
		group.modifier_group_code = f"EXTRA_{suffix}"
		group.modifier_group_name = f"Extras {suffix}"
		group.selection_type = "Multiple"
		group.min_selection = 0
		group.max_selection = 3
		group.is_active = 1
		group.insert(ignore_permissions=True)

		option = frappe.new_doc("Ledgix Modifier Option")
		option.modifier_group = group.name
		option.option_code = "EXTRA_INGREDIENT"
		option.option_name = "Extra Ingredient"
		option.stock_effect = "Add Linked Item"
		option.linked_item = ingredient.name
		option.stock_quantity = 0.05
		option.uom = "Kilogram"
		option.insert(ignore_permissions=True)

		self.assertEqual(option.linked_item, ingredient.name)
		self.assertEqual(option.uom, "Kilogram")

	def test_stock_effect_without_linked_item_is_rejected(self):
		suffix = uuid4().hex[:8].upper()
		group = frappe.new_doc("Ledgix Modifier Group")
		group.modifier_group_code = f"REQ_{suffix}"
		group.modifier_group_name = f"Required {suffix}"
		group.selection_type = "Single"
		group.min_selection = 0
		group.max_selection = 1
		group.is_active = 1
		group.insert(ignore_permissions=True)

		option = frappe.new_doc("Ledgix Modifier Option")
		option.modifier_group = group.name
		option.option_code = "BAD"
		option.option_name = "Bad Stock Option"
		option.stock_effect = "Add Linked Item"
		option.stock_quantity = 1
		with self.assertRaises(frappe.ValidationError):
			option.insert(ignore_permissions=True)
