from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from ledgix_saas.services.organization import ensure_branch_access


LOCKED_FIELDS = (
	"restaurant_order", "charge_type", "item", "item_name_snapshot", "tax_snapshot_locked",
	"item_tax_profile_snapshot", "tax_category_snapshot", "tax_basis_snapshot", "tax_rate_snapshot",
	"notified_retail_price_snapshot", "price_includes_tax_snapshot", "fbr_rate_description_snapshot",
	"hs_code_snapshot", "uom_for_fbr_snapshot", "sales_type_snapshot", "scenario_id_snapshot",
	"sro_schedule_number_snapshot", "sro_item_serial_number_snapshot",
	"sales_tax_withheld_at_source_per_unit_snapshot", "extra_tax_per_unit_snapshot",
	"further_tax_per_unit_snapshot", "fed_payable_per_unit_snapshot", "charge_key",
)
AMOUNT_FIELDS = (
	"amount", "taxable_amount", "sales_tax_amount", "sales_tax_withheld_at_source",
	"extra_tax_amount", "further_tax_amount", "fed_payable_amount", "tax_amount", "net_amount",
)


class LedgixRestaurantOrderCharge(Document):
	def before_insert(self):
		if not getattr(self.flags, "from_restaurant_settlement_service", False):
			frappe.throw("Restaurant Order Charges are service-owned.", frappe.PermissionError)
		self.charge_key = self.charge_key or f"{self.restaurant_order}::{self.charge_type}"

	def validate(self):
		order = frappe.db.get_value(
			"Ledgix Restaurant Order",
			self.restaurant_order,
			["branch", "status", "linked_sale"],
			as_dict=True,
		)
		if not order:
			frappe.throw("Restaurant Order Charge requires a valid Restaurant Order.")
		ensure_branch_access(order.branch)
		if order.status in {"Closed", "Voided"} or order.linked_sale:
			frappe.throw("Charges cannot change on a finalized Restaurant Order.")
		if self.charge_type not in {"Service Charge", "Tip"}:
			frappe.throw("Restaurant Charge Type must be Service Charge or Tip.")
		if flt(self.amount) < 0:
			frappe.throw("Restaurant Charge amount cannot be negative.")
		if not frappe.db.exists("Ledgix Item", {"name": self.item, "active": 1}):
			frappe.throw("Restaurant Charge requires an active Ledgix Item.")

		before = self.get_doc_before_save()
		if not before:
			return
		if any(before.get(field) != self.get(field) for field in LOCKED_FIELDS):
			frappe.throw("Restaurant Charge snapshot fields are immutable.", frappe.PermissionError)
		if any(before.get(field) != self.get(field) for field in AMOUNT_FIELDS):
			if not getattr(self.flags, "allow_charge_amount_update", False):
				frappe.throw("Restaurant Charge amounts must be changed through the service.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Restaurant Charge snapshots cannot be deleted.", frappe.PermissionError)
