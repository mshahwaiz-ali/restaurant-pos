from __future__ import annotations

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment, make_item
from ledgix_saas.services.kitchen import fire_order_items, set_kot_item_status, void_kitchen_item
from ledgix_saas.services.restaurant_orders import add_order_item, open_restaurant_order


class TestKitchenPhase5(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()
		self.suffix = uuid4().hex[:8].upper()
		self.branch = "MAIN"
		self.ingredient = self._make_ingredient()
		self.finished = self._make_finished_item()
		self.recipe = self._make_recipe()
		self.price_list = self._make_price_list()
		self.menu, self.menu_item = self._make_menu()
		self.station = self._make_default_station()

	def _make_ingredient(self):
		item = make_item(cost_price=2, opening_stock=1000)
		item.restaurant_item_type = "Ingredient"
		item.is_sellable = 0
		item.track_inventory = 1
		item.stock_uom = "Gram"
		item.save(ignore_permissions=True)
		return item

	def _make_finished_item(self):
		item = make_item(cost_price=0, opening_stock=0)
		item.restaurant_item_type = "Menu Item"
		item.is_sellable = 1
		item.track_inventory = 0
		item.stock_uom = "Portion"
		item.save(ignore_permissions=True)
		return item

	def _make_recipe(self):
		recipe = frappe.new_doc("Ledgix Recipe")
		recipe.finished_item = self.finished.name
		recipe.recipe_version = 1
		recipe.yield_quantity = 1
		recipe.output_uom = "Portion"
		recipe.is_active = 1
		recipe.append("ingredients", {
			"ingredient_item": self.ingredient.name,
			"quantity": 100,
			"uom": "Gram",
			"waste_percent": 0,
			"consume_stock": 1,
		})
		recipe.insert(ignore_permissions=True)
		return recipe

	def _make_price_list(self):
		doc = frappe.new_doc("Ledgix Price List")
		doc.price_list_name = f"KDS PRICE {self.suffix}"
		doc.currency = "PKR"
		doc.enabled = 1
		doc.priority = 50
		doc.insert(ignore_permissions=True)

		price = frappe.new_doc("Ledgix Item Price")
		price.item = self.finished.name
		price.price_list = doc.name
		price.rate = 800
		price.enabled = 1
		price.insert(ignore_permissions=True)
		return doc.name

	def _make_menu(self):
		menu = frappe.new_doc("Ledgix Menu")
		menu.menu_code = f"KDS_{self.suffix}"
		menu.menu_name = f"KDS Menu {self.suffix}"
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
		menu_item.item = self.finished.name
		menu_item.display_name = f"Kitchen Dish {self.suffix}"
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

	def _make_default_station(self):
		doc = frappe.new_doc("Ledgix Kitchen Station")
		doc.branch = self.branch
		doc.station_code = f"KDS-{self.suffix}"
		doc.station_name = f"Kitchen {self.suffix}"
		doc.station_type = "Kitchen"
		doc.display_priority = 1
		doc.is_default_station = 1
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
		return doc.name

	def _open_order_with_item(self, quantity=1):
		order = open_restaurant_order(
			order_type="Takeaway",
			branch=self.branch,
			menu=self.menu,
			client_order_id=f"ORDER-{uuid4().hex}",
		)
		order = add_order_item(
			order["name"],
			self.menu_item,
			quantity=quantity,
			client_item_id=f"ITEM-{uuid4().hex}",
		)
		return order, order["items"][0]["name"]

	def _movement_rows_for_kot(self, kot_name, movement_type):
		consumption_names = frappe.get_all(
			"Ledgix KOT Consumption",
			filters={"kot_item": ["in", frappe.get_all("Ledgix KOT Item", filters={"kot": kot_name}, pluck="name")]},
			pluck="name",
			limit_page_length=0,
		)
		if not consumption_names:
			return []
		return frappe.get_all(
			"Ledgix Stock Movement",
			filters={
				"reference_doctype": "Ledgix KOT Consumption",
				"reference_name": ["in", consumption_names],
				"movement_type": movement_type,
				"docstatus": 1,
			},
			fields=["name", "item", "quantity", "movement_type", "movement_source"],
			limit_page_length=0,
		)

	def test_fire_retry_posts_one_delta_and_one_stock_out(self):
		order, item_name = self._open_order_with_item(quantity=2)
		fire_id = f"FIRE-{uuid4().hex}"
		first = fire_order_items(order["name"], client_fire_id=fire_id)
		second = fire_order_items(order["name"], client_fire_id=fire_id)

		self.assertFalse(first["idempotent_replay"])
		self.assertTrue(second["idempotent_replay"])
		self.assertEqual(first["kot"]["name"], second["kot"]["name"])
		self.assertAlmostEqual(frappe.db.get_value("Ledgix Restaurant Order Item", item_name, "fired_quantity"), 2, places=6)
		movements = self._movement_rows_for_kot(first["kot"]["name"], "OUT")
		self.assertEqual(len(movements), 1)
		self.assertEqual(movements[0].item, self.ingredient.name)
		self.assertAlmostEqual(movements[0].quantity, 200, places=6)
		self.assertEqual(movements[0].movement_source, "Kitchen Consumption")

	def test_second_fire_posts_only_remaining_delta(self):
		order, item_name = self._open_order_with_item(quantity=3)
		first = fire_order_items(
			order["name"],
			selections=[{"order_item": item_name, "quantity": 1}],
			client_fire_id=f"FIRE-{uuid4().hex}",
		)
		second = fire_order_items(order["name"], client_fire_id=f"FIRE-{uuid4().hex}")
		first_out = self._movement_rows_for_kot(first["kot"]["name"], "OUT")
		second_out = self._movement_rows_for_kot(second["kot"]["name"], "OUT")
		self.assertAlmostEqual(first_out[0].quantity, 100, places=6)
		self.assertAlmostEqual(second_out[0].quantity, 200, places=6)
		self.assertAlmostEqual(frappe.db.get_value("Ledgix Restaurant Order Item", item_name, "fired_quantity"), 3, places=6)

	def test_recipe_edit_after_order_creation_does_not_change_fire_snapshot(self):
		order, item_name = self._open_order_with_item(quantity=1)
		snapshot_qty = frappe.db.get_value(
			"Ledgix Restaurant Order Consumption",
			{"restaurant_order_item": item_name, "ingredient_item": self.ingredient.name},
			"quantity_per_unit",
		)
		self.assertAlmostEqual(snapshot_qty, 100, places=6)

		recipe = frappe.get_doc("Ledgix Recipe", self.recipe.name)
		recipe.ingredients[0].quantity = 250
		recipe.save(ignore_permissions=True)
		result = fire_order_items(order["name"], client_fire_id=f"FIRE-{uuid4().hex}")
		movement = self._movement_rows_for_kot(result["kot"]["name"], "OUT")[0]
		self.assertAlmostEqual(movement.quantity, 100, places=6)

	def test_preparation_boundary_controls_stock_reversal(self):
		order, item_name = self._open_order_with_item(quantity=2)
		fired = fire_order_items(order["name"], client_fire_id=f"FIRE-{uuid4().hex}")
		pre_void = void_kitchen_item(
			item_name,
			quantity=1,
			reason="Guest changed mind before preparation",
			client_fire_id=f"VOID-{uuid4().hex}",
		)
		pre_in = self._movement_rows_for_kot(pre_void["kot"]["name"], "IN")
		self.assertEqual(len(pre_in), 1)
		self.assertAlmostEqual(pre_in[0].quantity, 100, places=6)
		self.assertEqual(pre_in[0].movement_source, "Kitchen Reversal")

		add_kot_item = fired["kot"]["items"][0]["name"]
		set_kot_item_status(add_kot_item, "Preparing")
		post_void = void_kitchen_item(
			item_name,
			quantity=1,
			reason="Prepared item comped",
			client_fire_id=f"VOID-{uuid4().hex}",
		)
		post_in = self._movement_rows_for_kot(post_void["kot"]["name"], "IN")
		self.assertEqual(post_in, [])
		void_kot_item = frappe.get_doc("Ledgix KOT Item", post_void["kot"]["items"][0]["name"])
		self.assertEqual(void_kot_item.consumption_status, "Waste")

	def test_kds_state_rolls_up_to_order_item_and_order(self):
		order, item_name = self._open_order_with_item(quantity=1)
		result = fire_order_items(order["name"], client_fire_id=f"FIRE-{uuid4().hex}")
		kot_item = result["kot"]["items"][0]["name"]
		set_kot_item_status(kot_item, "Preparing")
		self.assertEqual(frappe.db.get_value("Ledgix Restaurant Order Item", item_name, "kitchen_status"), "Preparing")
		set_kot_item_status(kot_item, "Ready")
		self.assertEqual(frappe.db.get_value("Ledgix Restaurant Order Item", item_name, "kitchen_status"), "Ready")
		self.assertEqual(frappe.db.get_value("Ledgix Restaurant Order", order["name"], "status"), "Ready")
		set_kot_item_status(kot_item, "Bumped")
		self.assertEqual(frappe.db.get_value("Ledgix Restaurant Order Item", item_name, "kitchen_status"), "Ready")
