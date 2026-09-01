# Copyright (c) 2026, Ali and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LedgixUserProfile(Document):
	def validate(self):
		self._validate_branch_defaults()

	def _validate_branch_defaults(self):
		if not frappe.get_meta(self.doctype).has_field("default_branch"):
			return

		if self.default_stock_location:
			location = frappe.db.get_value(
				"Ledgix Stock Location",
				self.default_stock_location,
				["branch", "is_active"],
				as_dict=True,
			)
			if not location or not int(location.is_active or 0):
				frappe.throw("Default Stock Location must be active.")
			if self.default_branch and location.branch != self.default_branch:
				frappe.throw("Default Stock Location must belong to the Default Branch.")
			self.default_branch = self.default_branch or location.branch

		if self.default_branch:
			active = frappe.db.get_value(
				"Ledgix Branch",
				{"name": self.default_branch, "is_active": 1},
				"name",
			)
			if not active:
				frappe.throw("Default Branch must be active.")

		seen = set()
		for row in self.get("allowed_branches") or []:
			if not row.branch:
				continue
			if row.branch in seen:
				frappe.throw(f"Branch {row.branch} is listed more than once in Allowed Branches.")
			seen.add(row.branch)
			if not frappe.db.exists("Ledgix Branch", {"name": row.branch, "is_active": 1}):
				frappe.throw(f"Allowed Branch {row.branch} must be active.")

		if self.default_branch and self.default_branch not in seen:
			self.append("allowed_branches", {"branch": self.default_branch})
