from __future__ import annotations

import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixFloor(Document):
	def validate(self):
		self.floor_code = (self.floor_code or "").strip().upper()
		self.floor_name = (self.floor_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.floor_code):
			frappe.throw("Floor Code may contain only A-Z, 0-9 and underscore.")
		if not self.floor_name:
			frappe.throw("Floor / Area Name is required.")
		if not frappe.db.exists("Ledgix Branch", {"name": self.branch, "is_active": 1}):
			frappe.throw("Floor requires an active Branch.")
		if cint(self.sort_order) < 0:
			frappe.throw("Sort Order cannot be negative.")
		self.floor_key = f"{self.branch}::{self.floor_code}"
		if not cint(self.is_active) and not self.is_new():
			active_table = frappe.db.get_value(
				"Ledgix Restaurant Table",
				{"floor": self.name, "is_active": 1},
				"name",
			) if frappe.db.exists("DocType", "Ledgix Restaurant Table") else None
			if active_table:
				frappe.throw(f"Deactivate table {active_table} before deactivating this Floor.")
