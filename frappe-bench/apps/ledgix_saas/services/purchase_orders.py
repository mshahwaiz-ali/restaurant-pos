from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, nowdate

from ledgix_saas.services.organization import ensure_branch_access
from ledgix_saas.services.uom import to_stock_qty


TRACKED_TYPES = {"Lot Based", "Serial Based"}


def _parse_rows(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or [])


def purchase_order_payload(name):
	doc = frappe.get_doc("Ledgix Purchase Order", name)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"supplier": doc.supplier,
		"branch": doc.branch,
		"stock_location": doc.stock_location,
		"order_date": doc.order_date,
		"expected_date": doc.expected_date,
		"subtotal": flt(doc.subtotal, 2),
		"received_percent": flt(doc.received_percent, 2),
		"items": [row.as_dict() for row in doc.items],
	}


def _lock_purchase_order(name):
	rows = frappe.db.sql(
		"""
		SELECT name, docstatus, status, supplier, branch, stock_location
		FROM `tabLedgix Purchase Order`
		WHERE name=%s
		FOR UPDATE
		""",
		(name,),
		as_dict=True,
	)
	if not rows:
		frappe.throw("Purchase Order was not found.")
	return rows[0]


def refresh_purchase_order_receipt_status(purchase_order):
	if not purchase_order or not frappe.db.exists("Ledgix Purchase Order", purchase_order):
		return
	po = frappe.get_doc("Ledgix Purchase Order", purchase_order)
	if po.docstatus != 1:
		return

	received = {}
	if frappe.get_meta("Ledgix Purchase").has_field("purchase_order") and frappe.get_meta("Ledgix Purchase Item").has_field("purchase_order_item"):
		rows = frappe.db.sql(
			"""
			SELECT pi.purchase_order_item, COALESCE(SUM(pi.quantity), 0) AS received_qty
			FROM `tabLedgix Purchase Item` pi
			INNER JOIN `tabLedgix Purchase` p ON p.name = pi.parent
			WHERE p.docstatus = 1
			  AND p.purchase_order = %s
			  AND COALESCE(pi.purchase_order_item, '') != ''
			GROUP BY pi.purchase_order_item
			""",
			(purchase_order,),
			as_dict=True,
		)
		received = {row.purchase_order_item: flt(row.received_qty, 6) for row in rows}

	total_ordered = 0.0
	total_received = 0.0
	all_received = True
	any_received = False
	for row in po.items:
		ordered = flt(row.stock_quantity, 6)
		received_qty = min(max(flt(received.get(row.name), 6), 0), ordered)
		outstanding = flt(max(ordered - received_qty, 0), 6)
		frappe.db.set_value(
			"Ledgix Purchase Order Item",
			row.name,
			{
				"received_stock_quantity": received_qty,
				"outstanding_stock_quantity": outstanding,
			},
			update_modified=False,
		)
		total_ordered += ordered
		total_received += received_qty
		any_received = any_received or received_qty > 0.000001
		all_received = all_received and outstanding <= 0.000001

	if all_received and po.items:
		status = "Received"
	elif any_received:
		status = "Partially Received"
	else:
		status = "Open"
	percent = flt((total_received / total_ordered * 100) if total_ordered else 0, 2)
	frappe.db.set_value(
		"Ledgix Purchase Order",
		po.name,
		{"status": status, "received_percent": percent},
		update_modified=False,
	)


def sync_purchase_order_receipt_status(doc, method=None):
	purchase_order = doc.get("purchase_order") if hasattr(doc, "get") else None
	if purchase_order:
		refresh_purchase_order_receipt_status(purchase_order)


def validate_purchase_order_cancel(po):
	if not frappe.get_meta("Ledgix Purchase").has_field("purchase_order"):
		return
	receipt = frappe.db.get_value(
		"Ledgix Purchase",
		{"purchase_order": po.name, "docstatus": 1},
		"name",
	)
	if receipt:
		frappe.throw(f"Purchase Order cannot be cancelled while submitted receipt {receipt} exists. Cancel the receipt first.")


