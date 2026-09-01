from __future__ import annotations

import frappe
from frappe.utils import flt, today

from ledgix_saas.api import stock_identity as legacy


# Stable helpers remain authoritative in the existing module.
is_lot_based_item = legacy.is_lot_based_item
is_serial_based_item = legacy.is_serial_based_item
parse_serial_numbers = legacy.parse_serial_numbers
normalize_purchase_serials = legacy.normalize_purchase_serials
normalize_sales_return_serials = legacy.normalize_sales_return_serials
validate_purchase_serial_numbers = legacy.validate_purchase_serial_numbers
reverse_purchase_lots = legacy.reverse_purchase_lots
reverse_purchase_serials = legacy.reverse_purchase_serials
reverse_sale_fifo_allocations = legacy.reverse_sale_fifo_allocations
reverse_sale_serial_allocations = legacy.reverse_sale_serial_allocations
reverse_sales_return_fifo_allocations = legacy.reverse_sales_return_fifo_allocations
reverse_sales_return_serials = legacy.reverse_sales_return_serials


def _require_location_context(doc):
    branch = getattr(doc, "branch", None)
    stock_location = getattr(doc, "stock_location", None)
    if not branch or not stock_location:
        frappe.throw(f"{doc.doctype} requires Branch and Stock Location for inventory identity tracking.")
    location_branch = frappe.db.get_value(
        "Ledgix Stock Location",
        {"name": stock_location, "is_active": 1},
        "branch",
    )
    if location_branch != branch:
        frappe.throw(f"Stock Location {stock_location} does not belong to Branch {branch}.")
    return branch, stock_location


def _select_available_sale_serial_numbers(item_code, qty, stock_location, excluded_serials=None):
    excluded_serials = set(excluded_serials or [])
    serial_rows = frappe.get_all(
        "Ledgix Stock Serial",
        filters={
            "item": item_code,
            "status": "Available",
            "stock_location": stock_location,
        },
        fields=["serial_no", "purchase_date", "creation"],
        order_by="purchase_date asc, creation asc",
        limit_page_length=qty + len(excluded_serials) + 50,
    )

    serials = []
    for serial in serial_rows:
        if serial.serial_no in excluded_serials:
            continue
        serials.append(serial.serial_no)
        if len(serials) >= qty:
            break

    if len(serials) != qty:
        frappe.throw(
            f"Serial Based item {item_code} requires {qty} available serial number(s) "
            f"at {stock_location}, but only {len(serials)} are available."
        )
    return serials


def normalize_sale_serials(sale_doc):
    _branch, stock_location = _require_location_context(sale_doc)
    selected_serials = set()

    for row in sale_doc.get("items") or []:
        if not is_serial_based_item(row.item):
            continue

        if legacy._has_serial_number_input(getattr(row, "serial_numbers", None)):
            for serial_no in parse_serial_numbers(getattr(row, "serial_numbers", None)):
                selected_serials.add(serial_no)
            continue

        qty = legacy._get_required_serial_qty(row.item, row.quantity)
        serials = _select_available_sale_serial_numbers(
            row.item,
            qty,
            stock_location,
            selected_serials,
        )
        legacy._write_serial_numbers(row, serials)
        selected_serials.update(serials)


def validate_sale_serial_numbers(sale_doc):
    _branch, stock_location = _require_location_context(sale_doc)
    for row in sale_doc.get("items") or []:
        if not is_serial_based_item(row.item):
            continue
        serials = parse_serial_numbers(getattr(row, "serial_numbers", None))
        legacy._validate_serial_qty(row.item, row.quantity, serials)
        for serial_no in serials:
            serial = frappe.db.get_value(
                "Ledgix Stock Serial",
                {"serial_no": serial_no},
                ["item", "stock_location"],
                as_dict=True,
            )
            if not serial or serial.item != row.item:
                frappe.throw(f"Serial number {serial_no} does not belong to item {row.item}.")
            if serial.stock_location != stock_location:
                frappe.throw(
                    f"Serial number {serial_no} is held at {serial.stock_location or 'an unknown location'}, "
                    f"not Sale location {stock_location}."
                )


def validate_sales_return_serial_numbers(return_doc):
    legacy.validate_sales_return_serial_numbers(return_doc)
    _branch, stock_location = _require_location_context(return_doc)
    for row in return_doc.get("items") or []:
        if not is_serial_based_item(row.item):
            continue
        for serial_no in parse_serial_numbers(getattr(row, "serial_numbers", None)):
            serial = frappe.db.get_value(
                "Ledgix Stock Serial",
                {"serial_no": serial_no},
                ["sale", "stock_location"],
                as_dict=True,
            )
            if not serial or serial.sale != return_doc.original_sale:
                frappe.throw(
                    f"Serial number {serial_no} was not sold in original Sale {return_doc.original_sale}."
                )
            if serial.stock_location != stock_location:
                frappe.throw(
                    f"Serial number {serial_no} belongs to Stock Location {serial.stock_location}, "
                    f"not return location {stock_location}."
                )


