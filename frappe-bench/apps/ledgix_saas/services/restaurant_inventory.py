from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.services.organization import ensure_branch_access, resolve_branch_location
from ledgix_saas.services.stock import _post_movement


UNSUPPORTED_RESTAURANT_TRACKING = {"Lot Based", "Serial Based"}


def get_standard_inventory_item(item, workflow="transfer/waste"):
	row = frappe.db.get_value(
		"Ledgix Item",
		item,
		["name", "item_code", "item_name", "active", "track_inventory", "tracking_type", "stock_uom", "cost_price", "restaurant_item_type"],
		as_dict=True,
	)
	if not row or not int(row.active or 0):
		frappe.throw(f"Inventory item {item} is inactive or missing.")
	if not int(row.track_inventory or 0):
		frappe.throw(f"Item {row.item_name or item} is not stock tracked.")
	if (row.tracking_type or "Normal") in UNSUPPORTED_RESTAURANT_TRACKING:
		frappe.throw(
			f"{row.tracking_type} item {row.item_name or item} requires identity-preserving lot/serial handling and cannot use the generic Restaurant V1 {workflow} workflow."
		)
	return row


def get_stock_count_sheet(branch=None, stock_location=None, query=None):
	"""Return countable inventory for one authoritative restaurant location."""
	branch, stock_location = resolve_branch_location(branch, stock_location)
	items = frappe.get_all(
		"Ledgix Item",
		filters={"active": 1, "track_inventory": 1},
		fields=[
			"name", "item_code", "item_name", "restaurant_item_type", "tracking_type", "stock_uom", "cost_price",
		],
		order_by="item_name asc, item_code asc",
		limit_page_length=0,
	)
	if query:
		text = str(query).strip().lower()
		items = [
			row for row in items
			if text in str(row.item_name or "").lower()
			or text in str(row.item_code or "").lower()
			or text in str(row.name or "").lower()
		]

	balances = {
		row.item: row
		for row in frappe.get_all(
			"Ledgix Stock Balance",
			filters={"branch": branch, "stock_location": stock_location},
			fields=["item", "quantity", "valuation_rate", "stock_value"],
			limit_page_length=0,
		)
	}
	countable = []
	unsupported = []
	for item in items:
		balance = balances.get(item.name)
		tracking_type = item.tracking_type or "Normal"
		row = {
			"item": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"restaurant_item_type": item.restaurant_item_type,
			"tracking_type": tracking_type,
			"uom": item.stock_uom,
			"expected_quantity": flt(balance.quantity if balance else 0, 6),
			"valuation_rate": flt(balance.valuation_rate if balance else item.cost_price, 6),
			"stock_value": flt(balance.stock_value if balance else 0, 4),
		}
		if tracking_type in UNSUPPORTED_RESTAURANT_TRACKING:
			row["reason"] = "Lot/Serial identity must be counted with an identity-preserving workflow."
			unsupported.append(row)
		else:
			countable.append(row)

	return {
		"branch": branch,
		"stock_location": stock_location,
		"items": countable,
		"unsupported_items": unsupported,
	}


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


def post_stock_count(stock_count):
	"""Set counted location balances through auditable ADJUSTMENT movements."""
	branch, stock_location = resolve_branch_location(
		stock_count.branch,
		stock_count.stock_location,
	)
	movement_meta = frappe.get_meta("Ledgix Stock Movement")
	if not movement_meta.has_field("previous_quantity"):
		frappe.throw("Stock Count requires the Stock Movement previous-quantity snapshot field. Run site migration first.")

	total_abs_variance = 0.0
	total_variance_value = 0.0
	for row in stock_count.items:
		item = get_standard_inventory_item(row.item, workflow="stock count")
		counted_qty = flt(row.counted_stock_quantity, 6)
		if counted_qty < 0:
			frappe.throw(f"Counted stock quantity for {row.item} cannot be negative.")

		movement_name = _post_movement(
			item=item.name,
			quantity=counted_qty,
			movement_type="ADJUSTMENT",
			reference_doctype="Ledgix Stock Count",
			reference_name=stock_count.name,
			source="Stock Count",
			branch=branch,
			stock_location=stock_location,
			rate=max(flt(row.valuation_rate), 0),
			note=f"{stock_count.count_type}: {stock_count.notes or ''}".rstrip(": "),
			movement_date=stock_count.count_date,
		)
		expected_qty = flt(
			frappe.db.get_value("Ledgix Stock Movement", movement_name, "previous_quantity"),
			6,
		)
		variance_qty = flt(counted_qty - expected_qty, 6)
		variance_value = flt(variance_qty * max(flt(row.valuation_rate), 0), 4)
		frappe.db.set_value(
			"Ledgix Stock Count Item",
			row.name,
			{
				"expected_quantity": expected_qty,
				"variance_quantity": variance_qty,
				"variance_value": variance_value,
			},
			update_modified=False,
		)
		total_abs_variance += abs(variance_qty)
		total_variance_value += variance_value

	frappe.db.set_value(
		"Ledgix Stock Count",
		stock_count.name,
		{
			"total_items": len(stock_count.items),
			"total_absolute_variance_quantity": flt(total_abs_variance, 6),
			"total_variance_value": flt(total_variance_value, 4),
		},
		update_modified=False,
	)
