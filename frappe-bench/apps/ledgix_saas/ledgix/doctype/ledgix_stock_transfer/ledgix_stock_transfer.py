from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from ledgix_saas.services.restaurant_inventory import (
	cancel_stock_transfer,
	get_standard_inventory_item,
	normalize_transfer_context,
	post_stock_transfer,
)
from ledgix_saas.services.uom import to_stock_qty


class LedgixStockTransfer(Document):
	def before_insert(self):
		self.transfer_date = self.transfer_date or now_datetime()
		self.status = "Draft"
		self.client_transfer_id = self.client_transfer_id or frappe.generate_hash(length=20)

	def validate(self):
		(
			self.source_branch,
			self.source_stock_location,
			self.destination_branch,
			self.destination_stock_location,
		) = normalize_transfer_context(
			self.source_branch,
			self.source_stock_location,
			self.destination_branch,
			self.destination_stock_location,
		)
		if not str(self.reason or "").strip():
			frappe.throw("Reason is required for a Stock Transfer.")
		if not self.items:
			frappe.throw("Stock Transfer requires at least one Item.")

		seen = set()
		total_qty = 0.0
		total_value = 0.0
		for row in self.items:
			if row.item in seen:
				frappe.throw(f"Item {row.item} is listed more than once. Combine it into one transfer row.")
			seen.add(row.item)
			item = get_standard_inventory_item(row.item)
			if flt(row.quantity) <= 0:
				frappe.throw(f"Transfer quantity for {row.item} must be greater than zero.")
			row.uom = row.uom or item.stock_uom
			row.stock_quantity = flt(to_stock_qty(row.item, row.quantity, row.uom), 6)
			row.valuation_rate = max(flt(item.cost_price), 0)
			row.stock_value = flt(row.stock_quantity * row.valuation_rate, 4)
			row.tracking_type_snapshot = item.tracking_type or "Normal"
			total_qty += flt(row.stock_quantity)
			total_value += flt(row.stock_value)
		self.total_stock_quantity = flt(total_qty, 6)
		self.total_stock_value = flt(total_value, 4)

	def before_submit(self):
		self.status = "Submitted"

	def on_submit(self):
		post_stock_transfer(self)

	def on_cancel(self):
		cancel_stock_transfer(self)
		self.db_set("status", "Cancelled", update_modified=False)
