from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt


SNAPSHOT_FIELDS = (
	"kot_item",
	"restaurant_order_item",
	"branch",
	"stock_location",
	"ingredient_item",
	"stock_uom",
	"stock_quantity",
	"cost_rate",
	"line_cost",
	"consumption_key",
)
POSTING_FIELDS = ("status", "out_movement", "reversal_movement", "posted_at", "reversed_at")


class LedgixKOTConsumption(Document):
	def before_insert(self):
		if not getattr(self.flags, "from_kitchen_service", False):
			frappe.throw("Kitchen consumption snapshots are service-owned.", frappe.PermissionError)
		self.consumption_key = self.consumption_key or f"{self.kot_item}::{self.ingredient_item}"

	def validate(self):
		if flt(self.stock_quantity) <= 0:
			frappe.throw("Kitchen consumption quantity must be greater than zero.")
		kot_item = frappe.db.get_value(
			"Ledgix KOT Item",
			self.kot_item,
			["restaurant_order_item", "kot"],
			as_dict=True,
		)
		if not kot_item or kot_item.restaurant_order_item != self.restaurant_order_item:
			frappe.throw("Kitchen consumption must match the referenced KOT Item.")
		kot = frappe.db.get_value("Ledgix KOT", kot_item.kot, ["branch", "stock_location"], as_dict=True)
		if not kot or kot.branch != self.branch or kot.stock_location != self.stock_location:
			frappe.throw("Kitchen consumption branch/location must match its KOT.")
		before = self.get_doc_before_save()
		if not before:
			return
		if any(before.get(field) != self.get(field) for field in SNAPSHOT_FIELDS):
			frappe.throw("Kitchen consumption plan snapshots are immutable.", frappe.PermissionError)
		if any(before.get(field) != self.get(field) for field in POSTING_FIELDS):
			if not getattr(self.flags, "allow_posting_state_update", False):
				frappe.throw("Kitchen consumption posting state is service-owned.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Kitchen consumption history cannot be deleted.", frappe.PermissionError)