def create_stock_lots_for_purchase(purchase_doc):
    branch, stock_location = _require_location_context(purchase_doc)
    created_lots = []

    for row in purchase_doc.get("items") or []:
        if not row.item or not is_lot_based_item(row.item):
            continue

        existing_lot = frappe.db.get_value(
            "Ledgix Stock Lot",
            {
                "purchase": purchase_doc.name,
                "purchase_item_row": row.name,
                "item": row.item,
            },
            ["name", "branch", "stock_location"],
            as_dict=True,
        )
        if existing_lot:
            if existing_lot.branch != branch or existing_lot.stock_location != stock_location:
                frappe.throw(f"Existing lot {existing_lot.name} has a conflicting Branch/Stock Location.")
            legacy.create_purchase_lot_allocation(purchase_doc, row, existing_lot.name)
            created_lots.append(existing_lot.name)
            continue

        qty = flt(row.quantity)
        rate = flt(row.rate)
        if qty <= 0:
            continue

        lot = frappe.new_doc("Ledgix Stock Lot")
        lot.item = row.item
        lot.branch = branch
        lot.stock_location = stock_location
        lot.purchase = purchase_doc.name
        lot.purchase_item_row = row.name
        lot.supplier = purchase_doc.supplier
        lot.purchase_date = purchase_doc.purchase_date
        lot.purchased_qty = qty
        lot.sold_qty = 0
        lot.returned_qty = 0
        lot.remaining_qty = qty
        lot.cost_rate = rate
        lot.total_cost = qty * rate
        lot.status = "Open"
        lot.insert(ignore_permissions=True)
        legacy.create_purchase_lot_allocation(purchase_doc, row, lot.name)
        created_lots.append(lot.name)

    return created_lots


def get_fifo_lots(item_code, stock_location, for_update=False):
    if for_update:
        return frappe.db.sql(
            """
            SELECT name, remaining_qty, cost_rate, purchase_date
            FROM `tabLedgix Stock Lot`
            WHERE item=%s
              AND stock_location=%s
              AND status='Open'
              AND remaining_qty > 0
            ORDER BY purchase_date ASC, creation ASC
            FOR UPDATE
            """,
            (item_code, stock_location),
            as_dict=True,
        )

    return frappe.get_all(
        "Ledgix Stock Lot",
        filters={
            "item": item_code,
            "stock_location": stock_location,
            "status": "Open",
            "remaining_qty": [">", 0],
        },
        fields=["name", "remaining_qty", "cost_rate", "purchase_date"],
        order_by="purchase_date asc, creation asc",
    )


def allocate_sale_fifo(sale_doc):
    _branch, stock_location = _require_location_context(sale_doc)
    all_allocations = []

    for sale_item in sale_doc.get("items") or []:
        if not is_lot_based_item(sale_item.item):
            continue

        existing_allocation = frappe.db.exists(
            "Ledgix Stock Lot Allocation",
            {
                "sale": sale_doc.name,
                "sale_item_row": sale_item.name,
                "allocation_type": "Sale",
                "is_reversed": 0,
            },
        )
        if existing_allocation:
            continue

        required_qty = flt(sale_item.quantity)
        if required_qty <= 0:
            continue

        allocations = []
        for lot in get_fifo_lots(sale_item.item, stock_location, for_update=True):
            if required_qty <= 0:
                break
            available_qty = flt(lot.remaining_qty)
            if available_qty <= 0:
                continue
            consume_qty = min(required_qty, available_qty)

            allocation = frappe.new_doc("Ledgix Stock Lot Allocation")
            allocation.stock_lot = lot.name
            allocation.item = sale_item.item
            allocation.sale = sale_doc.name
            allocation.sale_item_row = sale_item.name
            allocation.allocation_type = "Sale"
            allocation.qty = consume_qty
            allocation.cost_rate = flt(lot.cost_rate)
            allocation.sale_rate = flt(sale_item.rate)
            allocation.profit_amount = (flt(sale_item.rate) - flt(lot.cost_rate)) * consume_qty
            allocation.transaction_date = sale_doc.sale_date or sale_doc.creation
            allocation.is_reversed = 0
            allocation.insert(ignore_permissions=True)

            lot_doc = frappe.get_doc("Ledgix Stock Lot", lot.name)
            lot_doc.sold_qty = flt(lot_doc.sold_qty) + consume_qty
            lot_doc.remaining_qty = flt(lot_doc.remaining_qty) - consume_qty
            if flt(lot_doc.remaining_qty) <= 0:
                lot_doc.status = "Closed"
            lot_doc.save(ignore_permissions=True)

            allocations.append({"lot": lot.name, "qty": consume_qty})
            required_qty -= consume_qty

        if required_qty > 0:
            frappe.throw(
                f"Not enough FIFO stock lots at {stock_location} for item {sale_item.item}."
            )
        all_allocations.extend(allocations)

    return all_allocations


