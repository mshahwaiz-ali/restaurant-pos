from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.services.menu import build_menu_catalog


class TestBranchMenuPricing(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()

	def _price_list(self, label, priority):
		doc = frappe.new_doc("Ledgix Price List")
		doc.price_list_name = f"{label} {self.suffix}"
		doc.currency = "PKR"
		doc.enabled = 1
		doc.is_default = 0
		doc.priority = priority
		doc.insert(ignore_permissions=True)
		return doc.name

	def _item_price(self, item, price_list, rate):
		doc = frappe.new_doc("Ledgix Item Price")
		doc.item = item
		doc.price_list = price_list
		doc.rate = rate
		doc.enabled = 1
		doc.insert(ignore_permissions=True)

	def test_branch_assignment_overrides_shared_menu_price_list(self):
		default_price_list = self._price_list("CHAIN DEFAULT", 40)
		branch_price_list = self._price_list("MAIN BRANCH", 30)
		item = make_item(cost_price=150, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 0
		item.save(ignore_permissions=True)
		self._item_price(item.name, default_price_list, 700)
		self._item_price(item.name, branch_price_list, 825)

		menu = frappe.new_doc("Ledgix Menu")
		menu.menu_code = f"SHARED_{self.suffix}"
		menu.menu_name = f"Shared Menu {self.suffix}"
		menu.restaurant_brand = "DEFAULT"
		menu.default_price_list = default_price_list
		menu.available_dine_in = 1
		menu.available_takeaway = 1
		menu.available_delivery = 1
		menu.is_active = 1
		menu.insert(ignore_permissions=True)

		section = frappe.new_doc("Ledgix Menu Section")
		section.menu = menu.name
		section.section_code = "MAIN"
		section.section_name = "Main"
		section.is_active = 1
		section.insert(ignore_permissions=True)

		menu_item = frappe.new_doc("Ledgix Menu Item")
		menu_item.menu = menu.name
		menu_item.menu_section = section.name
		menu_item.item = item.name
		menu_item.is_active = 1
		menu_item.available_dine_in = 1
		menu_item.available_takeaway = 1
		menu_item.available_delivery = 1
		menu_item.insert(ignore_permissions=True)

		assignment = frappe.new_doc("Ledgix Branch Menu")
		assignment.branch = "MAIN"
		assignment.menu = menu.name
		assignment.price_list_override = branch_price_list
		assignment.priority = 10
		assignment.is_active = 1
		assignment.insert(ignore_permissions=True)

		catalog = build_menu_catalog(branch="MAIN", channel="Dine In", menu=menu.name)
		self.assertEqual(catalog["menu"]["price_list"], branch_price_list)
		self.assertAlmostEqual(catalog["items"][0]["rate"], 825, places=2)
