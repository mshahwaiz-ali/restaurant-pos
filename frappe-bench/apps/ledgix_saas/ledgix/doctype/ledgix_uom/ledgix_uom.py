from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")


class LedgixUOM(Document):
	def validate(self):
		self.uom_name = (self.uom_name or "").strip()
		self.symbol = (self.symbol or "").strip()
		if not self.uom_name or not NAME_PATTERN.fullmatch(self.uom_name):
			frappe.throw("UOM Name contains unsupported characters.")
		if not self.symbol:
			frappe.throw("UOM Symbol is required.")
		if int(self.decimal_precision or 0) < 0 or int(self.decimal_precision or 0) > 6:
			frappe.throw("Decimal Precision must be between 0 and 6.")

		if not int(self.is_active or 0) and not self.is_new():
			used_as_stock_uom = frappe.db.exists(
				"Ledgix Item",
				{"stock_uom": self.name},
			) if frappe.get_meta("Ledgix Item").has_field("stock_uom") else None
			if used_as_stock_uom:
				frappe.throw("This UOM is used as an Item Stock UOM and cannot be deactivated.")
