from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from ledgix.doctype.v2_test_utils import configure_v2_test_environment
from ledgix_saas.services.menu import menu_is_active


class TestRestaurantMenuSchedule(FrappeTestCase):
	def setUp(self):
		super().setUp()
		configure_v2_test_environment()

	def test_overnight_schedule_matches_next_calendar_day(self):
		suffix = uuid4().hex[:8].upper()
		menu = frappe.new_doc("Ledgix Menu")
		menu.menu_code = f"LATE_{suffix}"
		menu.menu_name = f"Late Night {suffix}"
		menu.restaurant_brand = "DEFAULT"
		menu.available_dine_in = 1
		menu.available_takeaway = 1
		menu.available_delivery = 0
		menu.is_active = 1
		menu.append("schedules", {
			"day_of_week": "Friday",
			"start_time": "18:00:00",
			"end_time": "02:00:00",
			"schedule_label": "Friday Late Night",
		})
		menu.insert(ignore_permissions=True)

		self.assertTrue(menu_is_active(menu, "Dine In", datetime(2026, 9, 4, 23, 0, 0)))
		self.assertTrue(menu_is_active(menu, "Dine In", datetime(2026, 9, 5, 1, 30, 0)))
		self.assertFalse(menu_is_active(menu, "Dine In", datetime(2026, 9, 5, 3, 0, 0)))
		self.assertFalse(menu_is_active(menu, "Delivery", datetime(2026, 9, 4, 23, 0, 0)))
