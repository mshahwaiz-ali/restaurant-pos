from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixMenuSection(Document):
	def validate(self):
		self.section_code = (self.section_code or "").strip().upper()
		self.section_name = (self.section_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.section_code):
			frappe.throw("Section Code may contain only A-Z, 0-9 and underscore.")
		if not self.section_name:
			frappe.throw("Section Name is required.")
		if not frappe.db.exists("Ledgix Menu", self.menu):
			frappe.throw("Menu does not exist.")
		self.section_key = f"{self.menu}::{self.section_code}"
