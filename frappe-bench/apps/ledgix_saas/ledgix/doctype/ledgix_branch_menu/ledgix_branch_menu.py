from __future__ import annotations

import frappe
from frappe.model.document import Document


class LedgixBranchMenu(Document):
	def validate(self):
		branch = frappe.db.get_value(
			"Ledgix Branch",
			{"name": self.branch, "is_active": 1},
			["restaurant_brand"],
			as_dict=True,
		)
		menu = frappe.db.get_value(
			"Ledgix Menu",
			{"name": self.menu, "is_active": 1},
			["restaurant_brand"],
			as_dict=True,
		)
		if not branch:
			frappe.throw("Branch must be active.")
		if not menu:
			frappe.throw("Menu must be active.")
		if branch.restaurant_brand != menu.restaurant_brand:
			frappe.throw("Branch and Menu must belong to the same Restaurant Brand.")
		if self.price_list_override and not frappe.db.exists(
			"Ledgix Price List",
			{"name": self.price_list_override, "enabled": 1},
		):
			frappe.throw("Price List Override must be enabled.")
		if int(self.priority or 0) < 0:
			frappe.throw("Priority cannot be negative.")
		self.assignment_key = f"{self.branch}::{self.menu}"
