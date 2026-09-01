from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class LedgixMenuItem(Document):
	def validate(self):
		menu = frappe.db.get_value(
			"Ledgix Menu",
			self.menu,
			["restaurant_brand", "is_active"],
			as_dict=True,
		)
		if not menu or not cint(menu.is_active):
			frappe.throw("Menu must be active.")

		section_menu = frappe.db.get_value(
			"Ledgix Menu Section",
			{"name": self.menu_section, "is_active": 1},
			"menu",
		)
		if section_menu != self.menu:
			frappe.throw("Menu Section must be active and belong to the selected Menu.")

		item = frappe.db.get_value(
			"Ledgix Item",
			self.item,
			["item_name", "active", "is_sellable"],
			as_dict=True,
		)
		if not item or not cint(item.active):
			frappe.throw("Ledgix Item must be active.")
		if frappe.get_meta("Ledgix Item").has_field("is_sellable") and not cint(item.is_sellable):
			frappe.throw("Only sellable items can be added to a Menu.")

		self.display_name = (self.display_name or item.item_name or self.item).strip()
		self.display_description = (self.display_description or "").strip()
		if int(self.sort_order or 0) < 0:
			frappe.throw("Sort Order cannot be negative.")
		if not any(cint(self.get(field)) for field in ("available_dine_in", "available_takeaway", "available_delivery")):
			frappe.throw("Enable at least one order channel for the Menu Item.")

		self.menu_item_key = f"{self.menu}::{self.item}"
		self._validate_modifier_groups()

	def _validate_modifier_groups(self):
		seen = set()
		for row in self.get("modifier_groups") or []:
			if not row.modifier_group:
				continue
			if row.modifier_group in seen:
				frappe.throw(f"Modifier Group {row.modifier_group} is attached more than once.")
			seen.add(row.modifier_group)
			group = frappe.db.get_value(
				"Ledgix Modifier Group",
				{"name": row.modifier_group, "is_active": 1},
				["min_selection", "max_selection", "selection_type"],
				as_dict=True,
			)
			if not group:
				frappe.throw(f"Modifier Group {row.modifier_group} must be active.")

			minimum = group.min_selection if int(row.min_selection_override or -1) < 0 else int(row.min_selection_override)
			maximum = group.max_selection if int(row.max_selection_override or -1) < 0 else int(row.max_selection_override)
			if row.required_override == "Required" and minimum < 1:
				minimum = 1
			elif row.required_override == "Optional":
				minimum = 0
			if maximum < minimum:
				frappe.throw(f"Modifier Group {row.modifier_group} has Max below Min for this Menu Item.")
			if group.selection_type == "Single" and maximum > 1:
				frappe.throw(f"Single-selection Modifier Group {row.modifier_group} cannot allow more than one option.")
