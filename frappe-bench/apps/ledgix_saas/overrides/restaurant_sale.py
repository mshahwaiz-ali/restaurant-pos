from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix.doctype.ledgix_sale.ledgix_sale import LedgixSale
from ledgix_saas.services.receivables import refresh_customer_credit_summary
from ledgix_saas.services.restaurant_sale_tax import apply_restaurant_sale_tax_snapshot
from ledgix_saas.services.sales import apply_customer_snapshot, apply_item_snapshots, apply_seller_snapshot


class RestaurantAwareLedgixSale(LedgixSale):
	"""Keep Ledgix Sale as final truth while respecting restaurant kitchen stock."""

	def is_restaurant_settlement(self):
		return bool(self.get("restaurant_order"))

	def validate(self):
		if not self.is_restaurant_settlement():
			return super().validate()

		if self.docstatus == 0:
			self.status = "Draft"
			apply_customer_snapshot(self)
			apply_seller_snapshot(self)
			apply_item_snapshots(self)

		self.validate_channel_requirements()
		self.apply_operating_context()
		self.validate_pos_shift()
		self.validate_restaurant_source()
		self.calculate_totals()
		apply_restaurant_sale_tax_snapshot(self)
		self.validate_tender_methods()
		self.calculate_payments()
		self.validate_payments()
		self.validate_credit()

		# Restaurant V1 does not accept serial-tracked menu lines. Their identity
		# allocation must be handled at kitchen fire before such items are enabled.
		for row in self.items:
			tracking_type = frappe.db.get_value("Ledgix Item", row.item, "tracking_type")
			if tracking_type == "Serial Based":
				frappe.throw("Serial Based items are not supported on Restaurant Orders in V1.")

	def validate_stock(self):
		if self.is_restaurant_settlement():
			self.validate_restaurant_source()
			return
		return super().validate_stock()

	def validate_restaurant_source(self):
		order = frappe.get_doc("Ledgix Restaurant Order", self.restaurant_order)
		if order.status == "Voided":
			frappe.throw("Voided Restaurant Orders cannot be settled.")
		if order.linked_sale and order.linked_sale != self.name:
			frappe.throw(f"Restaurant Order is already linked to Sale {order.linked_sale}.")
		if order.branch != self.branch or order.stock_location != self.stock_location:
			frappe.throw("Restaurant Sale branch/location must match the source Restaurant Order.")
		if order.price_list != self.price_list:
			frappe.throw("Restaurant Sale Price List must match the source Restaurant Order snapshot.")
		if not self.get("restaurant_stock_consumed_at_kitchen"):
			frappe.throw("Restaurant Sale must declare kitchen-time stock consumption.")

		active_items = {
			row.name: row
			for row in frappe.get_all(
				"Ledgix Restaurant Order Item",
				filters={"restaurant_order": order.name, "is_voided": 0},
				fields=["name", "item", "billable_quantity", "fired_quantity", "line_unit_rate"],
				limit_page_length=0,
			)
			if flt(row.billable_quantity) > 0
		}
		seen = set()
		for row in self.items:
			order_item_name = row.get("restaurant_order_item")
			if not order_item_name or order_item_name in seen:
				frappe.throw("Every Restaurant Sale line requires one unique Restaurant Order Item reference.")
			seen.add(order_item_name)
			order_item = active_items.get(order_item_name)
			if not order_item:
				frappe.throw(f"Restaurant Order Item {order_item_name} is not billable on {order.name}.")
			if order_item.item != row.item:
				frappe.throw(f"Sale item does not match Restaurant Order Item {order_item.name}.")
			if abs(flt(order_item.billable_quantity) - flt(row.quantity)) > 0.000001:
				frappe.throw(f"Sale quantity does not match Restaurant Order Item {order_item.name}.")
			if abs(flt(order_item.line_unit_rate) - flt(row.rate)) > 0.01:
				frappe.throw(f"Sale rate does not match Restaurant Order Item {order_item.name}.")
			if flt(order_item.fired_quantity) + 0.000001 < flt(order_item.billable_quantity):
				frappe.throw(f"Restaurant Order Item {order_item.name} must be fully fired before settlement.")

		if set(active_items) != seen:
			missing = ", ".join(sorted(set(active_items) - seen))
			frappe.throw(f"Restaurant Sale is missing billable Order Items: {missing}")

	def on_submit(self):
		if not self.is_restaurant_settlement():
			return super().on_submit()

		self.status = "Submitted"
		self.db_set("status", "Submitted", update_modified=False)

		# Do NOT post Ledgix Sale OUT movements or FIFO/serial allocations here.
		# Restaurant inventory was already consumed exactly once at KOT fire.
		self.post_legacy_tenders_to_payment_ledger()
		self.update_pos_shift_cash()
		refresh_customer_credit_summary(self.customer)
		self.queue_fbr_submission_after_sale_work()

	def before_cancel(self):
		if self.is_restaurant_settlement():
			frappe.throw(
				"Finalized Restaurant Sales cannot be cancelled directly. Use Sales Return/Credit and the payment refund workflow."
			)
		return super().before_cancel()
