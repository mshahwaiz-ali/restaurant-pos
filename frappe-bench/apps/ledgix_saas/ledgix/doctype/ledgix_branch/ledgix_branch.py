from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixBranch(Document):
	def validate(self):
		self.branch_code = (self.branch_code or "").strip().upper()
		self.branch_name = (self.branch_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.branch_code):
			frappe.throw("Branch Code may contain only A-Z, 0-9 and underscore.")
		if not self.branch_name:
			frappe.throw("Branch Name is required.")
		if not frappe.db.exists(
			"Ledgix Restaurant Brand",
			{"name": self.restaurant_brand, "is_active": 1},
		):
			frappe.throw("Branch requires an active Restaurant Brand.")

		self._validate_default_stock_location()
		self._validate_deactivation()

	def _validate_default_stock_location(self):
		if not self.default_stock_location:
			return
		location = frappe.db.get_value(
			"Ledgix Stock Location",
			self.default_stock_location,
			["branch", "is_active"],
			as_dict=True,
		)
		if not location or not int(location.is_active or 0):
			frappe.throw("Default Stock Location must be active.")
		if self.name and location.branch != self.name:
			frappe.throw("Default Stock Location must belong to this Branch.")

	def _validate_deactivation(self):
		if int(self.is_active or 0) or self.is_new():
			return

		open_shift = frappe.db.get_value(
			"Ledgix POS Shift",
			{"branch": self.name, "docstatus": 0, "status": "Open"},
			"name",
		) if frappe.get_meta("Ledgix POS Shift").has_field("branch") else None
		if open_shift:
			frappe.throw(f"Close POS Shift {open_shift} before deactivating this Branch.")

		active_location = frappe.db.get_value(
			"Ledgix Stock Location",
			{"branch": self.name, "is_active": 1},
			"name",
		)
		if active_location:
			frappe.throw(
				f"Deactivate Stock Location {active_location} and all other branch locations before deactivating this Branch."
			)
