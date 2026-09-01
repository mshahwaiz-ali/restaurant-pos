from __future__ import annotations

import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixModifierGroup(Document):
	def validate(self):
		self.modifier_group_code = (self.modifier_group_code or "").strip().upper()
		self.modifier_group_name = (self.modifier_group_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.modifier_group_code):
			frappe.throw("Modifier Group Code may contain only A-Z, 0-9 and underscore.")
		if not self.modifier_group_name:
			frappe.throw("Modifier Group Name is required.")
		minimum = max(cint(self.min_selection), 0)
		maximum = max(cint(self.max_selection), 0)
		if maximum < minimum:
			frappe.throw("Maximum Selections cannot be less than Minimum Selections.")
		if self.selection_type == "Single" and maximum > 1:
			frappe.throw("Single-selection modifier groups cannot allow more than one selection.")
		self.min_selection = minimum
		self.max_selection = maximum
