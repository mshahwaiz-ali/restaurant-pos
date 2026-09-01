from __future__ import annotations

import frappe
from frappe.utils import flt


LEGACY_UNIT_MAP = {
	"Piece": "Piece",
	"Kg": "Kilogram",
	"Gram": "Gram",
	"Liter": "Liter",
	"Pack": "Pack",
}


def get_stock_uom(item):
	row = frappe.db.get_value(
		"Ledgix Item",
		item,
		["stock_uom", "unit"],
		as_dict=True,
	)
	if not row:
		frappe.throw(f"Item {item} does not exist.")
	return row.stock_uom or LEGACY_UNIT_MAP.get(row.unit) or "Piece"


def get_conversion_factor(item, uom=None):
	"""Return Stock UOM units represented by one unit of `uom`."""
	stock_uom = get_stock_uom(item)
	uom = uom or stock_uom
	if uom == stock_uom:
		return 1.0

	factor = frappe.db.get_value(
		"Ledgix Item UOM Conversion",
		{
			"parent": item,
			"parenttype": "Ledgix Item",
			"parentfield": "uom_conversions",
			"uom": uom,
		},
		"conversion_factor",
	)
	if factor is None or flt(factor) <= 0:
		frappe.throw(f"No valid UOM conversion from {uom} to Stock UOM {stock_uom} is configured for {item}.")
	return flt(factor)


def to_stock_qty(item, quantity, uom=None, precision=6):
	quantity = flt(quantity)
	if quantity < 0:
		frappe.throw("Quantity cannot be negative.")
	return flt(quantity * get_conversion_factor(item, uom), precision)


def from_stock_qty(item, stock_quantity, uom=None, precision=6):
	stock_quantity = flt(stock_quantity)
	if stock_quantity < 0:
		frappe.throw("Stock quantity cannot be negative.")
	factor = get_conversion_factor(item, uom)
	return flt(stock_quantity / factor if factor else 0, precision)


def get_uom_precision(uom):
	precision = frappe.db.get_value(
		"Ledgix UOM",
		{"name": uom, "is_active": 1},
		"decimal_precision",
	)
	if precision is None:
		frappe.throw(f"UOM {uom} is inactive or does not exist.")
	return max(min(int(precision or 0), 6), 0)


def normalize_quantity(item, quantity, uom=None):
	"""Return one canonical quantity payload for purchase/recipe/order adapters."""
	stock_uom = get_stock_uom(item)
	selected_uom = uom or stock_uom
	return {
		"item": item,
		"uom": selected_uom,
		"stock_uom": stock_uom,
		"quantity": flt(quantity),
		"conversion_factor": get_conversion_factor(item, selected_uom),
		"stock_quantity": to_stock_qty(item, quantity, selected_uom),
	}
