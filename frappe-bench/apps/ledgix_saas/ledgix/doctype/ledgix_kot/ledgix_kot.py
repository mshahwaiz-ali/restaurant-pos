from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from ledgix_saas.services.organization import ensure_branch_access


DISPATCH_FIELDS = (
	"restaurant_order",
	"table_session",
	"branch",
	"stock_location",
	"action",
	"source_kot",
	"client_fire_id",
	"order_type",
	"restaurant_table_snapshot",
	"table_name_snapshot",
	"server_snapshot",
	"fired_at",
	"fired_by",
	"note",
)


class LedgixKOT(Document):
	def before_insert(self):
		if not getattr(self.flags, "from_kitchen_service", False):
			frappe.throw("KOTs must be created through the kitchen dispatch service.", frappe.PermissionError)
		self.fired_at = self.fired_at or now_datetime()
		self.fired_by = self.fired_by or frappe.session.user
		self.status = self.status or "New"

	def validate(self):
		ensure_branch_access(self.branch)
		order = frappe.db.get_value(
			"Ledgix Restaurant Order",
			self.restaurant_order,
			["branch", "stock_location", "table_session"],
			as_dict=True,
		)
		if not order or order.branch != self.branch or order.stock_location != self.stock_location:
			frappe.throw("KOT must retain the Restaurant Order branch and stock-location context.")
		if order.table_session != self.table_session:
			frappe.throw("KOT Table Session snapshot does not match the Restaurant Order.")
		self._protect_dispatch_snapshot()

	def _protect_dispatch_snapshot(self):
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [field for field in DISPATCH_FIELDS if before.get(field) != self.get(field)]
		if changed:
			frappe.throw("KOT dispatch history is immutable.", frappe.PermissionError)
		if before.status != self.status and not getattr(self.flags, "allow_kitchen_state_transition", False):
			frappe.throw("KOT state must be changed through the KDS service.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("KOT dispatch history cannot be deleted.", frappe.PermissionError)
