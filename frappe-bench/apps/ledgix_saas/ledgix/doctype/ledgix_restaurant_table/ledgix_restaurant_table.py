from __future__ import annotations

import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixRestaurantTable(Document):
	def validate(self):
		self.table_code = (self.table_code or "").strip().upper()
		self.table_name = (self.table_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.table_code):
			frappe.throw("Table Code may contain only A-Z, 0-9 and underscore.")
		if not self.table_name:
			frappe.throw("Table Display Name is required.")
		floor_branch = frappe.db.get_value(
			"Ledgix Floor",
			{"name": self.floor, "is_active": 1},
			"branch",
		)
		if floor_branch != self.branch:
			frappe.throw("Table Floor must be active and belong to the selected Branch.")
		if cint(self.capacity) <= 0:
			frappe.throw("Table Capacity must be greater than zero.")
		if cint(self.sort_order) < 0:
			frappe.throw("Sort Order cannot be negative.")
		if flt(self.display_width) <= 0 or flt(self.display_height) <= 0:
			frappe.throw("Floor-plan display dimensions must be greater than zero.")
		self.table_key = f"{self.branch}::{self.table_code}"
		if not cint(self.is_active) and not self.is_new():
			active_session = frappe.db.get_value(
				"Ledgix Table Session",
				{"restaurant_table": self.name, "status": ["in", ["Open", "Closing"]]},
				"name",
			) if frappe.db.exists("DocType", "Ledgix Table Session") else None
			if active_session:
				frappe.throw(f"Close Table Session {active_session} before deactivating this Table.")
