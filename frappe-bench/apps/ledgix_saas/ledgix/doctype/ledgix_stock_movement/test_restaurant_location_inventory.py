from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.api.stock_ops import manual_stock_entry
from ledgix_saas.services.stock import _post_movement, get_location_stock, get_total_stock


class TestRestaurantLocationInventory(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.main_branch = "MAIN"
		self.main_location = frappe.db.get_value(
			"Ledgix Branch",
			self.main_branch,
			"default_stock_location",
		)
		self.assertTrue(self.main_location)
		self.other_branch, self.other_location = self._make_branch_location()

	def _make_branch_location(self):
		suffix = uuid4().hex[:8].upper()
		branch_code = f"TBR_{suffix}"
		branch = frappe.get_doc(
			{
				"doctype": "Ledgix Branch",
				"restaurant_brand": "DEFAULT",
				"branch_code": branch_code,
				"branch_name": f"Test Branch {suffix}",
				"is_active": 1,
			}
		)
		branch.insert(ignore_permissions=True)

		location = frappe.get_doc(
			{
				"doctype": "Ledgix Stock Location",
				"branch": branch.name,
				"location_code": "MAIN",
				"location_name": "Main Store",
				"location_type": "Store",
				"is_active": 1,
				"is_default_receiving": 1,
				"is_default_consumption": 1,
			}
		)
		location.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Ledgix Branch",
			branch.name,
			"default_stock_location",
			location.name,
			update_modified=False,
		)
		return branch.name, location.name

	def test_same_item_has_independent_location_balances_and_aggregate_cache(self):
		item = make_item(cost_price=40, opening_stock=0)

		manual_stock_entry(
			item.name,
			qty_in=5,
			note="Main branch seed",
			branch=self.main_branch,
			stock_location=self.main_location,
		)
		manual_stock_entry(
			item.name,
			qty_in=7,
			note="Second branch seed",
			branch=self.other_branch,
			stock_location=self.other_location,
		)

		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 5, places=6)
		self.assertAlmostEqual(get_location_stock(item.name, self.other_location), 7, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 12, places=6)
		self.assertAlmostEqual(
			frappe.db.get_value("Ledgix Item", item.name, "current_stock"),
			12,
			places=6,
		)

	def test_out_cannot_borrow_stock_from_another_location(self):
		item = make_item(cost_price=30, opening_stock=0)
		manual_stock_entry(
			item.name,
			qty_in=2,
			note="Main branch seed",
			branch=self.main_branch,
			stock_location=self.main_location,
		)
		manual_stock_entry(
			item.name,
			qty_in=10,
			note="Other branch seed",
			branch=self.other_branch,
			stock_location=self.other_location,
		)

		with self.assertRaises(frappe.ValidationError):
			manual_stock_entry(
				item.name,
				qty_out=3,
				note="Must fail locally",
				branch=self.main_branch,
				stock_location=self.main_location,
			)

		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 2, places=6)
		self.assertAlmostEqual(get_location_stock(item.name, self.other_location), 10, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 12, places=6)

	def test_transaction_movement_identity_includes_stock_location(self):
		item = make_item(cost_price=25, opening_stock=0)
		reference_name = f"TEST-LOCATION-IDEMPOTENCY-{uuid4().hex[:10]}"

		first = _post_movement(
			item=item.name,
			quantity=2,
			movement_type="IN",
			reference_doctype="Ledgix Item",
			reference_name=reference_name,
			source="Manual IN",
			branch=self.main_branch,
			stock_location=self.main_location,
			rate=25,
		)
		first_retry = _post_movement(
			item=item.name,
			quantity=2,
			movement_type="IN",
			reference_doctype="Ledgix Item",
			reference_name=reference_name,
			source="Manual IN",
			branch=self.main_branch,
			stock_location=self.main_location,
			rate=25,
		)
		second_location = _post_movement(
			item=item.name,
			quantity=3,
			movement_type="IN",
			reference_doctype="Ledgix Item",
			reference_name=reference_name,
			source="Manual IN",
			branch=self.other_branch,
			stock_location=self.other_location,
			rate=25,
		)

		self.assertEqual(first_retry, first)
		self.assertNotEqual(second_location, first)
		self.assertEqual(
			frappe.db.count(
				"Ledgix Stock Movement",
				{
					"reference_doctype": "Ledgix Item",
					"reference_name": reference_name,
					"item": item.name,
					"docstatus": 1,
				},
			),
			2,
		)
		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 2, places=6)
		self.assertAlmostEqual(get_location_stock(item.name, self.other_location), 3, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 5, places=6)
