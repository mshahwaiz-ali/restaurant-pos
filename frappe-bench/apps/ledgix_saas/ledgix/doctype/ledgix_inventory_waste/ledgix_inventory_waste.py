from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from ledgix_saas.services.organization import resolve_branch_location
from ledgix_saas.services.restaurant_inventory import (
	cancel_inventory_waste,
	get_standard_inventory_item,
	post_inventory_waste,
)
from ledgix_saas.services.uom import to_stock_qty


class LedgixInventoryWaste(Document):
	def before_insert(self):
		self.waste_date = self.waste_date or now_datetime()
		self.status = "Draft"
		self.client_waste_id = self.client_waste_id or frappe.generate_hash(length=20)

	def validate(self):
		self.branch, self.stock_location = resolve_branch_location(
			self.branch,
			self.stock_location,
			purpose="consumption",
		)
		if not str(self.reason or "").strip():
			frappe.throw("Reason is required for Inventory Waste.")
		if not self.items:
			frappe.throw("Inventory Waste requires at least one Item.")

		seen = set()
		total_qty = 0.0
		total_value = 0.0
		for row in self.items:
			if row.item in seen:
				frappe.throw(f"Item {row.item} is listed more than once. Combine it into one waste row.")
			seen.add(row.item)
			item = get_standard_inventory_item(row.item)
			if flt(row.quantity) <= 0:
				frappe.throw(f"Waste quantity for {row.item} must be greater than zero.")
			row.uom = row.uom or item.stock_uom
			row.stock_quantity = flt(to_stock_qty(row.item, row.quantity, row.uom), 6)
			row.valuation_rate = max(flt(item.cost_price), 0)
			row.waste_value = flt(row.stock_quantity * row.valuation_rate, 4)
			row.tracking_type_snapshot = item.tracking_type or "Normal"
			total_qty += flt(row.stock_quantity)
			total_value += flt(row.waste_value)
		self.total_stock_quantity = flt(total_qty, 6)
		self.total_waste_value = flt(total_value, 4)

	def before_submit(self):
		self.status = "Submitted"

	def on_submit(self):
		post_inventory_waste(self)

	def on_cancel(self):
		cancel_inventory_waste(self)
		self.db_set("status", "Cancelled", update_modified=False)
