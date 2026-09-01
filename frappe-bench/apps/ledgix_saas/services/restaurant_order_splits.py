from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from ledgix_saas.services.organization import ensure_branch_access
from ledgix_saas.services.restaurant_orders import (
	_active_order,
	_as_rows,
	_recalculate_item_tax,
	_recalculate_order,
	get_order_payload,
)


PROTECTED_KITCHEN_STATUSES = {"Fired", "Preparing", "Ready", "Served"}


def _validate_split_replay(source, destination):
	if destination.split_from_order != source.name:
		frappe.throw("Client Order ID is already used by an unrelated Restaurant Order.")
	_validate_compatible_orders(source, destination)


def _create_sibling_order(source, client_order_id):
	if not client_order_id:
		frappe.throw("Client Order ID is required for an idempotent check split.")
	existing = frappe.db.get_value("Ledgix Restaurant Order", {"client_order_id": client_order_id}, "name")
	if existing:
		destination = frappe.get_doc("Ledgix Restaurant Order", existing)
		_validate_split_replay(source, destination)
		return destination, False

	sibling = frappe.get_doc({
		"doctype": "Ledgix Restaurant Order",
		"branch": source.branch,
		"stock_location": source.stock_location,
		"order_type": source.order_type,
		"menu": source.menu,
		"price_list": source.price_list,
		"client_order_id": client_order_id,
		"split_from_order": source.name,
		"table_session": source.table_session,
		"server": source.server,
		"covers": source.covers,
		"customer": source.customer,
		"pickup_name": source.pickup_name,
		"contact_phone": source.contact_phone,
		"delivery_address": source.delivery_address,
		"delivery_instructions": source.delivery_instructions,
		"promised_at": source.promised_at,
		"order_notes": source.order_notes,
	})
	sibling.insert(ignore_permissions=True)
	return sibling, True


def _validate_compatible_orders(source, destination):
	ensure_branch_access(source.branch)
	ensure_branch_access(destination.branch)
	for fieldname in ("branch", "stock_location", "order_type", "menu", "price_list", "table_session"):
		if source.get(fieldname) != destination.get(fieldname):
			frappe.throw(f"Checks cannot be combined because {source.meta.get_label(fieldname)} differs.")
	if source.linked_sale or destination.linked_sale:
		frappe.throw("Settled checks cannot be split or merged.")


def _move_full_item(item, destination_order):
	item.restaurant_order = destination_order
	item.flags.allow_check_move = True
	item.save(ignore_permissions=True)


def _copy_partial_item(item, destination_order, split_quantity):
	if flt(item.fired_quantity) > 0 or item.kitchen_status in PROTECTED_KITCHEN_STATUSES:
		frappe.throw(
			f"Order Item {item.name} has kitchen activity. Split the complete line instead of partially splitting its quantity."
		)
	remaining = flt(item.billable_quantity)
	if split_quantity <= 0 or split_quantity >= remaining:
		frappe.throw("Partial split quantity must be greater than zero and below the line's billable quantity.")
	if flt(item.void_quantity) > 0:
		frappe.throw("Partially voided lines cannot be quantity-split; move the complete line or create a clean replacement line.")

	clone = frappe.copy_doc(item)
	clone.restaurant_order = destination_order
	clone.origin_order = item.origin_order or item.restaurant_order
	clone.origin_order_item = item.origin_order_item or item.name
	clone.client_item_id = None
	clone.quantity = split_quantity
	clone.void_quantity = 0
	clone.billable_quantity = split_quantity
	clone.fired_quantity = 0
	clone.prepared_quantity = 0
	clone.ready_quantity = 0
	clone.served_quantity = 0
	clone.kitchen_status = "Held" if cint(item.is_course_held) else "Not Sent"
	clone.is_voided = 0
	clone.void_reason = None
	clone.voided_by = None
	clone.voided_at = None
	clone.flags.from_restaurant_order_service = True
	clone.insert(ignore_permissions=True)
	_recalculate_item_tax(clone)
	clone.flags.allow_operational_mutation = True
	clone.save(ignore_permissions=True)

	item.quantity = flt(item.quantity - split_quantity, 6)
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	_recalculate_item_tax(item)
	item.flags.allow_operational_mutation = True
	item.save(ignore_permissions=True)
	return clone


