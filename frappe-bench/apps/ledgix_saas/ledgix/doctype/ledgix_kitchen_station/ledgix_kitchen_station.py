from __future__ import annotations

import frappe
from frappe.model.document import Document

from ledgix_saas.services.organization import ensure_branch_access


class LedgixKitchenStation(Document):
	def validate(self):
		ensure_branch_access(self.branch)
		self.station_code = str(self.station_code or "").strip().upper()
		self.station_name = str(self.station_name or "").strip()
		if not self.station_code or not self.station_name:
			frappe.throw("Kitchen Station Code and Name are required.")
		self.station_key = f"{self.branch}::{self.station_code}"
		if self.is_default_station and self.is_active:
			existing = frappe.db.get_value(
				"Ledgix Kitchen Station",
				{"branch": self.branch, "is_default_station": 1, "is_active": 1, "name": ["!=", self.name or ""]},
				"name",
			)
			if existing:
				frappe.throw(f"Branch {self.branch} already has default Kitchen Station {existing}.")