def create_stock_serials_for_purchase(purchase_doc):
    branch, stock_location = _require_location_context(purchase_doc)
    created_serials = []

    for row in purchase_doc.get("items") or []:
        if not is_serial_based_item(row.item):
            continue

        serials = parse_serial_numbers(getattr(row, "serial_numbers", None))
        legacy._validate_serial_qty(row.item, row.quantity, serials)

        for serial_no in serials:
            existing_serial = frappe.db.get_value(
                "Ledgix Stock Serial",
                {"serial_no": serial_no},
                ["name", "purchase", "purchase_item_row", "status", "branch", "stock_location"],
                as_dict=True,
            )
            if existing_serial:
                if (
                    existing_serial.purchase == purchase_doc.name
                    and existing_serial.purchase_item_row == row.name
                    and existing_serial.status != "Cancelled"
                    and existing_serial.branch == branch
                    and existing_serial.stock_location == stock_location
                ):
                    continue
                frappe.throw(f"Serial number {serial_no} already exists for item {row.item}.")

            serial_doc = frappe.new_doc("Ledgix Stock Serial")
            serial_doc.serial_no = serial_no
            serial_doc.item = row.item
            serial_doc.branch = branch
            serial_doc.stock_location = stock_location
            serial_doc.status = "Available"
            serial_doc.purchase = purchase_doc.name
            serial_doc.purchase_item_row = row.name
            serial_doc.supplier = getattr(purchase_doc, "supplier", None)
            serial_doc.purchase_date = getattr(purchase_doc, "purchase_date", None)
            serial_doc.cost_rate = flt(getattr(row, "rate", 0))
            serial_doc.insert(ignore_permissions=True)
            created_serials.append(serial_doc.name)

    return created_serials


def allocate_sale_serials(sale_doc):
    _branch, stock_location = _require_location_context(sale_doc)
    allocated_serials = []

    for row in sale_doc.get("items") or []:
        if not is_serial_based_item(row.item):
            continue

        serials = parse_serial_numbers(getattr(row, "serial_numbers", None))
        legacy._validate_serial_qty(row.item, row.quantity, serials)

        for serial_no in serials:
            serial_doc = frappe.db.get_value(
                "Ledgix Stock Serial",
                {"serial_no": serial_no},
                ["name", "item", "status", "sale", "sale_item_row", "stock_location"],
                as_dict=True,
            )
            if not serial_doc:
                frappe.throw(f"Serial number {serial_no} does not exist for item {row.item}.")
            if serial_doc.item != row.item:
                frappe.throw(f"Serial number {serial_no} belongs to item {serial_doc.item}, not {row.item}.")
            if serial_doc.stock_location != stock_location:
                frappe.throw(
                    f"Serial number {serial_no} is held at {serial_doc.stock_location}, not {stock_location}."
                )
            if serial_doc.sale == sale_doc.name and serial_doc.sale_item_row == row.name:
                allocated_serials.append(serial_doc.name)
                continue
            if serial_doc.status != "Available":
                frappe.throw(
                    f"Serial number {serial_no} for item {row.item} is not Available. "
                    f"Current status: {serial_doc.status}."
                )

            frappe.db.set_value(
                "Ledgix Stock Serial",
                serial_doc.name,
                {
                    "status": "Sold",
                    "sale": sale_doc.name,
                    "sale_item_row": row.name,
                    "customer": getattr(sale_doc, "customer", None),
                    "sold_date": getattr(sale_doc, "sale_date", None) or today(),
                },
                update_modified=False,
            )
            allocated_serials.append(serial_doc.name)

    return allocated_serials


