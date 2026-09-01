from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.services.restaurant_audit import log_restaurant_operation
from ledgix_saas.services.restaurant_order_splits import split_check_by_items
from ledgix_saas.services.restaurant_orders import (
	add_order_item,
	get_order_payload,
	open_restaurant_order,
	open_table_session,
	transfer_table,
	update_order_item,
	void_order_item,
)


class TestRestaurantOrderPhase4(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()
		self.branch = "MAIN"
		self.price_list = self._make_price_list()
		self.menu, self.menu_item = self._make_menu_item()
		self.floor = self._make_floor()
		self.table = self._make_table("T1")
		self.other_table = self._make_table("T2")

	def _make_price_list(self):
		doc = frappe.new_doc("Ledgix Price List")
		doc.price_list_name = f"ORDER PRICE {self.suffix}"
		doc.currency = "PKR"
		doc.enabled = 1
		doc.is_default = 0
		doc.priority = 50
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_menu_item(self):
		item = make_item(cost_price=120, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 0
		item.save(ignore_permissions=True)

		price = frappe.new_doc("Ledgix Item Price")
		price.item = item.name
		price.price_list = self.price_list
		price.rate = 750
		price.enabled = 1
		price.insert(ignore_permissions=True)

		menu = frappe.new_doc("Ledgix Menu")
		menu.menu_code = f"ORDER_{self.suffix}"
		menu.menu_name = f"Order Menu {self.suffix}"
		menu.restaurant_brand = "DEFAULT"
		menu.default_price_list = self.price_list
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
		menu_item.display_name = f"Dish {self.suffix}"
		menu_item.is_active = 1
		menu_item.available_dine_in = 1
		menu_item.available_takeaway = 1
		menu_item.available_delivery = 1
		menu_item.insert(ignore_permissions=True)

		assignment = frappe.new_doc("Ledgix Branch Menu")
		assignment.branch = self.branch
		assignment.menu = menu.name
		assignment.price_list_override = self.price_list
		assignment.priority = 100
		assignment.is_active = 1
		assignment.insert(ignore_permissions=True)
		return menu.name, menu_item.name

	def _make_floor(self):
		doc = frappe.new_doc("Ledgix Floor")
		doc.branch = self.branch
		doc.floor_code = f"F{self.suffix}"
		doc.floor_name = f"Floor {self.suffix}"
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_table(self, code):
		doc = frappe.new_doc("Ledgix Restaurant Table")
		doc.branch = self.branch
		doc.floor = self.floor
		doc.table_code = f"{code}-{self.suffix}"
		doc.table_name = f"{code} {self.suffix}"
		doc.capacity = 4
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
		return doc.name

	def _open_check(self, client_order_id=None):
		session = open_table_session(self.table, covers=2)
		order = open_restaurant_order(
			order_type="Dine In",
			table_session=session["name"],
			menu=self.menu,
			client_order_id=client_order_id or f"ORDER-{uuid4().hex}",
		)
		return session, order

	def test_open_check_and_add_item_are_idempotent(self):
		client_order_id = f"ORDER-{uuid4().hex}"
		session, first = self._open_check(client_order_id)
		second = open_restaurant_order(
			order_type="Dine In",
			table_session=session["name"],
			menu=self.menu,
			client_order_id=client_order_id,
		)
		self.assertEqual(first["name"], second["name"])

		client_item_id = f"ITEM-{uuid4().hex}"
		one = add_order_item(first["name"], self.menu_item, quantity=2, client_item_id=client_item_id)
		two = add_order_item(first["name"], self.menu_item, quantity=2, client_item_id=client_item_id)
		self.assertEqual(len(one["items"]), 1)
		self.assertEqual(len(two["items"]), 1)
		self.assertEqual(one["items"][0]["name"], two["items"][0]["name"])
		self.assertAlmostEqual(one["items"][0]["quantity"], 2, places=3)

	def test_direct_order_item_creation_and_snapshot_change_are_blocked(self):
		_session, order = self._open_check()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({
				"doctype": "Ledgix Restaurant Order Item",
				"restaurant_order": order["name"],
				"menu_item": self.menu_item,
				"quantity": 1,
			}).insert(ignore_permissions=True)

		payload = add_order_item(order["name"], self.menu_item, client_item_id=f"ITEM-{uuid4().hex}")
		item = frappe.get_doc("Ledgix Restaurant Order Item", payload["items"][0]["name"])
		item.rate = item.rate + 25
		with self.assertRaises(frappe.ValidationError):
			item.save(ignore_permissions=True)

	def test_quantity_edit_is_blocked_after_kitchen_fire(self):
		_session, order = self._open_check()
		payload = add_order_item(order["name"], self.menu_item, quantity=2, client_item_id=f"ITEM-{uuid4().hex}")
		item_name = payload["items"][0]["name"]

		updated = update_order_item(item_name, quantity=3, seat_no=1, course="Main")
		self.assertAlmostEqual(updated["items"][0]["quantity"], 3, places=3)

		item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
		item.fired_quantity = 3
		item.kitchen_status = "Fired"
		item.flags.allow_operational_mutation = True
		item.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			update_order_item(item_name, quantity=4)

	def test_preparation_blocks_normal_void(self):
		_session, order = self._open_check()
		payload = add_order_item(order["name"], self.menu_item, quantity=1, client_item_id=f"ITEM-{uuid4().hex}")
		item_name = payload["items"][0]["name"]
		item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
		item.fired_quantity = 1
		item.prepared_quantity = 1
		item.kitchen_status = "Preparing"
		item.flags.allow_operational_mutation = True
		item.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			void_order_item(item_name, "Guest changed mind")

	def test_full_line_split_preserves_identity_and_replay_is_safe(self):
		_session, order = self._open_check()
		payload = add_order_item(order["name"], self.menu_item, quantity=1, seat_no=2, client_item_id=f"ITEM-{uuid4().hex}")
		item_name = payload["items"][0]["name"]
		split_id = f"SPLIT-{uuid4().hex}"
		first = split_check_by_items(order["name"], [{"order_item": item_name}], split_id, reason="Separate guest bill")
		second = split_check_by_items(order["name"], [{"order_item": item_name}], split_id, reason="Retry")
		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(second["idempotent_replay"])
		self.assertEqual(first["split"]["name"], second["split"]["name"])
		self.assertEqual(frappe.db.get_value("Ledgix Restaurant Order Item", item_name, "restaurant_order"), first["split"]["name"])

	def test_split_id_cannot_resolve_to_unrelated_order(self):
		_session, source = self._open_check()
		unrelated_id = f"UNRELATED-{uuid4().hex}"
		unrelated = open_restaurant_order(order_type="Takeaway", branch=self.branch, menu=self.menu, client_order_id=unrelated_id)
		self.assertNotEqual(source["name"], unrelated["name"])
		with self.assertRaises(frappe.ValidationError):
			split_check_by_items(source["name"], [{"order_item": "does-not-matter"}], unrelated_id, reason="Invalid collision")

	def test_table_transfer_updates_session_and_live_check(self):
		session, order = self._open_check()
		moved = transfer_table(session["name"], self.other_table, reason="Guest requested another table")
		self.assertEqual(moved["restaurant_table"], self.other_table)
		check = get_order_payload(order["name"])
		self.assertEqual(check["restaurant_table"], self.other_table)

	def test_operation_log_is_append_only_and_request_idempotent(self):
		request_id = f"phase4-test:{uuid4().hex}"
		first = log_restaurant_operation("Adjust Covers", branch=self.branch, request_id=request_id, reason="Test")
		second = log_restaurant_operation("Adjust Covers", branch=self.branch, request_id=request_id, reason="Retry")
		self.assertEqual(first, second)
		log = frappe.get_doc("Ledgix Restaurant Operation Log", first)
		log.reason = "Changed"
		with self.assertRaises(frappe.PermissionError):
			log.save(ignore_permissions=True)
