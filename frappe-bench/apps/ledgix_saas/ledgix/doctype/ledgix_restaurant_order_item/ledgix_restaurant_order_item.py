from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from ledgix_saas.services.organization import ensure_branch_access


FINAL_ORDER_STATUSES = {"Closed", "Voided"}
PROTECTED_KITCHEN_STATUSES = {"Fired", "Preparing", "Ready", "Served"}
SNAPSHOT_FIELDS = (
	"menu_item",
	"item",
	"display_name_snapshot",
	"rate",
	"modifier_unit_total",
	"line_unit_rate",
	"recipe",
	"recipe_version",
	"recipe_cost_per_unit",
)
OPERATIONAL_FIELDS = (
	"quantity",
	"void_quantity",
	"seat_no",
	"course",
	"is_course_held",
	"kitchen_status",
	"fired_quantity",
	"prepared_quantity",
	"ready_quantity",
	"served_quantity",
	"item_note",
	"is_voided",
	"void_reason",
	"voided_by",
	"voided_at",
)
MODIFIER_SNAPSHOT_FIELDS = (
	"modifier_group",
	"modifier_option",
	"modifier_group_name_snapshot",
	"option_name_snapshot",
	"kitchen_label_snapshot",
	"selection_quantity",
	"price_delta",
	"stock_effect",
	"linked_item",
	"stock_quantity",
	"uom",
)


