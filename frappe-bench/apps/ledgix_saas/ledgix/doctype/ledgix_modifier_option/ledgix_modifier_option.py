from __future__ import annotations

import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from ledgix_saas.services.uom import get_stock_uom, get_conversion_factor


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixModifierOption(Document):
	def validate(self):
		self.option_code = (self.option_code or "").strip().upper()
		self.option_name = (self.option_name or "").strip()
		self.kitchen_label = (self.kitchen_label or self.option_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.option_code):
			frappe.throw("Modifier Option Code may contain only A-Z, 0-9 and underscore.")
		if not self.option_name:
			frappe.throw("Modifier Option Name is required.")
		if not frappe.db.exists("Ledgix Modifier Group", {"name": self.modifier_group, "is_active": 1}):
			frappe.throw("Modifier Group must be active.")
		if int(self.sort_order or 0) < 0:
			frappe.throw("Sort Order cannot be negative.")
		self.option_key = f"{self.modifier_group}::{self.option_code}"
		self._validate_stock_effect()

	def _validate_stock_effect(self):
		if self.stock_effect == "None":
			self.linked_item = None
			self.stock_quantity = 0
			self.uom = None
			return

		if not self.linked_item or not frappe.db.exists("Ledgix Item", self.linked_item):
			frappe.throw("Linked Item / Ingredient is required for this Stock Effect.")

		if self.stock_effect == "Exclude Recipe Ingredient":
			self.stock_quantity = 0
			self.uom = None
			return

		if flt(self.stock_quantity) <= 0:
			frappe.throw("Modifier stock quantity must be greater than zero.")
		self.uom = self.uom or get_stock_uom(self.linked_item)
		get_conversion_factor(self.linked_item, self.uom)
