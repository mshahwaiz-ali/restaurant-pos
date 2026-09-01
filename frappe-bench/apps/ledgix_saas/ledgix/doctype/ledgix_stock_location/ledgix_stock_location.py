from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixStockLocation(Document):
	def validate(self):
		self.location_code = (self.location_code or "").strip().upper()
		self.location_name = (self.location_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.location_code):
			frappe.throw("Location Code may contain only A-Z, 0-9 and underscore.")
		self.location_key = f"{self.branch}-{self.location_code}"