class LedgixRestaurantOrderItem(Document):
	"""Stable operational restaurant line.

	The row is intentionally a standalone DocType. Creation and operational
	mutations must pass through the restaurant-order service so pricing,
	modifiers, branch access and later kitchen invariants cannot be bypassed by a
	direct document write.
	"""

	def before_insert(self):
		if not getattr(self.flags, "from_restaurant_order_service", False):
			frappe.throw(
				"Restaurant Order Items must be created through the restaurant-order service.",
				frappe.PermissionError,
			)

	def validate(self):
		order = self._validate_parent_order()
		self._validate_menu_item(order)
		self._validate_service_mutation()
		self._validate_snapshot_immutability()
		self._validate_quantities()
		self._validate_kitchen_state()
		self._recalculate_amounts()
		self._validate_void_state()

	def on_trash(self):
		if not getattr(self.flags, "from_restaurant_order_service", False):
			frappe.throw(
				"Restaurant Order Items cannot be deleted directly. Void them through the restaurant-order service.",
				frappe.PermissionError,
			)
		if flt(self.fired_quantity) > 0 or flt(self.prepared_quantity) > 0:
			frappe.throw("Kitchen-fired Restaurant Order Items cannot be deleted.")

	def _validate_parent_order(self):
		order = frappe.db.get_value(
			"Ledgix Restaurant Order",
			self.restaurant_order,
			[
				"name",
				"branch",
				"menu",
				"price_list",
				"order_type",
				"status",
				"linked_sale",
				"table_session",
			],
			as_dict=True,
		)
		if not order:
			frappe.throw("Restaurant Order Item requires a valid Restaurant Order.")
		ensure_branch_access(order.branch)
		if order.status in FINAL_ORDER_STATUSES or order.linked_sale:
			frappe.throw("Items cannot be changed on a finalized Restaurant Order.")
		return order

	def _validate_menu_item(self, order):
		channel_field = {
			"Dine In": "available_dine_in",
			"Takeaway": "available_takeaway",
			"Delivery": "available_delivery",
		}.get(order.order_type)
		fields = ["menu", "item", "display_name", "is_active"]
		if channel_field:
			fields.append(channel_field)
		menu_item = frappe.db.get_value(
			"Ledgix Menu Item",
			self.menu_item,
			fields,
			as_dict=True,
		)
		if not menu_item or not cint(menu_item.is_active):
			frappe.throw("Menu Item must be active.")
		if menu_item.menu != order.menu:
			frappe.throw("Menu Item must belong to the Restaurant Order menu snapshot.")
		if channel_field and not cint(menu_item.get(channel_field)):
			frappe.throw(f"Menu Item is not available for {order.order_type} orders.")
		if self.item and self.item != menu_item.item:
			frappe.throw("Restaurant Order Item does not match the selected Menu Item.")
		self.item = menu_item.item
		if self.is_new() and not self.display_name_snapshot:
			self.display_name_snapshot = (
				menu_item.display_name
				or frappe.db.get_value("Ledgix Item", menu_item.item, "item_name")
				or menu_item.item
			)

	def _validate_service_mutation(self):
		before = self.get_doc_before_save()
		if not before:
			return

		if before.restaurant_order != self.restaurant_order:
			if not getattr(self.flags, "allow_check_move", False):
				frappe.throw("Move Restaurant Order Items between checks through the split/merge service.")

		changed = [field for field in OPERATIONAL_FIELDS if before.get(field) != self.get(field)]
		if changed and not getattr(self.flags, "allow_operational_mutation", False):
			frappe.throw("Restaurant Order Item operational fields must be changed through the restaurant-order service.")

	def _validate_snapshot_immutability(self):
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [field for field in SNAPSHOT_FIELDS if before.get(field) != self.get(field)]
		modifiers_changed = self._modifier_signature(before) != self._modifier_signature(self)
		if not changed and not modifiers_changed:
			return
		if not getattr(self.flags, "allow_snapshot_refresh", False):
			frappe.throw("Restaurant Order Item price/recipe/modifier snapshots are immutable outside the operational service.")
		if self._is_kitchen_protected(before):
			frappe.throw("Price, recipe or modifier snapshots cannot change after an item has been fired to the kitchen.")

	def _validate_quantities(self):
		quantity = flt(self.quantity, 6)
		void_quantity = flt(self.void_quantity, 6)
		if quantity <= 0:
			frappe.throw("Restaurant Order Item quantity must be greater than zero.")
		if void_quantity < 0 or void_quantity > quantity:
			frappe.throw("Void Quantity must be between zero and the ordered quantity.")

		for fieldname in ("fired_quantity", "prepared_quantity", "ready_quantity", "served_quantity"):
			value = flt(self.get(fieldname), 6)
			if value < 0 or value > quantity:
				frappe.throw(f"{self.meta.get_label(fieldname)} must be between zero and the ordered quantity.")

		fired = flt(self.fired_quantity, 6)
		prepared = flt(self.prepared_quantity, 6)
		ready = flt(self.ready_quantity, 6)
		served = flt(self.served_quantity, 6)
		if prepared > fired:
			frappe.throw("Prepared Quantity cannot exceed Fired Quantity.")
		if ready > prepared:
			frappe.throw("Ready Quantity cannot exceed Prepared Quantity.")
		if served > ready:
			frappe.throw("Served Quantity cannot exceed Ready Quantity.")
		if served + void_quantity > quantity + 0.000001:
			frappe.throw("Served and void quantities cannot exceed the ordered quantity.")

		self.billable_quantity = flt(max(quantity - void_quantity, 0), 6)

	def _validate_kitchen_state(self):
		status = self.kitchen_status or "Not Sent"
		fired = flt(self.fired_quantity, 6)
		prepared = flt(self.prepared_quantity, 6)
		ready = flt(self.ready_quantity, 6)
		served = flt(self.served_quantity, 6)
		if status in {"Not Sent", "Held"} and fired > 0:
			frappe.throw(f"Kitchen Status {status} cannot have a fired quantity.")
		if status in PROTECTED_KITCHEN_STATUSES and fired <= 0:
			frappe.throw(f"Kitchen Status {status} requires a fired quantity.")
		if status in {"Preparing", "Ready", "Served"} and prepared <= 0:
			frappe.throw(f"Kitchen Status {status} requires a prepared quantity.")
		if status in {"Ready", "Served"} and ready <= 0:
			frappe.throw(f"Kitchen Status {status} requires a ready quantity.")
		if status == "Served" and served <= 0:
			frappe.throw("Served Kitchen Status requires a served quantity.")

	def _recalculate_amounts(self):
		quantity = flt(self.billable_quantity, 6)
		self.modifier_unit_total = flt(self.modifier_unit_total, 2)
		self.rate = flt(self.rate, 2)
		self.line_unit_rate = flt(self.rate + self.modifier_unit_total, 2)
		self.base_amount = flt(self.rate * quantity, 2)
		self.modifier_amount = flt(self.modifier_unit_total * quantity, 2)
		self.amount = flt(self.line_unit_rate * quantity, 2)
		self.recipe_cost_per_unit = flt(self.recipe_cost_per_unit, 4)
		self.estimated_cost = flt(self.recipe_cost_per_unit * quantity, 4)
		self.estimated_profit = flt(self.amount - self.estimated_cost, 4)

	def _validate_void_state(self):
		void_quantity = flt(self.void_quantity, 6)
		fully_voided = bool(void_quantity and flt(self.billable_quantity, 6) <= 0)
		if void_quantity > 0 and not str(self.void_reason or "").strip():
			frappe.throw("Void Reason is required when any Restaurant Order Item quantity is voided.")
		if cint(self.is_voided) and not fully_voided:
			frappe.throw("Item can only be marked fully voided when its full ordered quantity is voided.")
		if fully_voided:
			self.is_voided = 1
			self.kitchen_status = "Voided"
		elif not void_quantity:
			self.is_voided = 0
			self.void_reason = None
			self.voided_by = None
			self.voided_at = None

	def _is_kitchen_protected(self, doc=None):
		doc = doc or self
		return (
			flt(doc.get("fired_quantity"), 6) > 0
			or flt(doc.get("prepared_quantity"), 6) > 0
			or (doc.get("kitchen_status") or "Not Sent") in PROTECTED_KITCHEN_STATUSES
		)

	@staticmethod
	def _modifier_signature(doc):
		rows = []
		for row in doc.get("modifiers") or []:
			rows.append(tuple(row.get(field) for field in MODIFIER_SNAPSHOT_FIELDS))
		return tuple(rows)
