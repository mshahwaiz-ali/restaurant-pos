from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class LedgixRestaurantOrderConsumption(Document):
	def before_insert(self):
		if not getattr(self.flags, "from_restaurant_order_service", False):
			frappe.throw("Restaurant Order consumption snapshots are service-owned.", frappe.PermissionError)
		self.snapshot_key = self.snapshot_key or f"{self.restaurant_order_item}::{self.ingredient_item}"

	def validate(self):
		if flt(self.quantity_per_unit) <= 0:
			frappe.throw("Ingredient quantity per ordered unit must be greater than zero.")
		if not frappe.db.exists("Ledgix Restaurant Order Item", self.restaurant_order_item):
			frappe.throw("Restaurant Order consumption snapshot requires a valid Order Item.")
		if not self.is_new():
			frappe.throw("Restaurant Order consumption snapshots are immutable.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Restaurant Order consumption snapshots cannot be deleted.", frappe.PermissionError)
