from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from ledgix_saas.services.organization import resolve_branch_location
from ledgix_saas.services.purchase_orders import validate_purchase_order_cancel
from ledgix_saas.services.uom import to_stock_qty


class LedgixPurchaseOrder(Document):
	def before_insert(self):
		self.order_date = self.order_date or nowdate()
		self.status = "Draft"
		self.client_purchase_order_id = self.client_purchase_order_id or frappe.generate_hash(length=20)

	def validate(self):
		self.branch, self.stock_location = resolve_branch_location(
			self.branch,
			self.stock_location,
			purpose="receiving",
		)
		if not frappe.db.exists("Ledgix Supplier", {"name": self.supplier, "is_active": 1}):
			frappe.throw("Purchase Order requires an active Supplier.")
		if self.expected_date and getdate(self.expected_date) < getdate(self.order_date):
			frappe.throw("Expected Date cannot be before Order Date.")
		if not self.items:
			frappe.throw("Purchase Order requires at least one Item.")

		seen = set()
		total_stock_qty = 0.0
		subtotal = 0.0
		for row in self.items:
			if row.item in seen:
				frappe.throw(f"Item {row.item} is listed more than once. Combine it into one Purchase Order row.")
			seen.add(row.item)
			item = frappe.db.get_value(
				"Ledgix Item",
				row.item,
				["active", "track_inventory", "stock_uom"],
				as_dict=True,
			)
			if not item or not int(item.active or 0) or not int(item.track_inventory or 0):
				frappe.throw(f"Purchase Order item {row.item} must be an active stock-tracked Item.")
			if flt(row.quantity) <= 0:
				frappe.throw(f"Ordered quantity for {row.item} must be greater than zero.")
			if flt(row.rate) < 0:
				frappe.throw(f"Rate for {row.item} cannot be negative.")
			row.uom = row.uom or item.stock_uom
			row.stock_uom_snapshot = item.stock_uom
			row.stock_quantity = flt(to_stock_qty(row.item, row.quantity, row.uom), 6)
			row.amount = flt(row.quantity * flt(row.rate), 4)
			row.stock_rate = flt(row.amount / row.stock_quantity, 6) if flt(row.stock_quantity) else 0
			row.received_stock_quantity = min(max(flt(row.received_stock_quantity), 0), row.stock_quantity)
			row.outstanding_stock_quantity = flt(max(row.stock_quantity - row.received_stock_quantity, 0), 6)
			total_stock_qty += flt(row.stock_quantity)
			subtotal += flt(row.amount)
		self.total_stock_quantity = flt(total_stock_qty, 6)
		self.subtotal = flt(subtotal, 2)
		if self.docstatus == 0:
			self.received_percent = 0

	def before_submit(self):
		self.status = "Open"

	def before_cancel(self):
		validate_purchase_order_cancel(self)

	def on_cancel(self):
		self.db_set("status", "Cancelled", update_modified=False)
