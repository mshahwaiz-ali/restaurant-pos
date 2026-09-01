from __future__ import annotations

from datetime import date

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime

from ledgix_saas.services.uom import get_conversion_factor, get_stock_uom, to_stock_qty


class LedgixRecipe(Document):
	def validate(self):
		self.recipe_version = max(cint(self.recipe_version), 1)
		self.recipe_key = f"{self.finished_item}::V{self.recipe_version}"
		self._validate_finished_item()
		self._validate_effective_dates()
		self._validate_active_overlap()
		self._normalize_ingredients_and_cost()

	def _validate_finished_item(self):
		item = frappe.db.get_value(
			"Ledgix Item",
			{"name": self.finished_item, "active": 1},
			["item_name", "stock_uom"],
			as_dict=True,
		)
		if not item:
			frappe.throw("Recipe requires an active Finished / Menu Item.")
		self.recipe_name = (self.recipe_name or item.item_name or self.finished_item).strip()
		if flt(self.yield_quantity) <= 0:
			frappe.throw("Recipe Yield Quantity must be greater than zero.")
		if not self.output_uom:
			self.output_uom = item.stock_uom or get_stock_uom(self.finished_item)
		if not frappe.db.exists("Ledgix UOM", {"name": self.output_uom, "is_active": 1}):
			frappe.throw("Recipe Output UOM must be active.")

	def _validate_effective_dates(self):
		if self.effective_from and self.effective_to and getdate(self.effective_from) > getdate(self.effective_to):
			frappe.throw("Recipe Effective From cannot be after Effective To.")

	def _validate_active_overlap(self):
		if not cint(self.is_active) or not self.finished_item:
			return
		other_names = frappe.get_all(
			"Ledgix Recipe",
			filters={
				"finished_item": self.finished_item,
				"is_active": 1,
				"name": ["!=", self.name or ""],
			},
			pluck="name",
			limit_page_length=0,
		)
		for name in other_names:
			other = frappe.db.get_value(
				"Ledgix Recipe",
				name,
				["effective_from", "effective_to", "recipe_version"],
				as_dict=True,
			)
			if other and _date_ranges_overlap(
				self.effective_from,
				self.effective_to,
				other.effective_from,
				other.effective_to,
			):
				frappe.throw(
					f"Active Recipe version {other.recipe_version} overlaps this recipe's effective date range."
				)

	def _normalize_ingredients_and_cost(self):
		if not self.get("ingredients"):
			frappe.throw("Recipe requires at least one Ingredient.")

		seen = set()
		total_cost = 0.0
		for row in self.ingredients:
			if not row.ingredient_item:
				frappe.throw("Every Recipe row requires an Ingredient.")
			if row.ingredient_item == self.finished_item:
				frappe.throw("A Recipe cannot directly consume its own Finished Item.")
			if row.ingredient_item in seen:
				frappe.throw(f"Ingredient {row.ingredient_item} is listed more than once. Combine it into one Recipe row.")
			seen.add(row.ingredient_item)

			ingredient = frappe.db.get_value(
				"Ledgix Item",
				{"name": row.ingredient_item, "active": 1},
				["cost_price", "track_inventory", "stock_uom"],
				as_dict=True,
			)
			if not ingredient:
				frappe.throw(f"Ingredient {row.ingredient_item} must be active.")
			if flt(row.quantity) <= 0:
				frappe.throw(f"Recipe quantity for {row.ingredient_item} must be greater than zero.")
			waste = flt(row.waste_percent)
			if waste < 0 or waste > 100:
				frappe.throw(f"Waste % for {row.ingredient_item} must be between 0 and 100.")

			row.uom = row.uom or ingredient.stock_uom or get_stock_uom(row.ingredient_item)
			get_conversion_factor(row.ingredient_item, row.uom)
			row.stock_quantity = to_stock_qty(row.ingredient_item, row.quantity, row.uom)
			row.consumption_quantity = flt(row.stock_quantity * (1 + waste / 100), 6)
			row.ingredient_cost = flt(row.consumption_quantity * flt(ingredient.cost_price), 4)
			total_cost += flt(row.ingredient_cost)

		self.ingredient_cost = flt(total_cost, 4)
		self.cost_per_serving = flt(total_cost / flt(self.yield_quantity), 4)
		self.costed_at = now_datetime()


def _date_ranges_overlap(start_a, end_a, start_b, end_b):
	minimum = date.min
	maximum = date.max
	a_start = getdate(start_a) if start_a else minimum
	a_end = getdate(end_a) if end_a else maximum
	b_start = getdate(start_b) if start_b else minimum
	b_end = getdate(end_b) if end_b else maximum
	return a_start <= b_end and b_start <= a_end
