# Copyright (c) 2026, Ali and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class LedgixStockMovement(Document):

    def validate(self):
        if not self.item:
            frappe.throw("Item is required.")
        if self.movement_type not in {"IN", "OUT", "ADJUSTMENT"}:
            frappe.throw(f"Invalid movement type: {self.movement_type}")

        quantity = flt(self.quantity)
        if self.movement_type == "ADJUSTMENT":
            if quantity < 0:
                frappe.throw("Adjustment quantity cannot be negative.")
        elif quantity <= 0:
            frappe.throw("Movement quantity must be greater than zero.")

        if self.valuation_rate is not None and flt(self.valuation_rate) < 0:
            frappe.throw("Valuation Rate cannot be negative.")

        from ledgix_saas.services.organization import resolve_branch_location

        self.branch, self.stock_location = resolve_branch_location(
            getattr(self, "branch", None),
            getattr(self, "stock_location", None),
        )

        # Server-created movements normally pass an explicit valuation snapshot.
        # A maintenance-created movement keeps the current item-level average.
        if self.valuation_rate is None and self.item:
            self.valuation_rate = flt(
                frappe.db.get_value("Ledgix Item", self.item, "cost_price") or 0
            )

    def before_insert(self):
        if not self.movement_date:
            self.movement_date = frappe.utils.now_datetime()

    def on_submit(self):
        self.update_stock()

    def on_cancel(self):
        if self.movement_type == "ADJUSTMENT":
            frappe.throw(
                "Stock Adjustment cannot be cancelled safely. Create a corrective adjustment instead."
            )

        self.update_stock(reverse=True)

        # Cancelling an earlier OUT or IN can change the quantity base used by
        # later receipts. Replay cost history after the quantity reversal.
        from ledgix_saas.services.stock import rebuild_item_average_cost

        rebuild_item_average_cost(self.item, exclude_movement=self.name)

    def update_stock(self, reverse=False):
        from ledgix_saas.services.stock import (
            ensure_stock_balance,
            get_location_stock,
            get_total_stock,
            refresh_stock_balance_valuation,
        )

        # get_location_stock(for_update=True) locks the Item row first and then
        # the materialized location balance. All stock writes for an item are
        # therefore serialized even when two terminals target different branches.
        location_stock = get_location_stock(
            self.item,
            self.stock_location,
            for_update=True,
        )
        balance_name = ensure_stock_balance(self.item, self.stock_location)
        aggregate_stock = get_total_stock(self.item)
        item_doc = frappe.get_doc("Ledgix Item", self.item)
        quantity = flt(self.quantity)
        new_location_stock = location_stock
        new_aggregate_stock = aggregate_stock

        if reverse:
            if self.movement_type == "IN":
                if quantity > location_stock + 0.000001:
                    frappe.throw(
                        f"Cannot cancel stock IN for {self.item} at {self.stock_location}. "
                        f"Available location stock is {location_stock:g}, required reversal is {quantity:g}."
                    )
                new_location_stock = location_stock - quantity
                new_aggregate_stock = aggregate_stock - quantity
            elif self.movement_type == "OUT":
                new_location_stock = location_stock + quantity
                new_aggregate_stock = aggregate_stock + quantity
        else:
            if self.movement_type == "IN":
                valuation_rate = max(flt(self.valuation_rate), 0)
                new_location_stock = location_stock + quantity
                new_aggregate_stock = aggregate_stock + quantity
                old_cost = flt(item_doc.cost_price)
                item_doc.cost_price = (
                    ((aggregate_stock * old_cost) + (quantity * valuation_rate))
                    / new_aggregate_stock
                    if new_aggregate_stock > 0
                    else valuation_rate
                )
            elif self.movement_type == "OUT":
                if quantity > location_stock + 0.000001:
                    frappe.throw(
                        f"Stock movement would make {self.item} negative at {self.stock_location}. "
                        f"Available location stock: {location_stock:g}."
                    )
                new_location_stock = location_stock - quantity
                new_aggregate_stock = aggregate_stock - quantity
            elif self.movement_type == "ADJUSTMENT":
                movement_meta = frappe.get_meta("Ledgix Stock Movement")
                if movement_meta.has_field("previous_quantity"):
                    self.db_set("previous_quantity", str(flt(location_stock, 6)), update_modified=False)
                if movement_meta.has_field("previous_quantity_is_snapshot"):
                    self.db_set("previous_quantity_is_snapshot", 1, update_modified=False)
                new_location_stock = quantity
                new_aggregate_stock = aggregate_stock + (quantity - location_stock)
                if self.valuation_rate is not None:
                    item_doc.cost_price = max(flt(self.valuation_rate), 0)

        if new_location_stock < -0.000001 or new_aggregate_stock < -0.000001:
            frappe.throw("Stock movement would create a negative inventory balance.")

        new_location_stock = max(flt(new_location_stock), 0)
        new_aggregate_stock = max(flt(new_aggregate_stock), 0)

        frappe.db.set_value(
            "Ledgix Stock Balance",
            balance_name,
            {
                "quantity": new_location_stock,
                "valuation_rate": max(flt(item_doc.cost_price), 0),
                "stock_value": flt(new_location_stock * max(flt(item_doc.cost_price), 0), 6),
            },
            update_modified=False,
        )

        item_doc.current_stock = new_aggregate_stock
        item_doc.update_stock_status()
        item_doc.flags.allow_stock_update = True
        item_doc.flags.allow_cost_update = True
        item_doc.save(ignore_permissions=True)
        refresh_stock_balance_valuation(self.item, item_doc.cost_price)
