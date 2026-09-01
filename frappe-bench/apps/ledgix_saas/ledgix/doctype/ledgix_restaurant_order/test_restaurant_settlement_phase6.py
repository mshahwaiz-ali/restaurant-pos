from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from ledgix.doctype.v2_test_utils import (
	configure_tax_profile,
	configure_v2_test_environment,
	ensure_cash_payment_method,
	make_customer,
	make_item,
	make_item_price,
	make_item_tax_profile,
	make_price_list,
	make_sale,
	make_tax_category,
	make_tax_rate,
)
from ledgix_saas.api.kds import transition_item
from ledgix_saas.services.kitchen import fire_order_items
from ledgix_saas.services.organization import resolve_branch_location
from ledgix_saas.services.restaurant_orders import (
	add_order_item,
	open_restaurant_order,
	open_table_session,
	update_order_item,
)
from ledgix_saas.services.restaurant_settlement import (
	preview_restaurant_settlement,
	settle_restaurant_order,
)
from ledgix_saas.services.stock import _post_movement, get_location_stock


class TestRestaurantSettlementPhase6(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()
		self.branch = "MAIN"
		self.branch, self.stock_location = resolve_branch_location(self.branch, purpose="consumption")
		self.price_list = make_price_list()
		self.menu_item = self._make_direct_stock_menu_item()
		self.menu = self._make_menu(self.menu_item)
		self.station = self._ensure_default_station()
		self.cash_method = ensure_cash_payment_method()
		self.shift = self._open_shift()

	def _make_direct_stock_menu_item(self):
		item = make_item(cost_price=125, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 1
		item.save(ignore_permissions=True)
		make_item_price(item.name, self.price_list.name, 800)
		_post_movement(
			item=item.name,
			quantity=20,
			movement_type="IN",
			reference_doctype="Ledgix Item",
			reference_name=item.name,
			source="Opening",
			branch=self.branch,
			stock_location=self.stock_location,
			rate=125,
			note="Restaurant phase 6 test stock",
		)
		return item

	def _make_menu(self, item):
		menu = frappe.new_doc("Ledgix Menu")
		menu.menu_code = f"SETTLE_{self.suffix}"
		menu.menu_name = f"Settlement Menu {self.suffix}"
		menu.restaurant_brand = "DEFAULT"
		menu.default_price_list = self.price_list.name
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
		menu_item.display_name = f"Settlement Dish {self.suffix}"
		menu_item.is_active = 1
		menu_item.available_dine_in = 1
		menu_item.available_takeaway = 1
		menu_item.available_delivery = 1
		menu_item.insert(ignore_permissions=True)

		assignment = frappe.new_doc("Ledgix Branch Menu")
		assignment.branch = self.branch
		assignment.menu = menu.name
		assignment.price_list_override = self.price_list.name
		assignment.priority = 100
		assignment.is_active = 1
		assignment.insert(ignore_permissions=True)
		return {"menu": menu, "menu_item": menu_item}

	def _ensure_default_station(self):
		existing = frappe.db.get_value(
			"Ledgix Kitchen Station",
			{"branch": self.branch, "is_active": 1, "is_default_station": 1},
			"name",
		)
		if existing:
			return existing
		doc = frappe.new_doc("Ledgix Kitchen Station")
		doc.branch = self.branch
		doc.station_code = f"SETTLE-{self.suffix}"
		doc.station_name = f"Settlement Kitchen {self.suffix}"
		doc.station_type = "Kitchen"
		doc.display_priority = 1
		doc.is_default_station = 1
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
		return doc.name

	def _open_shift(self):
		existing = frappe.db.get_value(
			"Ledgix POS Shift",
			{"status": "Open", "docstatus": 0, "opened_by": frappe.session.user, "branch": self.branch},
			"name",
		)
		if existing:
			return existing
		doc = frappe.new_doc("Ledgix POS Shift")
		doc.opened_by = frappe.session.user
		doc.branch = self.branch
		doc.stock_location = self.stock_location
		doc.opening_time = now_datetime()
		doc.opening_cash = 1000
		doc.status = "Open"
		doc.insert(ignore_permissions=True)
		return doc.name

	def _open_takeaway(self, quantity=1):
		order = open_restaurant_order(
			order_type="Takeaway",
			branch=self.branch,
			menu=self.menu["menu"].name,
			client_order_id=f"ORDER-{uuid4().hex}",
		)
		order = add_order_item(
			order["name"],
			self.menu["menu_item"].name,
			quantity=quantity,
			client_item_id=f"ITEM-{uuid4().hex}",
		)
		return order, order["items"][0]["name"]

	def _fire(self, order_name):
		return fire_order_items(order_name, client_fire_id=f"FIRE-{uuid4().hex}")

	def _settle_cash(self, order_name, amount, client_sale_id=None, **kwargs):
		return settle_restaurant_order(
			order_name,
			tenders=[{"payment_method": self.cash_method, "amount": amount}],
			client_sale_id=client_sale_id or f"SALE-{uuid4().hex}",
			request_id=f"SETTLE-{uuid4().hex}",
			**kwargs,
		)

	def test_direct_stock_is_consumed_at_fire_not_again_at_sale(self):
		order, _item_name = self._open_takeaway(quantity=2)
		before = get_location_stock(self.menu_item.name, self.stock_location)
		fired = self._fire(order["name"])
		after_fire = get_location_stock(self.menu_item.name, self.stock_location)
		self.assertAlmostEqual(before - after_fire, 2, places=6)

		result = self._settle_cash(order["name"], fired["order"]["grand_total"])
		after_sale = get_location_stock(self.menu_item.name, self.stock_location)
		self.assertAlmostEqual(after_sale, after_fire, places=6)
		self.assertFalse(
			frappe.db.exists(
				"Ledgix Stock Movement",
				{"reference_doctype": "Ledgix Sale", "reference_name": result["sale"]["name"], "docstatus": 1},
			)
		)

	def test_settlement_retry_returns_same_submitted_sale(self):
		order, _item_name = self._open_takeaway()
		fired = self._fire(order["name"])
		client_sale_id = f"SALE-{uuid4().hex}"
		first = self._settle_cash(order["name"], fired["order"]["grand_total"], client_sale_id=client_sale_id)
		second = self._settle_cash(order["name"], first["sale"]["grand_total"], client_sale_id=client_sale_id)
		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(second["idempotent_replay"])
		self.assertEqual(first["sale"]["name"], second["sale"]["name"])
		self.assertEqual(
			frappe.db.get_value("Ledgix Restaurant Order", order["name"], "linked_sale"),
			first["sale"]["name"],
		)

	def test_fired_line_context_is_server_locked(self):
		order, item_name = self._open_takeaway()
		self._fire(order["name"])
		with self.assertRaises(frappe.ValidationError):
			update_order_item(item_name, item_note="Changed after fire")

	def test_kds_cannot_move_ready_item_back_to_preparing(self):
		order, _item_name = self._open_takeaway()
		fired = self._fire(order["name"])
		kot_item = fired["kot"]["items"][0]["name"]
		transition_item(kot_item, "Preparing")
		transition_item(kot_item, "Ready")
		with self.assertRaises(frappe.ValidationError):
			transition_item(kot_item, "Preparing")

	def test_discount_uses_locked_tax_snapshot_and_reconciles_sale_total(self):
		tax_category = make_tax_category(rate=10)
		make_tax_rate(tax_category.name, rate=10)
		configure_tax_profile(tax_category.name, price_includes_tax=False)
		profile = make_item_tax_profile(
			self.menu_item.name,
			tax_category.name,
			extra_tax_per_unit=2,
			further_tax_per_unit=1,
		)

		order, item_name = self._open_takeaway()
		locked = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
		self.assertAlmostEqual(locked.tax_rate_snapshot, 10, places=2)
		self.assertAlmostEqual(locked.extra_tax_per_unit_snapshot, 2, places=2)

		profile.extra_tax_per_unit = 25
		profile.save(ignore_permissions=True)
		self._fire(order["name"])
		preview = preview_restaurant_settlement(order["name"], discount_amount=100)
		result = self._settle_cash(
			order["name"],
			preview["grand_total"],
			discount_amount=100,
			adjustment_reason="Manager discount test",
		)
		sale = frappe.get_doc("Ledgix Sale", result["sale"]["name"])
		tax_row = sale.tax_details[0]
		self.assertAlmostEqual(tax_row.discount_amount, 100, places=2)
		self.assertAlmostEqual(tax_row.tax_rate, 10, places=2)
		self.assertAlmostEqual(tax_row.extra_tax, 2, places=2)
		self.assertAlmostEqual(sale.grand_total, sum(row.net_amount for row in sale.tax_details), places=2)

	def test_mapped_service_charge_and_tip_become_fiscal_sale_lines(self):
		service_item = make_item(cost_price=0, opening_stock=0)
		service_item.track_inventory = 0
		service_item.is_sellable = 1
		service_item.save(ignore_permissions=True)
		tip_item = make_item(cost_price=0, opening_stock=0)
		tip_item.track_inventory = 0
		tip_item.is_sellable = 1
		tip_item.save(ignore_permissions=True)
		frappe.db.set_value("Ledgix Branch", self.branch, "service_charge_item", service_item.name)
		frappe.db.set_value("Ledgix Branch", self.branch, "tip_item", tip_item.name)

		order, _item_name = self._open_takeaway()
		self._fire(order["name"])
		preview = preview_restaurant_settlement(order["name"], service_charge=50, tip_amount=20)
		result = self._settle_cash(
			order["name"],
			preview["grand_total"],
			service_charge=50,
			tip_amount=20,
			adjustment_reason="Configured service charge",
		)
		sale = frappe.get_doc("Ledgix Sale", result["sale"]["name"])
		charge_rows = [row for row in sale.items if row.get("restaurant_order_charge")]
		self.assertEqual(len(charge_rows), 2)
		self.assertEqual({row.restaurant_charge_type for row in charge_rows}, {"Service Charge", "Tip"})
		self.assertEqual(len(sale.tax_details), 3)
		self.assertAlmostEqual(sale.grand_total, sum(row.net_amount for row in sale.tax_details), places=2)

	def test_last_sibling_check_settlement_closes_table_session(self):
		floor = frappe.new_doc("Ledgix Floor")
		floor.branch = self.branch
		floor.floor_code = f"S{self.suffix}"
		floor.floor_name = f"Settlement Floor {self.suffix}"
		floor.is_active = 1
		floor.insert(ignore_permissions=True)

		table = frappe.new_doc("Ledgix Restaurant Table")
		table.branch = self.branch
		table.floor = floor.name
		table.table_code = f"T-{self.suffix}"
		table.table_name = f"Table {self.suffix}"
		table.capacity = 4
		table.is_active = 1
		table.insert(ignore_permissions=True)

		session = open_table_session(table.name, covers=2)
		orders = []
		for index in range(2):
			order = open_restaurant_order(
				order_type="Dine In",
				table_session=session["name"],
				menu=self.menu["menu"].name,
				client_order_id=f"SIBLING-{index}-{uuid4().hex}",
			)
			order = add_order_item(
				order["name"],
				self.menu["menu_item"].name,
				client_item_id=f"SIBLING-ITEM-{index}-{uuid4().hex}",
			)
			order = self._fire(order["name"])["order"]
			orders.append(order)

		self._settle_cash(orders[0]["name"], orders[0]["grand_total"])
		self.assertEqual(frappe.db.get_value("Ledgix Table Session", session["name"], "status"), "Open")
		self._settle_cash(orders[1]["name"], orders[1]["grand_total"])
		self.assertEqual(frappe.db.get_value("Ledgix Table Session", session["name"], "status"), "Closed")

	def test_restaurant_sale_cannot_be_cancelled_directly(self):
		order, _item_name = self._open_takeaway()
		fired = self._fire(order["name"])
		result = self._settle_cash(order["name"], fired["order"]["grand_total"])
		sale = frappe.get_doc("Ledgix Sale", result["sale"]["name"])
		with self.assertRaises(frappe.ValidationError):
			sale.cancel()

	def test_non_restaurant_sale_still_posts_stock(self):
		customer = make_customer(customer_type="B2B", payment_terms_days=30, credit_limit=100000)
		item = make_item(cost_price=50, opening_stock=5)
		before = get_location_stock(item.name, self.stock_location)
		sale = make_sale(customer.name, item.name, quantity=1, rate=100, sale_channel="B2B", submit=True)
		after = get_location_stock(item.name, self.stock_location)
		self.assertAlmostEqual(before - after, 1, places=6)
		self.assertTrue(
			frappe.db.exists(
				"Ledgix Stock Movement",
				{"reference_doctype": "Ledgix Sale", "reference_name": sale.name, "docstatus": 1},
			)
		)
