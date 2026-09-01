from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.services.organization import ensure_branch_access, resolve_branch_location
from ledgix_saas.services.stock import _post_movement


UNSUPPORTED_RESTAURANT_TRACKING = {"Lot Based", "Serial Based"}


def get_standard_inventory_item(item):
	row = frappe.db.get_value(
		"Ledgix Item",
		item,
		["name", "item_name", "active", "track_inventory", "tracking_type", "stock_uom", "cost_price"],
		as_dict=True,
	)
	if not row or not int(row.active or 0):
		frappe.throw(f"Inventory item {item} is inactive or missing.")
	if not int(row.track_inventory or 0):
		frappe.throw(f"Item {row.item_name or item} is not stock tracked.")
	if (row.tracking_type or "Normal") in UNSUPPORTED_RESTAURANT_TRACKING:
		frappe.throw(
			f"{row.tracking_type} item {row.item_name or item} requires identity-preserving lot/serial handling and cannot use the generic Restaurant V1 transfer/waste workflow."
		)
	return row


def normalize_transfer_context(source_branch, source_location, destination_branch, destination_location):
	source_branch, source_location = resolve_branch_location(
		source_branch,
		source_location,
		purpose="consumption",
	)
	destination_branch, destination_location = resolve_branch_location(
		destination_branch,
		destination_location,
		purpose="receiving",
	)
	if source_location == destination_location:
		frappe.throw("Source and Destination Stock Locations must be different.")
	return source_branch, source_location, destination_branch, destination_location


def post_stock_transfer(transfer):
	"""Post one paired OUT/IN event per item using Stock Movement as truth."""
	source_branch, source_location, destination_branch, destination_location = normalize_transfer_context(
		transfer.source_branch,
		transfer.source_stock_location,
		transfer.destination_branch,
		transfer.destination_stock_location,
	)
	for row in transfer.items:
		item = get_standard_inventory_item(row.item)
		qty = flt(row.stock_quantity, 6)
		if qty <= 0:
			frappe.throw(f"Transfer quantity for {row.item} must be greater than zero.")
		rate = max(flt(row.valuation_rate), 0)
		_post_movement(
			item=item.name,
			quantity=qty,
			movement_type="OUT",
			reference_doctype="Ledgix Stock Transfer",
			reference_name=transfer.name,
			source="Transfer OUT",
			branch=source_branch,
			stock_location=source_location,
			rate=rate,
			note=transfer.reason,
			movement_date=transfer.transfer_date,
		)
		_post_movement(
			item=item.name,
			quantity=qty,
			movement_type="IN",
			reference_doctype="Ledgix Stock Transfer",
			reference_name=transfer.name,
			source="Transfer IN",
			branch=destination_branch,
			stock_location=destination_location,
			rate=rate,
			note=transfer.reason,
			movement_date=transfer.transfer_date,
		)


def cancel_stock_transfer(transfer):
	"""Reverse destination IN first so spent destination stock blocks unsafe cancellation."""
	ensure_branch_access(transfer.source_branch)
	ensure_branch_access(transfer.destination_branch)
	movements = frappe.get_all(
		"Ledgix Stock Movement",
		filters={
			"reference_doctype": "Ledgix Stock Transfer",
			"reference_name": transfer.name,
			"docstatus": 1,
		},
		fields=["name", "movement_type"],
		limit_page_length=0,
	)
	incoming = [row.name for row in movements if row.movement_type == "IN"]
	outgoing = [row.name for row in movements if row.movement_type == "OUT"]
	for movement_name in incoming + outgoing:
		frappe.get_doc("Ledgix Stock Movement", movement_name).cancel()


def post_inventory_waste(waste):
	branch, stock_location = resolve_branch_location(
		waste.branch,
		waste.stock_location,
		purpose="consumption",
	)
	for row in waste.items:
		item = get_standard_inventory_item(row.item)
		qty = flt(row.stock_quantity, 6)
		if qty <= 0:
			frappe.throw(f"Waste quantity for {row.item} must be greater than zero.")
		_post_movement(
			item=item.name,
			quantity=qty,
			movement_type="OUT",
			reference_doctype="Ledgix Inventory Waste",
			reference_name=waste.name,
			source="Waste",
			branch=branch,
			stock_location=stock_location,
			rate=max(flt(row.valuation_rate), 0),
			note=f"{waste.waste_type}: {waste.reason}",
			movement_date=waste.waste_date,
		)


def cancel_inventory_waste(waste):
	ensure_branch_access(waste.branch)
	movements = frappe.get_all(
		"Ledgix Stock Movement",
		filters={
			"reference_doctype": "Ledgix Inventory Waste",
			"reference_name": waste.name,
			"movement_type": "OUT",
			"docstatus": 1,
		},
		pluck="name",
		limit_page_length=0,
	)
	for movement_name in movements:
		frappe.get_doc("Ledgix Stock Movement", movement_name).cancel()
