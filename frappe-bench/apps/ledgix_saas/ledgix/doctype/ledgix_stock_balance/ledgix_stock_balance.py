from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class LedgixStockBalance(Document):
	def validate(self):
		if not self.stock_location or not self.item:
			frappe.throw("Stock Location and Item are required.")

		location_branch = frappe.db.get_value(
			"Ledgix Stock Location", self.stock_location, "branch"
		)
		if not location_branch:
			frappe.throw("Stock Location does not exist.")
		if self.branch and self.branch != location_branch:
			frappe.throw("Stock Balance branch must match the Stock Location branch.")

		self.branch = location_branch
		self.balance_key = f"{self.stock_location}::{self.item}"
		self.quantity = flt(self.quantity)
		self.valuation_rate = max(flt(self.valuation_rate), 0)
		self.stock_value = flt(self.quantity * self.valuation_rate, 6)
