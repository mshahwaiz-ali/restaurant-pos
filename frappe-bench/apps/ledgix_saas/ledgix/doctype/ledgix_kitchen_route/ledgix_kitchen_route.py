from __future__ import annotations

import frappe
from frappe.model.document import Document

from ledgix_saas.services.organization import ensure_branch_access


ROUTE_FIELD = {
	"Item": "item",
	"Menu Item": "menu_item",
	"Menu Section": "menu_section",
}


class LedgixKitchenRoute(Document):
	def validate(self):
		ensure_branch_access(self.branch)
		station_branch = frappe.db.get_value(
			"Ledgix Kitchen Station",
			{"name": self.kitchen_station, "is_active": 1},
			"branch",
		)
		if station_branch != self.branch:
			frappe.throw("Kitchen Station must be active and belong to the same Branch as the routing rule.")

		fieldname = ROUTE_FIELD.get(self.route_type)
		if not fieldname:
			frappe.throw("Kitchen Route Type is invalid.")
		for candidate in ROUTE_FIELD.values():
			value = self.get(candidate)
			if candidate == fieldname and not value:
				frappe.throw(f"{self.meta.get_label(candidate)} is required for this Kitchen Route.")
			if candidate != fieldname and value:
				frappe.throw("Kitchen Route must target exactly one Item, Menu Item, or Menu Section.")

		filters = {
			"branch": self.branch,
			"route_type": self.route_type,
			fieldname: self.get(fieldname),
			"is_active": 1,
			"name": ["!=", self.name or ""],
		}
		if self.is_active and frappe.db.get_value("Ledgix Kitchen Route", filters, "name"):
			frappe.throw("An active Kitchen Route already exists for this Branch and target.")