def receive_purchase_order(
	purchase_order,
	items,
	client_receipt_id,
	*,
	purchase_date=None,
):
	if not client_receipt_id:
		frappe.throw("Client Receipt ID is required for idempotent Purchase Order receiving.")
	locked = _lock_purchase_order(purchase_order)
	if int(locked.docstatus or 0) != 1 or locked.status not in {"Open", "Partially Received"}:
		frappe.throw(f"Purchase Order {purchase_order} is not open for receiving.")
	ensure_branch_access(locked.branch)

	existing = frappe.db.get_value(
		"Ledgix Purchase",
		{"client_receipt_id": client_receipt_id},
		["name", "purchase_order", "docstatus"],
		as_dict=True,
	) if frappe.get_meta("Ledgix Purchase").has_field("client_receipt_id") else None
	if existing:
		if existing.purchase_order != purchase_order:
			frappe.throw("Client Receipt ID is already used by another Purchase Order.")
		if int(existing.docstatus or 0) == 1:
			refresh_purchase_order_receipt_status(purchase_order)
			return {
				"purchase": existing.name,
				"purchase_order": purchase_order_payload(purchase_order),
				"idempotent_replay": True,
			}
		frappe.throw(f"Purchase receipt draft {existing.name} already exists and requires review.")

	po = frappe.get_doc("Ledgix Purchase Order", purchase_order)
	by_name = {row.name: row for row in po.items}
	by_item = {row.item: row for row in po.items}
	requested_rows = _parse_rows(items)
	if not requested_rows:
		frappe.throw("Select at least one Purchase Order item to receive.")

	prepared = []
	seen = set()
	for requested in requested_rows:
		row = by_name.get(requested.get("purchase_order_item")) or by_item.get(requested.get("item"))
		if not row:
			frappe.throw("Receipt item does not belong to the Purchase Order.")
		if row.name in seen:
			frappe.throw(f"Purchase Order Item {row.name} is repeated in the receipt.")
		seen.add(row.name)
		quantity = flt(requested.get("quantity"), 6)
		if quantity <= 0:
			frappe.throw(f"Receipt quantity for {row.item} must be greater than zero.")
		stock_qty = flt(to_stock_qty(row.item, quantity, row.uom), 6)
		outstanding = flt(row.outstanding_stock_quantity, 6)
		if stock_qty > outstanding + 0.000001:
			frappe.throw(
				f"Receipt quantity for {row.item} exceeds Purchase Order outstanding quantity {outstanding:g} {row.stock_uom_snapshot}."
			)
		item_meta = frappe.db.get_value(
			"Ledgix Item",
			row.item,
			["tracking_type", "stock_uom", "active", "track_inventory"],
			as_dict=True,
		)
		if not item_meta or not int(item_meta.active or 0) or not int(item_meta.track_inventory or 0):
			frappe.throw(f"Purchase Order item {row.item} is no longer an active stock item.")
		if (item_meta.tracking_type or "Normal") in TRACKED_TYPES:
			frappe.throw(
				f"{item_meta.tracking_type} item {row.item} requires the identity-aware Purchase receiving flow and cannot be auto-received from this Purchase Order endpoint."
			)
		prepared.append({
			"po_row": row,
			"stock_quantity": stock_qty,
			"stock_uom": row.stock_uom_snapshot or item_meta.stock_uom,
			"stock_rate": flt(row.stock_rate, 6),
		})

	purchase = frappe.new_doc("Ledgix Purchase")
	purchase.supplier = po.supplier
	purchase.purchase_date = getdate(purchase_date or nowdate())
	purchase.branch = po.branch
	purchase.stock_location = po.stock_location
	purchase.purchase_order = po.name
	purchase.client_receipt_id = client_receipt_id
	for prepared_row in prepared:
		row = prepared_row["po_row"]
		purchase.append("items", {
			"item": row.item,
			"quantity": prepared_row["stock_quantity"],
			"rate": prepared_row["stock_rate"],
			"unit": prepared_row["stock_uom"],
			"purchase_order_item": row.name,
		})
	purchase.insert(ignore_permissions=True)
	purchase.submit()
	refresh_purchase_order_receipt_status(po.name)
	return {
		"purchase": purchase.name,
		"purchase_order": purchase_order_payload(po.name),
		"idempotent_replay": False,
	}
