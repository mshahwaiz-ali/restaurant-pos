from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from ledgix_saas.services.organization import resolve_branch_location


class LedgixReorderRule(Document):
	def validate(self):
		self.branch, self.stock_location = resolve_branch_location(
			self.branch,
			self.stock_location,
			purpose="receiving",
		)
		item = frappe.db.get_value(
			"Ledgix Item",
			self.item,
			["active", "track_inventory"],
			as_dict=True,
		)
		if not item or not cint(item.active) or not cint(item.track_inventory):
			frappe.throw("Reorder Rule requires an active stock-tracked Item.")
		if flt(self.minimum_quantity) < 0:
			frappe.throw("Minimum Quantity cannot be negative.")
		if flt(self.target_quantity) <= 0:
			frappe.throw("Target Quantity must be greater than zero.")
		if flt(self.target_quantity) < flt(self.minimum_quantity):
			frappe.throw("Target Quantity cannot be below Minimum Quantity.")
		if cint(self.lead_time_days) < 0:
			frappe.throw("Lead Time cannot be negative.")
		if self.preferred_supplier and not frappe.db.exists(
			"Ledgix Supplier",
			{"name": self.preferred_supplier, "is_active": 1},
		):
			frappe.throw("Preferred Supplier must be active.")
		self.rule_key = f"{self.stock_location}::{self.item}"
