from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item, make_supplier
from ledgix_saas.api.purchase_orders import create as create_purchase_order
from ledgix_saas.api.purchase_orders import receive as receive_purchase_order
from ledgix_saas.api.restaurant_inventory import record_waste, transfer_stock
from ledgix_saas.api.stock_ops import manual_stock_entry
from ledgix_saas.services.reorder import get_reorder_suggestions
from ledgix_saas.services.stock import get_location_stock, get_total_stock


class TestPhase7InventoryOperations(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.branch = "MAIN"
		self.main_location = frappe.db.get_value(
			"Ledgix Branch",
			self.branch,
			"default_stock_location",
		)
		self.assertTrue(self.main_location)

	def _uom(self, item):
		return frappe.db.get_value("Ledgix Item", item, "stock_uom") or "Piece"

	def _seed(self, item, quantity, stock_location=None):
		manual_stock_entry(
			item.name,
			qty_in=quantity,
			note="Phase 7 regression seed",
			branch=self.branch,
			stock_location=stock_location or self.main_location,
		)

	def _make_secondary_location(self):
		suffix = uuid4().hex[:8].upper()
		doc = frappe.get_doc({
			"doctype": "Ledgix Stock Location",
			"branch": self.branch,
			"location_code": f"T{suffix}",
			"location_name": f"Transfer Store {suffix}",
			"location_type": "Store",
			"is_active": 1,
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_transfer_is_atomic_location_movement_and_idempotent(self):
		item = make_item(cost_price=20, opening_stock=0)
		destination = self._make_secondary_location()
		self._seed(item, 10)
		client_transfer_id = f"TEST-XFER-{uuid4().hex[:12]}"
		payload = [{"item": item.name, "quantity": 3, "uom": self._uom(item.name)}]

		first = transfer_stock(
			source_stock_location=self.main_location,
			destination_stock_location=destination,
			items=payload,
			reason="Phase 7 transfer regression",
			client_transfer_id=client_transfer_id,
			source_branch=self.branch,
			destination_branch=self.branch,
		)
		second = transfer_stock(
			source_stock_location=self.main_location,
			destination_stock_location=destination,
			items=payload,
			reason="Phase 7 transfer regression",
			client_transfer_id=client_transfer_id,
			source_branch=self.branch,
			destination_branch=self.branch,
		)

		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(second["idempotent_replay"])
		self.assertEqual(second["name"], first["name"])
		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 7, places=6)
		self.assertAlmostEqual(get_location_stock(item.name, destination), 3, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 10, places=6)

		movements = frappe.get_all(
			"Ledgix Stock Movement",
			filters={"reference_doctype": "Ledgix Stock Transfer", "reference_name": first["name"], "docstatus": 1},
			fields=["movement_type", "movement_source", "stock_location", "quantity"],
			order_by="movement_type asc",
		)
		self.assertEqual(len(movements), 2)
		self.assertEqual({row.movement_type for row in movements}, {"IN", "OUT"})
		self.assertEqual({row.movement_source for row in movements}, {"Transfer IN", "Transfer OUT"})
		self.assertEqual({row.stock_location for row in movements}, {self.main_location, destination})

	def test_waste_posts_explicit_out_and_replay_does_not_double_consume(self):
		item = make_item(cost_price=18, opening_stock=0)
		self._seed(item, 6)
		client_waste_id = f"TEST-WASTE-{uuid4().hex[:12]}"
		payload = [{"item": item.name, "quantity": 2, "uom": self._uom(item.name)}]

		first = record_waste(
			stock_location=self.main_location,
			branch=self.branch,
			items=payload,
			waste_type="Spoilage",
			reason="Phase 7 waste regression",
			client_waste_id=client_waste_id,
		)
		second = record_waste(
			stock_location=self.main_location,
			branch=self.branch,
			items=payload,
			waste_type="Spoilage",
			reason="Phase 7 waste regression",
			client_waste_id=client_waste_id,
		)

		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(second["idempotent_replay"])
		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 4, places=6)
		movement = frappe.db.get_value(
			"Ledgix Stock Movement",
			{"reference_doctype": "Ledgix Inventory Waste", "reference_name": first["name"], "item": item.name, "docstatus": 1},
			["movement_type", "movement_source", "quantity"],
			as_dict=True,
		)
		self.assertEqual(movement.movement_type, "OUT")
		self.assertEqual(movement.movement_source, "Waste")
		self.assertAlmostEqual(movement.quantity, 2, places=6)

	def test_purchase_order_partial_receiving_updates_po_and_stock_ledger(self):
		item = make_item(cost_price=10, opening_stock=0)
		supplier = make_supplier()
		po = create_purchase_order(
			supplier=supplier.name,
			branch=self.branch,
			stock_location=self.main_location,
			items=[{"item": item.name, "quantity": 10, "uom": self._uom(item.name), "rate": 12}],
			client_purchase_order_id=f"TEST-PO-{uuid4().hex[:12]}",
		)
		self.assertEqual(po["status"], "Open")
		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 0, places=6)

		first_receipt_id = f"TEST-RCV-{uuid4().hex[:12]}"
		first = receive_purchase_order(
			purchase_order=po["name"],
			items=[{"item": item.name, "quantity": 4}],
			client_receipt_id=first_receipt_id,
		)
		first_replay = receive_purchase_order(
			purchase_order=po["name"],
			items=[{"item": item.name, "quantity": 4}],
			client_receipt_id=first_receipt_id,
		)
		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(first_replay["idempotent_replay"])
		self.assertEqual(first["purchase_order"]["status"], "Partially Received")
		self.assertAlmostEqual(first["purchase_order"]["received_percent"], 40, places=2)
		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 4, places=6)

		second = receive_purchase_order(
			purchase_order=po["name"],
			items=[{"item": item.name, "quantity": 6}],
			client_receipt_id=f"TEST-RCV-{uuid4().hex[:12]}",
		)
		self.assertEqual(second["purchase_order"]["status"], "Received")
		self.assertAlmostEqual(second["purchase_order"]["received_percent"], 100, places=2)
		self.assertAlmostEqual(get_location_stock(item.name, self.main_location), 10, places=6)
		self.assertAlmostEqual(get_total_stock(item.name), 10, places=6)
		self.assertEqual(
			frappe.db.count(
				"Ledgix Stock Movement",
				{"reference_doctype": "Ledgix Purchase", "item": item.name, "movement_type": "IN", "docstatus": 1},
			),
			2,
		)
		for purchase_name in (first["purchase"], second["purchase"]):
			self.assertEqual(
				frappe.db.get_value("Ledgix Purchase", purchase_name, "purchase_order"),
				po["name"],
			)

	def test_open_purchase_order_reduces_location_reorder_suggestion(self):
		item = make_item(cost_price=8, opening_stock=0)
		supplier = make_supplier()
		self._seed(item, 2)
		rule = frappe.get_doc({
			"doctype": "Ledgix Reorder Rule",
			"branch": self.branch,
			"stock_location": self.main_location,
			"item": item.name,
			"minimum_quantity": 5,
			"target_quantity": 10,
			"preferred_supplier": supplier.name,
			"lead_time_days": 2,
			"is_active": 1,
		})
		rule.insert(ignore_permissions=True)

		before = get_reorder_suggestions(self.branch, self.main_location)
		before_row = next(row for row in before["suggestions"] if row["item"] == item.name)
		self.assertAlmostEqual(before_row["suggested_order_quantity"], 8, places=6)

		create_purchase_order(
			supplier=supplier.name,
			branch=self.branch,
			stock_location=self.main_location,
			items=[{"item": item.name, "quantity": 3, "uom": self._uom(item.name), "rate": 8}],
			client_purchase_order_id=f"TEST-PO-{uuid4().hex[:12]}",
		)
		after = get_reorder_suggestions(self.branch, self.main_location)
		after_row = next(row for row in after["suggestions"] if row["item"] == item.name)
		self.assertAlmostEqual(after_row["on_purchase_order"], 3, places=6)
		self.assertAlmostEqual(after_row["suggested_order_quantity"], 5, places=6)
