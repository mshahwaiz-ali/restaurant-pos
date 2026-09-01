from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.api.security import require_ledgix_manager_or_above
from ledgix_saas.services.recipe import (
	build_consumption_plan,
	build_recipe_snapshot,
	recipe_margin,
)


@frappe.whitelist()
def get_recipe_cost(item=None, recipe=None, selling_rate=None, transaction_date=None):
	require_ledgix_manager_or_above()
	if not item and not recipe:
		frappe.throw("Item or Recipe is required.")
	if selling_rate not in (None, ""):
		return recipe_margin(
			recipe=recipe,
			item=item,
			selling_rate=flt(selling_rate),
			transaction_date=transaction_date,
		)
	return build_recipe_snapshot(item=item, recipe=recipe, transaction_date=transaction_date)


@frappe.whitelist()
def preview_recipe_consumption(item, quantity=1, modifier_options=None, transaction_date=None):
	"""Preview normalized stock consumption only; this endpoint never posts stock."""
	require_ledgix_manager_or_above()
	return build_consumption_plan(
		item,
		order_quantity=quantity,
		modifier_options=modifier_options,
		transaction_date=transaction_date,
	)


@frappe.whitelist()
def refresh_recipe_cost(recipe):
	"""Recalculate current food cost by re-validating the Recipe master."""
	require_ledgix_manager_or_above()
	doc = frappe.get_doc("Ledgix Recipe", recipe)
	doc.save(ignore_permissions=True)
	return build_recipe_snapshot(recipe=doc.name)
