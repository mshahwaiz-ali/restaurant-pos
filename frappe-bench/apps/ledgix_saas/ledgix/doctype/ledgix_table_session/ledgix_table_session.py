from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from ledgix_saas.services.organization import ensure_branch_access


ALLOWED_TRANSITIONS = {
	"Open": {"Open", "Closing", "Closed"},
	"Closing": {"Closing", "Open", "Closed"},
	"Closed": {"Closed"},
}


class LedgixTableSession(Document):
	def before_insert(self):
		self.status = "Open"
		self.opened_at = self.opened_at or now_datetime()
		self.opened_by = self.opened_by or frappe.session.user

	def validate(self):
		table = frappe.db.get_value(
			"Ledgix Restaurant Table",
			{"name": self.restaurant_table, "is_active": 1},
			["branch", "floor"],
			as_dict=True,
		)
		if not table:
			frappe.throw("Table Session requires an active Restaurant Table.")
		ensure_branch_access(table.branch)
		self.branch = table.branch
		self.floor = table.floor
		if cint(self.covers) <= 0:
			frappe.throw("Covers must be greater than zero.")
		if self.server:
			if not frappe.db.exists("User", {"name": self.server, "enabled": 1}):
				frappe.throw("Server / Waiter must be an enabled User.")
			ensure_branch_access(self.branch, user=self.server)
		if self.customer and not frappe.db.exists("Ledgix Customer", self.customer):
			frappe.throw("Selected Customer does not exist.")
		self._validate_unique_active_table_session()
		self._validate_table_move()
		self._validate_status_transition()
		self._validate_closure()

	def _validate_unique_active_table_session(self):
		if self.status not in {"Open", "Closing"}:
			return
		filters = {
			"restaurant_table": self.restaurant_table,
			"status": ["in", ["Open", "Closing"]],
		}
		if self.name:
			filters["name"] = ["!=", self.name]
		existing = frappe.db.get_value("Ledgix Table Session", filters, "name", order_by="opened_at desc")
		if existing:
			frappe.throw(f"Restaurant Table already has active Table Session {existing}.")

	def _validate_table_move(self):
		before = self.get_doc_before_save()
		if not before or before.restaurant_table == self.restaurant_table:
			return
		if not getattr(self.flags, "allow_table_move", False):
			frappe.throw("Move a live Table Session through the table-transfer service so the change is audited.")

	def _validate_status_transition(self):
		before = self.get_doc_before_save()
		if not before:
			return
		if self.status not in ALLOWED_TRANSITIONS.get(before.status, {before.status}):
			frappe.throw(f"Table Session cannot move from {before.status} to {self.status}.")

	def _validate_closure(self):
		if self.status != "Closed":
			return
		open_order = frappe.db.get_value(
			"Ledgix Restaurant Order",
			{
				"table_session": self.name,
				"status": ["not in", ["Closed", "Voided"]],
			},
			"name",
		) if frappe.db.exists("DocType", "Ledgix Restaurant Order") else None
		if open_order:
			frappe.throw(f"Restaurant Order {open_order} must be closed or voided before closing this Table Session.")
		self.closed_at = self.closed_at or now_datetime()
		self.closed_by = self.closed_by or frappe.session.user
