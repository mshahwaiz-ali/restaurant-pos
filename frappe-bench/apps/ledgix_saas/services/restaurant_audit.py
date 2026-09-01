from __future__ import annotations

import json

import frappe

from ledgix_saas.services.organization import ensure_branch_access


def _compact_metadata(metadata):
	if not metadata:
		return None
	return json.dumps(metadata, default=str, separators=(",", ":"), sort_keys=True)


def log_restaurant_operation(
	operation,
	*,
	branch,
	reason=None,
	request_id=None,
	table_session=None,
	restaurant_order=None,
	restaurant_order_item=None,
	source_order=None,
	destination_order=None,
	metadata=None,
):
	"""Create one immutable audit row.

	If request_id is supplied, the same protected operation can safely replay
	without duplicating its audit record. The caller still owns business-operation
	idempotency; this helper provides durable audit idempotency.
	"""
	ensure_branch_access(branch)
	if request_id:
		existing = frappe.db.get_value("Ledgix Restaurant Operation Log", {"request_id": request_id}, "name")
		if existing:
			return existing

	doc = frappe.get_doc({
		"doctype": "Ledgix Restaurant Operation Log",
		"operation": operation,
		"branch": branch,
		"request_id": request_id,
		"table_session": table_session,
		"restaurant_order": restaurant_order,
		"restaurant_order_item": restaurant_order_item,
		"source_order": source_order,
		"destination_order": destination_order,
		"reason": str(reason or "").strip(),
		"metadata_json": _compact_metadata(metadata),
	})
	doc.flags.from_restaurant_operation_service = True
	doc.insert(ignore_permissions=True)
	return doc.name