def restore_sale_return_fifo_allocations(return_doc):
    _branch, stock_location = _require_location_context(return_doc)
    lot_names = frappe.get_all(
        "Ledgix Stock Lot Allocation",
        filters={
            "sale": return_doc.original_sale,
            "allocation_type": "Sale",
            "is_reversed": 0,
        },
        pluck="stock_lot",
        limit_page_length=0,
    )
    for lot_name in set(lot_names):
        lot_location = frappe.db.get_value("Ledgix Stock Lot", lot_name, "stock_location")
        if lot_location != stock_location:
            frappe.throw(
                f"Stock Lot {lot_name} belongs to {lot_location}, not return location {stock_location}."
            )
    return legacy.restore_sale_return_fifo_allocations(return_doc)


def restore_sales_return_serials(return_doc):
    validate_sales_return_serial_numbers(return_doc)
    return legacy.restore_sales_return_serials(return_doc)


def create_stock_lot_from_manual_entry(
    item,
    qty,
    rate,
    movement_name,
    *,
    branch,
    stock_location,
):
    if not item or not is_lot_based_item(item):
        return None

    qty = flt(qty)
    if qty <= 0:
        return None

    lot = frappe.new_doc("Ledgix Stock Lot")
    lot.item = item
    lot.branch = branch
    lot.stock_location = stock_location
    lot.purchase_date = today()
    lot.purchased_qty = qty
    lot.sold_qty = 0
    lot.returned_qty = 0
    lot.remaining_qty = qty
    lot.cost_rate = flt(rate)
    lot.total_cost = qty * flt(rate)
    lot.status = "Open"
    lot.insert(ignore_permissions=True)

    allocation = frappe.new_doc("Ledgix Stock Lot Allocation")
    allocation.stock_lot = lot.name
    allocation.item = item
    allocation.purchase_item_row = movement_name or ""
    allocation.allocation_type = "Purchase"
    allocation.qty = qty
    allocation.cost_rate = flt(rate)
    allocation.sale_rate = 0
    allocation.profit_amount = 0
    allocation.transaction_date = today()
    allocation.is_reversed = 0
    allocation.insert(ignore_permissions=True)
    return lot.name


def reduce_lots_fifo_for_manual_out(item, qty, *, stock_location):
    if not item or not is_lot_based_item(item):
        return []

    required_qty = flt(qty)
    if required_qty <= 0:
        return []

    allocations = []
    for lot in get_fifo_lots(item, stock_location, for_update=True):
        if required_qty <= 0:
            break
        available_qty = flt(lot.remaining_qty)
        if available_qty <= 0:
            continue
        consume_qty = min(required_qty, available_qty)

        allocation = frappe.new_doc("Ledgix Stock Lot Allocation")
        allocation.stock_lot = lot.name
        allocation.item = item
        allocation.allocation_type = "Sale"
        allocation.qty = consume_qty
        allocation.cost_rate = flt(lot.cost_rate)
        allocation.sale_rate = 0
        allocation.profit_amount = 0
        allocation.transaction_date = today()
        allocation.is_reversed = 0
        allocation.insert(ignore_permissions=True)

        lot_doc = frappe.get_doc("Ledgix Stock Lot", lot.name)
        lot_doc.sold_qty = flt(lot_doc.sold_qty) + consume_qty
        lot_doc.remaining_qty = flt(lot_doc.remaining_qty) - consume_qty
        if flt(lot_doc.remaining_qty) <= 0:
            lot_doc.status = "Closed"
        lot_doc.save(ignore_permissions=True)

        allocations.append({"lot": lot.name, "qty": consume_qty})
        required_qty -= consume_qty

    if required_qty > 0:
        frappe.throw(f"Not enough FIFO stock lots at {stock_location} for item {item}.")
    return allocations


def create_stock_serials_for_manual_entry(
    item,
    qty,
    serial_numbers=None,
    cost_rate=0,
    *,
    branch,
    stock_location,
):
    if not item or not is_serial_based_item(item):
        return 0

    required_qty = legacy._get_required_serial_qty(item, qty)
    serials = (
        parse_serial_numbers(serial_numbers)
        if legacy._has_serial_number_input(serial_numbers)
        else []
    )
    if not serials:
        serials = legacy._generate_purchase_serial_numbers(item, required_qty)
    legacy._validate_serial_qty(item, qty, serials)

    for serial_no in serials:
        if frappe.db.exists("Ledgix Stock Serial", {"serial_no": serial_no}):
            frappe.throw(f"Serial number {serial_no} already exists for item {item}.")

        serial_doc = frappe.new_doc("Ledgix Stock Serial")
        serial_doc.serial_no = serial_no
        serial_doc.item = item
        serial_doc.branch = branch
        serial_doc.stock_location = stock_location
        serial_doc.status = "Available"
        serial_doc.purchase_date = today()
        serial_doc.cost_rate = flt(cost_rate)
        serial_doc.insert(ignore_permissions=True)

    return len(serials)
