from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


STATE_TRANSITIONS = {
	"New": {"New", "Preparing", "Ready", "Voided", "Recalled"},
	"Preparing": {"Preparing", "Ready", "Voided"},
	"Ready": {"Ready", "Bumped", "Voided"},
	"Bumped": {"Bumped"},
	"Voided": {"Voided"},
	"Recalled": {"Recalled", "New", "Preparing", "Ready"},
}
DISPATCH_FIELDS = (
	"kot",
	"restaurant_order",
	"restaurant_order_item",
	"kitchen_station",
	"dispatch_key",
	"action",
	"quantity",
	"item",
	"item_name_snapshot",
	"seat_no",
	"course",
	"is_course_held",
	"kitchen_note",
	"modifier_summary",
	"queued_at",
	"recipe",
	"recipe_version",
)
CONSUMPTION_FIELDS = (
	"consumption_status",
	"consumption_posted_at",
	"consumption_reversed_at",
)


class LedgixKOTItem(Document):
	def before_insert(self):
		if not getattr(self.flags, "from_kitchen_service", False):
			frappe.throw("KOT Items must be created through the kitchen dispatch service.", frappe.PermissionError)
		self.queued_at = self.queued_at or now_datetime()
		self.status = self.status or "New"
		self.dispatch_key = self.dispatch_key or f"{self.kot}::{self.restaurant_order_item}::{self.action}::{self.kitchen_station}"

	def validate(self):
		if flt(self.quantity) <= 0:
			frappe.throw("KOT Item quantity must be greater than zero.")
		kot = frappe.db.get_value(
			"Ledgix KOT",
			self.kot,
			["restaurant_order", "branch", "action"],
			as_dict=True,
		)
		if not kot or kot.restaurant_order != self.restaurant_order or kot.action != self.action:
			frappe.throw("KOT Item must retain its KOT order/action context.")
		station_branch = frappe.db.get_value(
			"Ledgix Kitchen Station",
			{"name": self.kitchen_station, "is_active": 1},
			"branch",
		)
		if station_branch != kot.branch:
			frappe.throw("KOT Item Kitchen Station must be active and belong to the KOT Branch.")
		order_item = frappe.db.get_value(
			"Ledgix Restaurant Order Item",
			self.restaurant_order_item,
			["restaurant_order", "item"],
			as_dict=True,
		)
		if not order_item or order_item.restaurant_order != self.restaurant_order or order_item.item != self.item:
			frappe.throw("KOT Item does not match the referenced Restaurant Order Item.")
		self._protect_dispatch_snapshot()
		self._validate_state_transition()
		self._protect_consumption_state()

	def _protect_dispatch_snapshot(self):
		before = self.get_doc_before_save()
		if not before:
			return
		if any(before.get(field) != self.get(field) for field in DISPATCH_FIELDS):
			frappe.throw("KOT Item dispatch snapshot is immutable.", frappe.PermissionError)

	def _validate_state_transition(self):
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if not getattr(self.flags, "allow_kitchen_state_transition", False):
			frappe.throw("KOT Item state must be changed through the KDS service.", frappe.PermissionError)
		if self.status not in STATE_TRANSITIONS.get(before.status, {before.status}):
			frappe.throw(f"KOT Item cannot move from {before.status} to {self.status}.")

	def _protect_consumption_state(self):
		before = self.get_doc_before_save()
		if not before:
			return
		if any(before.get(field) != self.get(field) for field in CONSUMPTION_FIELDS):
			if not getattr(self.flags, "allow_consumption_state_update", False):
				frappe.throw("KOT Item consumption state is service-owned.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("KOT Items cannot be deleted from immutable dispatch history.", frappe.PermissionError)
