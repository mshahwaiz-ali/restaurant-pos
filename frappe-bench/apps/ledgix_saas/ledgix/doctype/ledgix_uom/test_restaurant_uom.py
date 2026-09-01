from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.api.stock_ops import manual_stock_entry
from ledgix_saas.services.uom import from_stock_qty, to_stock_qty


class TestRestaurantUOM(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()

	def test_item_specific_uom_conversion_normalizes_to_stock_uom(self):
		item = make_item(cost_price=0, opening_stock=0)
		item.stock_uom = "Gram"
		item.set("uom_conversions", [])
		item.append("uom_conversions", {
			"uom": "Kilogram",
			"conversion_factor": 1000,
			"is_purchase_uom": 1,
			"is_recipe_uom": 1,
		})
		item.save(ignore_permissions=True)

		self.assertAlmostEqual(to_stock_qty(item.name, 2.5, "Kilogram"), 2500, places=6)
		self.assertAlmostEqual(from_stock_qty(item.name, 2500, "Kilogram"), 2.5, places=6)

	def test_stock_uom_change_is_blocked_after_inventory_history_exists(self):
		item = make_item(cost_price=10, opening_stock=0)
		item.stock_uom = "Piece"
		item.save(ignore_permissions=True)

		manual_stock_entry(
			item.name,
			qty_in=5,
			note="UOM immutability test",
			branch="MAIN",
		)

		item.reload()
		item.stock_uom = "Pack"
		with self.assertRaises(frappe.ValidationError):
			item.save(ignore_permissions=True)
