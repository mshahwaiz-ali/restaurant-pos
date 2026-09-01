from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from ledgix_saas.services.organization import resolve_branch_location
from ledgix_saas.services.restaurant_inventory import get_standard_inventory_item, post_stock_count
from ledgix_saas.services.stock import get_location_stock
from ledgix_saas.services.uom import to_stock_qty


class LedgixStockCount(Document):
	def before_insert(self):
		self.count_date = self.count_date or now_datetime()
		self.status = "Draft"
		self.client_count_id = self.client_count_id or frappe.generate_hash(length=20)

	def validate(self):
		self.branch, self.stock_location = resolve_branch_location(
			self.branch,
			self.stock_location,
		)
		if not self.items:
			frappe.throw("Stock Count requires at least one Item.")

		seen = set()
		total_abs_variance = 0.0
		total_variance_value = 0.0
		for row in self.items:
			if row.item in seen:
				frappe.throw(f"Item {row.item} is listed more than once. Combine it into one count row.")
			seen.add(row.item)

			item = get_standard_inventory_item(row.item, workflow="stock count")
			if not int(row.count_confirmed or 0):
				frappe.throw(f"Confirm the physical count for {row.item}, including an explicit zero count.")
			if flt(row.counted_quantity) < 0:
				frappe.throw(f"Counted quantity for {row.item} cannot be negative.")
			row.uom = row.uom or item.stock_uom
			row.counted_stock_quantity = flt(
				to_stock_qty(row.item, row.counted_quantity, row.uom),
				6,
			)
			row.expected_quantity = flt(get_location_stock(row.item, self.stock_location), 6)
			row.variance_quantity = flt(row.counted_stock_quantity - row.expected_quantity, 6)
			row.valuation_rate = max(flt(item.cost_price), 0)
			row.variance_value = flt(row.variance_quantity * row.valuation_rate, 4)
			row.tracking_type_snapshot = item.tracking_type or "Normal"
			total_abs_variance += abs(flt(row.variance_quantity))
			total_variance_value += flt(row.variance_value)

		self.total_items = len(self.items)
		self.total_absolute_variance_quantity = flt(total_abs_variance, 6)
		self.total_variance_value = flt(total_variance_value, 4)

	def before_submit(self):
		self.status = "Submitted"

	def on_submit(self):
		post_stock_count(self)

	def on_cancel(self):
		frappe.throw(
			"Submitted Stock Counts cannot be cancelled safely. Create a corrective Stock Count instead."
		)
