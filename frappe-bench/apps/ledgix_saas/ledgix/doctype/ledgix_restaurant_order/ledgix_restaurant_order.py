from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from ledgix_saas.services.organization import ensure_branch_access, resolve_branch_location


FINAL_STATUSES = {"Closed", "Voided"}


class LedgixRestaurantOrder(Document):
	def before_insert(self):
		self.status = "Open"
		self.opened_at = self.opened_at or now_datetime()
		self.opened_by = self.opened_by or frappe.session.user
		self.cashier = self.cashier or frappe.session.user

	def validate(self):
		self.branch, self.stock_location = resolve_branch_location(
			self.branch,
			self.stock_location,
			purpose="consumption",
		)
		ensure_branch_access(self.branch)
		self._validate_order_type_context()
		self._validate_menu_context()
		self._validate_people()
		self._validate_immutable_context()
		self._validate_status_change()
		self._validate_final_state()

	def _validate_order_type_context(self):
		if self.order_type == "Dine In":
			if not self.table_session:
				frappe.throw("Dine In orders require a Table Session.")
			session = frappe.db.get_value(
				"Ledgix Table Session",
				{"name": self.table_session, "status": ["in", ["Open", "Closing"]]},
				["branch", "restaurant_table", "covers", "server", "customer"],
				as_dict=True,
			)
			if not session or session.branch != self.branch:
				frappe.throw("Table Session must be open and belong to the Order Branch.")
			self.restaurant_table = session.restaurant_table
			self.table_name_snapshot = frappe.db.get_value("Ledgix Restaurant Table", session.restaurant_table, "table_name") or session.restaurant_table
			self.covers = cint(self.covers) or cint(session.covers) or 1
			self.server = self.server or session.server
			self.customer = self.customer or session.customer
		else:
			self.table_session = None
			self.restaurant_table = None
			self.table_name_snapshot = None
			self.covers = max(cint(self.covers), 1)
			if self.order_type == "Delivery" and not str(self.delivery_address or "").strip():
				frappe.throw("Delivery orders require a Delivery Address.")

	def _validate_menu_context(self):
		if not frappe.db.exists("Ledgix Menu", {"name": self.menu, "is_active": 1}):
			frappe.throw("Order Menu must be active.")
		if not frappe.db.exists(
			"Ledgix Branch Menu",
			{"branch": self.branch, "menu": self.menu, "is_active": 1},
		):
			frappe.throw("Selected Menu is not actively assigned to this Branch.")
		if not self.price_list or not frappe.db.exists("Ledgix Price List", {"name": self.price_list, "enabled": 1}):
			frappe.throw("Order Price List snapshot must be enabled.")

	def _validate_people(self):
		for fieldname, label in (("server", "Server / Waiter"), ("cashier", "Cashier")):
			user = self.get(fieldname)
			if user and not frappe.db.exists("User", {"name": user, "enabled": 1}):
				frappe.throw(f"{label} must be an enabled User.")
		if self.customer and not frappe.db.exists("Ledgix Customer", self.customer):
			frappe.throw("Selected Customer does not exist.")

	def _validate_immutable_context(self):
		before = self.get_doc_before_save()
		if not before:
			return
		item_exists = bool(frappe.db.exists("Ledgix Restaurant Order Item", {"restaurant_order": self.name})) if frappe.db.exists("DocType", "Ledgix Restaurant Order Item") else False
		if item_exists:
			for fieldname in ("branch", "stock_location", "order_type", "menu", "price_list", "table_session"):
				if self.get(fieldname) != before.get(fieldname):
					frappe.throw(f"{self.meta.get_label(fieldname)} cannot change after Order Items exist.")
		if before.linked_sale and self.linked_sale != before.linked_sale:
			frappe.throw("Final Sale link cannot be replaced once set.")

	def _validate_status_change(self):
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if not getattr(self.flags, "allow_status_transition", False):
			frappe.throw("Restaurant Order status must be changed through an operational service so the transition is audited.")
		if before.status in FINAL_STATUSES:
			frappe.throw(f"Restaurant Order {before.status} is final and cannot transition again.")

	def _validate_final_state(self):
		if self.status == "Voided" and not str(self.void_reason or "").strip():
			frappe.throw("Void Reason is required for a voided Restaurant Order.")
		if self.status == "Closed":
			if not self.linked_sale:
				frappe.throw("Closed Restaurant Orders require a linked finalized Ledgix Sale.")
			sale = frappe.db.get_value(
				"Ledgix Sale",
				{"name": self.linked_sale, "docstatus": 1},
				["branch"],
				as_dict=True,
			)
			if not sale or sale.branch != self.branch:
				frappe.throw("Final Sale must be submitted and belong to the same Branch.")
			self.closed_at = self.closed_at or now_datetime()
			self.closed_by = self.closed_by or frappe.session.user
