from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.api.restaurant_inventory import record_stock_count
from ledgix_saas.api.stock_ops import manual_stock_entry
from ledgix_saas.services.restaurant_inventory import get_stock_count_sheet
from ledgix_saas.services.stock import get_location_stock, get_total_stock


class TestLedgixStockCount(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.branch = "MAIN"
		self.stock_location = frappe.db.get_value(
			"Ledgix Branch",
			self.branch,
			"default_stock_location",
		)
		self.assertTrue(self.stock_location)

	def _seed(self, item, quantity):
		manual_stock_entry(
			item.name,
			qty_in=quantity,
			note="Stock count test seed",
			branch=self.branch,
			stock_location=self.stock_location,
		)

	def _count(self, item, counted_quantity, client_count_id=None):
		return record_stock_count(
			stock_location=self.stock_location,
			branch=self.branch,
			items=[{
				"item": item.name,
				"counted_quantity": counted_quantity,
				"uom": item.stock_uom or "Piece",
			}],
			client_count_id=client_count_id or f"TEST-COUNT-{uuid4().hex[:12]}",
			count_type="Cycle Count",
			notes="Regression count",
		)

	def test_count_posts_one_adjustment_and_freezes_real_variance(self):
		item = make_item(cost_price=25, opening_stock=0)
		self._seed(item, 10)

		result = self._count(item, 7)

		self.assertFalse(result["idempotent_replay"])
		self.assertEqual(result["docstatus"], 1)
		self.assertEqual(result["status"], "Submitted")
		self.assertAlmostEqual(result["items"][0]["expected_quantity"], 10, places=6)
		self.assertAlmostEqual(result["items"][0]["counted_stock_quantity"], 7, places=6)
		self.assertAlmostEqual(result["items"][0]["variance_quantity"], -3, places=6)
		self.assertAlmostEqual(result["total_absolute_variance_quantity"], 3, places=6)
		self.assertAlmostEqual(result["total_variance_value"], -75, places=4)
		self.assertAlmostEqual(get_location_stock(item.name, self.stock_location), 7, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 7, places=6)

		movement = frappe.db.get_value(
			"Ledgix Stock Movement",
			{
				"reference_doctype": "Ledgix Stock Count",
				"reference_name": result["name"],
				"item": item.name,
				"stock_location": self.stock_location,
				"movement_type": "ADJUSTMENT",
				"docstatus": 1,
			},
			["name", "quantity", "previous_quantity", "movement_source"],
			as_dict=True,
		)
		self.assertTrue(movement)
		self.assertAlmostEqual(movement.quantity, 7, places=6)
		self.assertAlmostEqual(movement.previous_quantity, 10, places=6)
		self.assertEqual(movement.movement_source, "Stock Count")

	def test_physical_count_can_adjust_location_to_zero(self):
		item = make_item(cost_price=12, opening_stock=0)
		self._seed(item, 4)

		result = self._count(item, 0)

		self.assertAlmostEqual(result["items"][0]["expected_quantity"], 4, places=6)
		self.assertAlmostEqual(result["items"][0]["variance_quantity"], -4, places=6)
		self.assertAlmostEqual(get_location_stock(item.name, self.stock_location), 0, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 0, places=6)

		movement = frappe.db.get_value(
			"Ledgix Stock Movement",
			{"reference_doctype": "Ledgix Stock Count", "reference_name": result["name"], "item": item.name},
			["quantity", "previous_quantity", "docstatus"],
			as_dict=True,
		)
		self.assertEqual(movement.docstatus, 1)
		self.assertAlmostEqual(movement.quantity, 0, places=6)
		self.assertAlmostEqual(movement.previous_quantity, 4, places=6)

	def test_stock_count_api_is_idempotent(self):
		item = make_item(cost_price=15, opening_stock=0)
		self._seed(item, 8)
		client_count_id = f"TEST-COUNT-{uuid4().hex[:12]}"

		first = self._count(item, 6, client_count_id=client_count_id)
		second = self._count(item, 6, client_count_id=client_count_id)

		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(second["idempotent_replay"])
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(
			frappe.db.count(
				"Ledgix Stock Movement",
				{
					"reference_doctype": "Ledgix Stock Count",
					"reference_name": first["name"],
					"item": item.name,
					"docstatus": 1,
				},
			),
			1,
		)
		self.assertAlmostEqual(get_location_stock(item.name, self.stock_location), 6, places=6)

	def test_count_sheet_reports_expected_stock_and_separates_tracked_items(self):
		countable_item = make_item(cost_price=9, opening_stock=0)
		tracked_item = make_item(cost_price=11, opening_stock=0)
		self._seed(countable_item, 5)
		frappe.db.set_value("Ledgix Item", tracked_item.name, "tracking_type", "Lot Based")

		sheet = get_stock_count_sheet(
			branch=self.branch,
			stock_location=self.stock_location,
			query="TEST-ITEM",
		)
		countable = {row["item"]: row for row in sheet["items"]}
		unsupported = {row["item"]: row for row in sheet["unsupported_items"]}

		self.assertIn(countable_item.name, countable)
		self.assertAlmostEqual(countable[countable_item.name]["expected_quantity"], 5, places=6)
		self.assertIn(tracked_item.name, unsupported)
		self.assertIn("identity", unsupported[tracked_item.name]["reason"].lower())

		with self.assertRaises(frappe.ValidationError):
			self._count(tracked_item, 0)
