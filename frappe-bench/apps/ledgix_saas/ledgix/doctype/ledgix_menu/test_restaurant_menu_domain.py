from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.services.menu import build_menu_catalog


class TestRestaurantMenuDomain(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()
		self.branch = "MAIN"
		self.price_list = self._make_price_list(f"MENU PRICE {self.suffix}")

	def _make_price_list(self, name):
		doc = frappe.new_doc("Ledgix Price List")
		doc.price_list_name = name
		doc.currency = "PKR"
		doc.enabled = 1
		doc.is_default = 0
		doc.priority = 50
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_menu_item(self, rate=850):
		item = make_item(cost_price=200, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 0
		item.save(ignore_permissions=True)

		price = frappe.new_doc("Ledgix Item Price")
		price.item = item.name
		price.price_list = self.price_list
		price.rate = rate
		price.enabled = 1
		price.insert(ignore_permissions=True)

		menu = frappe.new_doc("Ledgix Menu")
		menu.menu_code = f"MENU_{self.suffix}"
		menu.menu_name = f"Restaurant Menu {self.suffix}"
		menu.restaurant_brand = "DEFAULT"
		menu.default_price_list = self.price_list
		menu.available_dine_in = 1
		menu.available_takeaway = 1
		menu.available_delivery = 1
		menu.is_active = 1
		menu.insert(ignore_permissions=True)

		section = frappe.new_doc("Ledgix Menu Section")
		section.menu = menu.name
		section.section_code = "MAINS"
		section.section_name = "Mains"
		section.sort_order = 10
		section.is_active = 1
		section.insert(ignore_permissions=True)

		group = frappe.new_doc("Ledgix Modifier Group")
		group.modifier_group_code = f"SPICE_{self.suffix}"
		group.modifier_group_name = "Spice Level"
		group.selection_type = "Single"
		group.min_selection = 1
		group.max_selection = 1
		group.is_active = 1
		group.insert(ignore_permissions=True)

		option = frappe.new_doc("Ledgix Modifier Option")
		option.modifier_group = group.name
		option.option_code = "HOT"
		option.option_name = "Hot"
		option.kitchen_label = "HOT"
		option.price_delta = 0
		option.stock_effect = "None"
		option.is_active = 1
		option.insert(ignore_permissions=True)

		menu_item = frappe.new_doc("Ledgix Menu Item")
		menu_item.menu = menu.name
		menu_item.menu_section = section.name
		menu_item.item = item.name
		menu_item.display_name = "Signature Dish"
		menu_item.is_active = 1
		menu_item.available_dine_in = 1
		menu_item.available_takeaway = 1
		menu_item.available_delivery = 1
		menu_item.append("modifier_groups", {
			"modifier_group": group.name,
			"required_override": "Use Group Rule",
			"min_selection_override": -1,
			"max_selection_override": -1,
			"sort_order": 10,
		})
		menu_item.insert(ignore_permissions=True)

		assignment = frappe.new_doc("Ledgix Branch Menu")
		assignment.branch = self.branch
		assignment.menu = menu.name
		assignment.price_list_override = self.price_list
		assignment.priority = 10
		assignment.is_active = 1
		assignment.insert(ignore_permissions=True)

		return item, menu, menu_item, group

	def test_catalog_resolves_branch_price_and_modifier_rules(self):
		item, menu, _menu_item, group = self._make_menu_item(rate=850)
		catalog = build_menu_catalog(branch=self.branch, channel="Dine In", menu=menu.name)

		self.assertEqual(catalog["branch"], self.branch)
		self.assertEqual(catalog["menu"]["price_list"], self.price_list)
		self.assertEqual(len(catalog["items"]), 1)
		row = catalog["items"][0]
		self.assertEqual(row["item"], item.name)
		self.assertEqual(row["display_name"], "Signature Dish")
		self.assertAlmostEqual(row["rate"], 850, places=2)
		self.assertTrue(row["available"])
		self.assertEqual(row["modifier_groups"][0]["modifier_group"], group.name)
		self.assertEqual(row["modifier_groups"][0]["min_selection"], 1)
		self.assertEqual(row["modifier_groups"][0]["max_selection"], 1)
		self.assertEqual(row["modifier_groups"][0]["options"][0]["name"], "Hot")

	def test_86_state_applies_across_menu_catalog(self):
		item, menu, _menu_item, _group = self._make_menu_item(rate=500)
		availability = frappe.new_doc("Ledgix Item Availability")
		availability.branch = self.branch
		availability.item = item.name
		availability.status = "86d"
		availability.reason = "Sold out after lunch service"
		availability.insert(ignore_permissions=True)

		catalog = build_menu_catalog(branch=self.branch, channel="Takeaway", menu=menu.name)
		row = catalog["items"][0]
		self.assertFalse(row["available"])
		self.assertEqual(row["availability_status"], "86d")
		self.assertEqual(row["unavailable_reason"], "Sold out after lunch service")
