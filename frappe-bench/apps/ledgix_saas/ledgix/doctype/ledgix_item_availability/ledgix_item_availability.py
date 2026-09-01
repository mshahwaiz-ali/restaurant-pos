from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class LedgixItemAvailability(Document):
	def validate(self):
		if not frappe.db.exists("Ledgix Branch", {"name": self.branch, "is_active": 1}):
			frappe.throw("Availability requires an active Branch.")
		if not frappe.db.exists("Ledgix Item", {"name": self.item, "active": 1}):
			frappe.throw("Availability requires an active Item.")

		if self.status == "86d":
			self.reason = (self.reason or "").strip()
			if not self.reason:
				frappe.throw("Reason is required when an item is 86d.")
		else:
			self.status = "Available"
			self.reason = ""
			self.auto_restore_at = None

		self.availability_key = f"{self.branch}::{self.item}"
		self.updated_by = frappe.session.user
		self.updated_at = now_datetime()
