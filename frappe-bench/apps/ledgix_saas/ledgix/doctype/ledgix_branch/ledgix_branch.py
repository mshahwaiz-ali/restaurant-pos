from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixBranch(Document):
	def validate(self):
		self.branch_code = (self.branch_code or "").strip().upper()
		self.branch_name = (self.branch_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.branch_code):
			frappe.throw("Branch Code may contain only A-Z, 0-9 and underscore.")

		if self.default_stock_location:
			location_branch = frappe.db.get_value(
				"Ledgix Stock Location", self.default_stock_location, "branch"
			)
			if location_branch and location_branch != self.name:
				frappe.throw("Default Stock Location must belong to this branch.")
