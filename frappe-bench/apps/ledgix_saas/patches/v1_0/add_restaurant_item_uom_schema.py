from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


BASE_UOMS = (
	("Piece", "pc", "Count", 0),
	("Kilogram", "kg", "Weight", 3),
	("Gram", "g", "Weight", 3),
	("Liter", "L", "Volume", 3),
	("Milliliter", "ml", "Volume", 3),
	("Pack", "pack", "Packaging", 0),
	("Dozen", "doz", "Packaging", 2),
	("Bottle", "btl", "Packaging", 0),
	("Box", "box", "Packaging", 0),
	("Portion", "portion", "Count", 3),
)

LEGACY_UNIT_MAP = {
	"Piece": "Piece",
	"Kg": "Kilogram",
	"Gram": "Gram",
	"Liter": "Liter",
	"Pack": "Pack",
}


def execute():
	_bootstrap_uoms()
	create_custom_fields(
		{
			"Ledgix Item": [
				{
					"fieldname": "restaurant_item_section",
					"label": "Restaurant Item Setup",
					"fieldtype": "Section Break",
					"insert_after": "tracking_type",
					"module": "Ledgix",
				},
				{
					"fieldname": "restaurant_item_type",
					"label": "Restaurant Item Type",
					"fieldtype": "Select",
					"options": "Retail Item\nMenu Item\nIngredient\nPackaging\nConsumable\nPrepared Item",
					"default": "Retail Item",
					"insert_after": "restaurant_item_section",
					"in_list_view": 1,
					"in_standard_filter": 1,
					"module": "Ledgix",
				},
				{
					"fieldname": "is_sellable",
					"label": "Sellable",
					"fieldtype": "Check",
					"default": "1",
					"insert_after": "restaurant_item_type",
					"module": "Ledgix",
				},
				{
					"fieldname": "track_inventory",
					"label": "Track Inventory",
					"fieldtype": "Check",
					"default": "1",
					"insert_after": "is_sellable",
					"description": "Disable for service/non-stock menu items. Recipe ingredient consumption is handled separately from finished menu-item stock.",
					"module": "Ledgix",
				},
				{
					"fieldname": "uom_section",
					"label": "Units of Measure",
					"fieldtype": "Section Break",
					"insert_after": "track_inventory",
					"module": "Ledgix",
				},
				{
					"fieldname": "stock_uom",
					"label": "Stock UOM",
					"fieldtype": "Link",
					"options": "Ledgix UOM",
					"insert_after": "uom_section",
					"reqd": 1,
					"in_standard_filter": 1,
					"description": "Canonical quantity unit used by inventory and recipes.",
					"module": "Ledgix",
				},
				{
					"fieldname": "uom_conversions",
					"label": "Alternate UOM Conversions",
					"fieldtype": "Table",
					"options": "Ledgix Item UOM Conversion",
					"insert_after": "stock_uom",
					"module": "Ledgix",
				},
			]
		},
		update=True,
	)

	frappe.db.sql(
		"""
		UPDATE `tabLedgix Item`
		SET restaurant_item_type = COALESCE(NULLIF(restaurant_item_type, ''), 'Retail Item'),
		    is_sellable = COALESCE(is_sellable, 1),
		    track_inventory = COALESCE(track_inventory, 1)
		"""
	)

	for legacy_unit, stock_uom in LEGACY_UNIT_MAP.items():
		frappe.db.sql(
			"""
			UPDATE `tabLedgix Item`
			SET stock_uom=%s
			WHERE COALESCE(stock_uom, '')='' AND unit=%s
			""",
			(stock_uom, legacy_unit),
		)
	frappe.db.sql(
		"UPDATE `tabLedgix Item` SET stock_uom='Piece' WHERE COALESCE(stock_uom, '')=''"
	)
	frappe.clear_cache(doctype="Ledgix Item")


def _bootstrap_uoms():
	for name, symbol, uom_type, precision in BASE_UOMS:
		if frappe.db.exists("Ledgix UOM", name):
			continue
		doc = frappe.new_doc("Ledgix UOM")
		doc.uom_name = name
		doc.symbol = symbol
		doc.uom_type = uom_type
		doc.decimal_precision = precision
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
