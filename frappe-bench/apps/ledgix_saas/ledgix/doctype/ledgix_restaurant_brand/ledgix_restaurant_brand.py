from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixRestaurantBrand(Document):
	def validate(self):
		self.brand_code = (self.brand_code or "").strip().upper()
		self.brand_name = (self.brand_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.brand_code):
			frappe.throw("Brand Code may contain only A-Z, 0-9 and underscore.")