def split_check_by_items(source_order, selections, client_order_id, reason=None):
	source = _active_order(source_order)
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw("Split reason is required.")
	if not client_order_id:
		frappe.throw("Client Order ID is required for an idempotent check split.")

	existing = frappe.db.get_value("Ledgix Restaurant Order", {"client_order_id": client_order_id}, "name")
	if existing:
		destination = frappe.get_doc("Ledgix Restaurant Order", existing)
		_validate_split_replay(source, destination)
		return {
			"source": get_order_payload(source.name),
			"split": get_order_payload(destination.name),
			"idempotent_replay": True,
		}

	rows = _as_rows(selections)
	if not rows:
		frappe.throw("Select at least one Restaurant Order Item to split.")

	destination, _created = _create_sibling_order(source, client_order_id)
	_validate_compatible_orders(source, destination)
	seen = set()
	for selection in rows:
		if isinstance(selection, str):
			item_name = selection
			requested_qty = None
		else:
			item_name = selection.get("order_item") or selection.get("item") or selection.get("name")
			requested_qty = selection.get("quantity")
		if not item_name or item_name in seen:
			frappe.throw("Each split selection must reference a unique Restaurant Order Item.")
		seen.add(item_name)
		item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
		if item.restaurant_order != source.name:
			frappe.throw(f"Order Item {item.name} does not belong to source check {source.name}.")
		if cint(item.is_voided) or flt(item.billable_quantity) <= 0:
			frappe.throw(f"Voided Order Item {item.name} cannot be split.")
		qty = flt(requested_qty) if requested_qty is not None else flt(item.billable_quantity)
		if qty <= 0 or qty > flt(item.billable_quantity):
			frappe.throw(f"Invalid split quantity for Order Item {item.name}.")
		if abs(qty - flt(item.billable_quantity)) <= 0.000001:
			_move_full_item(item, destination.name)
		else:
			_copy_partial_item(item, destination.name, qty)

	_recalculate_order(source.name)
	_recalculate_order(destination.name)
	return {
		"source": get_order_payload(source.name),
		"split": get_order_payload(destination.name),
		"idempotent_replay": False,
	}


def split_check_by_seat(source_order, seat_no, client_order_id, reason=None):
	seat_no = cint(seat_no)
	if seat_no <= 0:
		frappe.throw("Seat number must be greater than zero.")
	items = frappe.get_all(
		"Ledgix Restaurant Order Item",
		filters={
			"restaurant_order": source_order,
			"seat_no": seat_no,
			"is_voided": 0,
		},
		pluck="name",
		order_by="creation asc",
		limit_page_length=0,
	)
	if not items:
		frappe.throw(f"No billable items are assigned to seat {seat_no}.")
	return split_check_by_items(
		source_order,
		[{"order_item": name} for name in items],
		client_order_id,
		reason=reason or f"Split seat {seat_no}",
	)


def merge_checks(source_order, destination_order, reason=None):
	if source_order == destination_order:
		return get_order_payload(destination_order)

	source_snapshot = frappe.get_doc("Ledgix Restaurant Order", source_order)
	ensure_branch_access(source_snapshot.branch)
	if source_snapshot.status == "Voided" and str(source_snapshot.void_reason or "").startswith(f"Merged into {destination_order}:"):
		return get_order_payload(destination_order)

	source = _active_order(source_order)
	destination = _active_order(destination_order)
	_validate_compatible_orders(source, destination)
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw("Merge reason is required.")
	if any(flt(source.get(field)) for field in ("discount_amount", "service_charge", "tip_amount")):
		frappe.throw("Source check has order-level adjustments. Remove or deliberately reallocate them before merging.")

	item_names = frappe.get_all(
		"Ledgix Restaurant Order Item",
		filters={"restaurant_order": source.name},
		pluck="name",
		order_by="creation asc",
		limit_page_length=0,
	)
	for item_name in item_names:
		item = frappe.get_doc("Ledgix Restaurant Order Item", item_name)
		_move_full_item(item, destination.name)

	_recalculate_order(destination.name)
	_recalculate_order(source.name)
	source.status = "Voided"
	source.void_reason = f"Merged into {destination.name}: {reason}"
	source.flags.allow_status_transition = True
	source.save(ignore_permissions=True)
	return get_order_payload(destination.name)
