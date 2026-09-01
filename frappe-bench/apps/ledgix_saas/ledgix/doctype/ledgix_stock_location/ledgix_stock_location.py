from __future__ import annotations

import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt


CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class LedgixStockLocation(Document):
	def validate(self):
		self.location_code = (self.location_code or "").strip().upper()
		self.location_name = (self.location_name or "").strip()
		if not CODE_PATTERN.fullmatch(self.location_code):
			frappe.throw("Location Code may contain only A-Z, 0-9 and underscore.")
		if not frappe.db.exists("Ledgix Branch", {"name": self.branch, "is_active": 1}):
			frappe.throw("Stock Location requires an active Branch.")

		self.location_key = f"{self.branch}-{self.location_code}"
		self._validate_default_uniqueness()
		self._validate_deactivation()

	def _validate_default_uniqueness(self):
		for fieldname, label in (
			("is_default_receiving", "default receiving"),
			("is_default_consumption", "default consumption"),
		):
			if not int(self.get(fieldname) or 0):
				continue
			existing = frappe.db.get_value(
				"Ledgix Stock Location",
				{
					"branch": self.branch,
					fieldname: 1,
					"is_active": 1,
					"name": ["!=", self.name or ""],
				},
				"name",
			)
			if existing:
				frappe.throw(
					f"Branch {self.branch} already has {existing} configured as its {label} location."
				)

	def _validate_deactivation(self):
		if int(self.is_active or 0) or self.is_new():
			return

		if frappe.db.get_value("Ledgix Branch", self.branch, "default_stock_location") == self.name:
			frappe.throw("Remove this location as the Branch Default Stock Location before deactivating it.")

		nonzero = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(ABS(quantity)), 0)
				FROM `tabLedgix Stock Balance`
				WHERE stock_location=%s AND ABS(quantity) > 0.000001
				""",
				(self.name,),
			)[0][0]
		)
		if nonzero > 0.000001:
			frappe.throw("Move or adjust all stock to zero before deactivating this Stock Location.")
