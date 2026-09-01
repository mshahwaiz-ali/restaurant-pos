from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.api.security import require_ledgix_manager_or_above


def _rows(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or [])


def _transfer_payload(name):
	doc = frappe.get_doc("Ledgix Stock Transfer", name)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"source_branch": doc.source_branch,
		"source_stock_location": doc.source_stock_location,
		"destination_branch": doc.destination_branch,
		"destination_stock_location": doc.destination_stock_location,
		"total_stock_quantity": flt(doc.total_stock_quantity, 6),
		"total_stock_value": flt(doc.total_stock_value, 4),
		"items": [row.as_dict() for row in doc.items],
	}


def _waste_payload(name):
	doc = frappe.get_doc("Ledgix Inventory Waste", name)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"branch": doc.branch,
		"stock_location": doc.stock_location,
		"waste_type": doc.waste_type,
		"total_stock_quantity": flt(doc.total_stock_quantity, 6),
		"total_waste_value": flt(doc.total_waste_value, 4),
		"items": [row.as_dict() for row in doc.items],
	}


def _count_payload(name):
	doc = frappe.get_doc("Ledgix Stock Count", name)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"count_date": doc.count_date,
		"branch": doc.branch,
		"stock_location": doc.stock_location,
		"count_type": doc.count_type,
		"total_items": int(doc.total_items or 0),
		"total_absolute_variance_quantity": flt(doc.total_absolute_variance_quantity, 6),
		"total_variance_value": flt(doc.total_variance_value, 4),
		"items": [row.as_dict() for row in doc.items],
	}


@frappe.whitelist()
def transfer_stock(
	source_stock_location,
	destination_stock_location,
	items,
	reason,
	client_transfer_id,
	source_branch=None,
	destination_branch=None,
	transfer_date=None,
	notes=None,
):
	require_ledgix_manager_or_above()
	if not client_transfer_id:
		frappe.throw("Client Transfer ID is required for idempotent Stock Transfer.")
	existing = frappe.db.get_value(
		"Ledgix Stock Transfer",
		{"client_transfer_id": client_transfer_id},
		["name", "docstatus"],
		as_dict=True,
	)
	if existing:
		if int(existing.docstatus or 0) == 1:
			return {**_transfer_payload(existing.name), "idempotent_replay": True}
		frappe.throw(f"Stock Transfer {existing.name} already exists in a non-submitted state and requires review.")

	doc = frappe.new_doc("Ledgix Stock Transfer")
	doc.client_transfer_id = client_transfer_id
	doc.source_branch = source_branch
	doc.source_stock_location = source_stock_location
	doc.destination_branch = destination_branch
	doc.destination_stock_location = destination_stock_location
	doc.transfer_date = transfer_date
	doc.reason = reason
	doc.notes = notes
	for row in _rows(items):
		doc.append("items", {
			"item": row.get("item"),
			"quantity": flt(row.get("quantity")),
			"uom": row.get("uom"),
		})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {**_transfer_payload(doc.name), "idempotent_replay": False}


@frappe.whitelist()
def record_waste(
	stock_location,
	items,
	waste_type,
	reason,
	client_waste_id,
	branch=None,
	waste_date=None,
	notes=None,
):
	require_ledgix_manager_or_above()
	if not client_waste_id:
		frappe.throw("Client Waste ID is required for idempotent Inventory Waste.")
	existing = frappe.db.get_value(
		"Ledgix Inventory Waste",
		{"client_waste_id": client_waste_id},
		["name", "docstatus"],
		as_dict=True,
	)
	if existing:
		if int(existing.docstatus or 0) == 1:
			return {**_waste_payload(existing.name), "idempotent_replay": True}
		frappe.throw(f"Inventory Waste {existing.name} already exists in a non-submitted state and requires review.")

	doc = frappe.new_doc("Ledgix Inventory Waste")
	doc.client_waste_id = client_waste_id
	doc.branch = branch
	doc.stock_location = stock_location
	doc.waste_date = waste_date
	doc.waste_type = waste_type
	doc.reason = reason
	doc.notes = notes
	for row in _rows(items):
		doc.append("items", {
			"item": row.get("item"),
			"quantity": flt(row.get("quantity")),
			"uom": row.get("uom"),
		})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {**_waste_payload(doc.name), "idempotent_replay": False}


@frappe.whitelist()
def record_stock_count(
	stock_location,
	items,
	client_count_id,
	branch=None,
	count_date=None,
	count_type="Cycle Count",
	notes=None,
):
	require_ledgix_manager_or_above()
	if not client_count_id:
		frappe.throw("Client Count ID is required for idempotent Stock Count.")
	existing = frappe.db.get_value(
		"Ledgix Stock Count",
		{"client_count_id": client_count_id},
		["name", "docstatus"],
		as_dict=True,
	)
	if existing:
		if int(existing.docstatus or 0) == 1:
			return {**_count_payload(existing.name), "idempotent_replay": True}
		frappe.throw(f"Stock Count {existing.name} already exists in a non-submitted state and requires review.")

	doc = frappe.new_doc("Ledgix Stock Count")
	doc.client_count_id = client_count_id
	doc.branch = branch
	doc.stock_location = stock_location
	doc.count_date = count_date
	doc.count_type = count_type or "Cycle Count"
	doc.notes = notes
	for row in _rows(items):
		if "counted_quantity" in row:
			counted_quantity = row.get("counted_quantity")
		elif "quantity" in row:
			counted_quantity = row.get("quantity")
		else:
			frappe.throw(f"Counted Quantity is required for Stock Count item {row.get('item') or ''}.")
		doc.append("items", {
			"item": row.get("item"),
			"counted_quantity": flt(counted_quantity),
			"count_confirmed": 1,
			"uom": row.get("uom"),
		})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {**_count_payload(doc.name), "idempotent_replay": False}
