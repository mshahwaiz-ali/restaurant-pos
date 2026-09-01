from __future__ import annotations

import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, getdate


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixMenu(Document):
	def validate(self):
		self.menu_code = (self.menu_code or "").strip().upper()
		self.menu_name = (self.menu_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.menu_code):
			frappe.throw("Menu Code may contain only A-Z, 0-9 and underscore.")
		if not self.menu_name:
			frappe.throw("Menu Name is required.")
		if not frappe.db.exists("Ledgix Restaurant Brand", {"name": self.restaurant_brand, "is_active": 1}):
			frappe.throw("Menu requires an active Restaurant Brand.")
		if self.default_price_list and not frappe.db.exists("Ledgix Price List", {"name": self.default_price_list, "enabled": 1}):
			frappe.throw("Default Price List must be enabled.")
		if not any(cint(self.get(field)) for field in ("available_dine_in", "available_takeaway", "available_delivery")):
			frappe.throw("Enable at least one order channel for the Menu.")
		if self.valid_from and self.valid_to and getdate(self.valid_from) > getdate(self.valid_to):
			frappe.throw("Menu Valid From cannot be after Valid To.")
		self._validate_schedules()
		self._validate_deactivation()

	def _validate_schedules(self):
		seen = set()
		for row in self.get("schedules") or []:
			key = (row.day_of_week, str(row.start_time), str(row.end_time))
			if key in seen:
				frappe.throw(
					f"Duplicate Menu schedule for {row.day_of_week} {row.start_time}–{row.end_time}."
				)
			seen.add(key)
			if not row.start_time or not row.end_time:
				frappe.throw("Every Menu schedule requires Start Time and End Time.")
			if str(row.start_time) == str(row.end_time):
				frappe.throw("Menu schedule Start Time and End Time cannot be identical; leave schedules empty for all-day availability.")

	def _validate_deactivation(self):
		if cint(self.is_active) or self.is_new():
			return
		active_assignment = frappe.db.get_value(
			"Ledgix Branch Menu",
			{"menu": self.name, "is_active": 1},
			"name",
		) if frappe.db.exists("DocType", "Ledgix Branch Menu") else None
		if active_assignment:
			frappe.throw(f"Deactivate Branch Menu assignment {active_assignment} before deactivating this Menu.")
