from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.api.security import require_ledgix_manager_or_above
from ledgix_saas.services.purchase_orders import purchase_order_payload, receive_purchase_order


def _rows(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or [])


@frappe.whitelist()
def create(
	supplier,
	branch,
	stock_location,
	items,
	client_purchase_order_id,
	order_date=None,
	expected_date=None,
	supplier_reference=None,
	notes=None,
	submit=1,
):
	require_ledgix_manager_or_above()
	if not client_purchase_order_id:
		frappe.throw("Client Purchase Order ID is required for idempotent creation.")
	existing = frappe.db.get_value(
		"Ledgix Purchase Order",
		{"client_purchase_order_id": client_purchase_order_id},
		["name", "docstatus"],
		as_dict=True,
	)
	if existing:
		return {**purchase_order_payload(existing.name), "idempotent_replay": True}

	doc = frappe.new_doc("Ledgix Purchase Order")
	doc.client_purchase_order_id = client_purchase_order_id
	doc.supplier = supplier
	doc.branch = branch
	doc.stock_location = stock_location
	doc.order_date = order_date
	doc.expected_date = expected_date
	doc.supplier_reference = supplier_reference
	doc.notes = notes
	for row in _rows(items):
		doc.append("items", {
			"item": row.get("item"),
			"quantity": flt(row.get("quantity")),
			"uom": row.get("uom"),
			"rate": flt(row.get("rate")),
		})
	doc.insert(ignore_permissions=True)
	if int(submit or 0):
		doc.submit()
	return {**purchase_order_payload(doc.name), "idempotent_replay": False}


@frappe.whitelist()
def receive(purchase_order, items, client_receipt_id, purchase_date=None):
	require_ledgix_manager_or_above()
	return receive_purchase_order(
		purchase_order,
		items,
		client_receipt_id,
		purchase_date=purchase_date,
	)


@frappe.whitelist()
def get(purchase_order):
	require_ledgix_manager_or_above()
	return purchase_order_payload(purchase_order)
