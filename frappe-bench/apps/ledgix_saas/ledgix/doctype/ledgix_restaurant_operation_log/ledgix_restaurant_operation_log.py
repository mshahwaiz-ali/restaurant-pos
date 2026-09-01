from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class LedgixRestaurantOperationLog(Document):
	"""Append-only audit row for protected restaurant operations."""

	def before_insert(self):
		if not getattr(self.flags, "from_restaurant_operation_service", False):
			frappe.throw("Restaurant operation logs are created by the restaurant service.", frappe.PermissionError)
		self.actor = self.actor or frappe.session.user
		self.occurred_at = self.occurred_at or now_datetime()

	def validate(self):
		if not self.branch:
			frappe.throw("Restaurant operation log requires Branch context.")
		if not self.actor:
			frappe.throw("Restaurant operation log requires Actor context.")

	def before_save(self):
		if not self.is_new():
			frappe.throw("Restaurant operation logs are append-only.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Restaurant operation logs cannot be deleted.", frappe.PermissionError)
