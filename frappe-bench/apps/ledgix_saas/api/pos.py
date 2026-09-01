"""Legacy POS API compatibility surface.

Ledgix V2 has one checkout engine (`v2_pos`), one return workflow (`v2_returns`)
and one hold workflow (`v2_holds`). Older method paths remain importable so an
upgraded site fails gracefully instead of carrying a second pricing/payment
engine.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.api.v2_holds import (
    cancel_pos_v2_hold,
    get_pos_v2_holds,
    hold_pos_v2_sale,
    resume_pos_v2_hold,
)
from ledgix_saas.api.v2_inventory import get_available_pos_serials
from ledgix_saas.api.v2_pos import (
    complete_pos_v2_sale,
    get_pos_v2_boot,
    search_pos_v2_items,
)
from ledgix_saas.api.v2_returns import (
    create_pos_v2_return,
    get_pos_v2_return_context,
)
from ledgix_saas.services.organization import (
    ensure_branch_access,
    get_allowed_branches,
    resolve_branch_location,
)
from ledgix_saas.services.stock import get_location_stock


@frappe.whitelist()
def get_item_by_barcode_or_sku(code, branch=None, stock_location=None):
    require_ledgix_cashier_or_above()
    code = str(code or "").strip()
    if not code:
        frappe.throw("Barcode / SKU / Item Code is required")

    branch, stock_location = resolve_branch_location(
        branch,
        stock_location,
        purpose="consumption",
    )
    for fieldname in ("barcode", "sku", "item_code"):
        name = frappe.db.get_value(
            "Ledgix Item",
            {fieldname: code, "active": 1},
            "name",
        )
        if name:
            item = frappe.db.get_value(
                "Ledgix Item",
                name,
                [
                    "name",
                    "item_name",
                    "item_code",
                    "sku",
                    "barcode",
                    "unit",
                    "tracking_type",
                    "selling_price",
                    "cost_price",
                    "current_stock",
                ],
                as_dict=True,
            )
            item["aggregate_stock"] = flt(item.current_stock)
            item["current_stock"] = get_location_stock(name, stock_location)
            item["branch"] = branch
            item["stock_location"] = stock_location
            return {"found": True, "item": item}
    return {"found": False, "message": "No active item found for this barcode / SKU / item code"}


@frappe.whitelist()
def get_pos_boot_data(branch=None, stock_location=None):
    """Compatibility boot response backed by the V2 catalog and configuration."""
    boot = get_pos_v2_boot(
        sale_channel="Retail",
        branch=branch,
        stock_location=stock_location,
    )
    catalog = search_pos_v2_items(
        sale_channel="Retail",
        limit=60,
        branch=boot.get("branch"),
        stock_location=boot.get("stock_location"),
    )
    return {
        "branch": boot.get("branch"),
        "stock_location": boot.get("stock_location"),
        "categories": boot.get("categories") or [],
        "items": catalog.get("items") or [],
        "payment_methods": boot.get("payment_methods") or [],
        "active_shift": boot.get("active_shift"),
        "price_list": boot.get("price_list"),
    }


@frappe.whitelist()
def search_pos_items(query=None, category=None, branch=None, stock_location=None):
    result = search_pos_v2_items(
        query=query,
        category=category,
        sale_channel="Retail",
        limit=80,
        branch=branch,
        stock_location=stock_location,
    )
    return {
        "branch": result.get("branch"),
        "stock_location": result.get("stock_location"),
        "items": result.get("items") or [],
    }


@frappe.whitelist()
def get_available_serials_for_pos(item, limit=100, branch=None, stock_location=None):
    result = get_available_pos_serials(
        item=item,
        limit=limit,
        branch=branch,
        stock_location=stock_location,
    )
    return {
        "item": result.get("item"),
        "branch": result.get("branch"),
        "stock_location": result.get("stock_location"),
        "serials": [
            {
                "name": row.get("name"),
                "serial_number": row.get("serial_no"),
                "item": result.get("item"),
                "purchase": row.get("purchase"),
                "purchase_date": row.get("purchase_date"),
                "status": "Available",
            }
            for row in result.get("serials") or []
        ],
    }


@frappe.whitelist()
def create_pos_sale(
    cart_items=None,
    payments=None,
    discount_type="Amount",
    discount_value=0,
    client_sale_id=None,
    branch=None,
    stock_location=None,
):
    """Old checkout path delegates to the authoritative V2 Retail checkout."""
    tenders = frappe.parse_json(payments) if isinstance(payments, str) else (payments or [])
    normalized = []
    for row in tenders:
        normalized.append({
            "payment_method": row.get("payment_method"),
            "amount": row.get("amount"),
            "reference_number": row.get("reference_number") or row.get("reference_no"),
            "notes": row.get("notes"),
        })
    return complete_pos_v2_sale(
        cart_items=cart_items,
        tenders=normalized,
        sale_channel="Retail",
        discount_type=discount_type,
        discount_value=discount_value,
        client_sale_id=client_sale_id,
        branch=branch,
        stock_location=stock_location,
    )


@frappe.whitelist()
def hold_pos_sale(cart_items=None, discount_type="Amount", discount_value=0, notes=None):
    return hold_pos_v2_sale(
        cart_items=cart_items,
        sale_channel="Retail",
        discount_type=discount_type,
        discount_value=discount_value,
        notes=notes,
    )


@frappe.whitelist()
def get_held_pos_sales():
    return get_pos_v2_holds()


@frappe.whitelist()
def resume_held_pos_sale(hold_id=None):
    return resume_pos_v2_hold(hold_id=hold_id)


@frappe.whitelist()
def delete_held_pos_sale(hold_id=None):
    return cancel_pos_v2_hold(hold_id=hold_id)


@frappe.whitelist()
def get_pos_sale_for_return(sale_id=None):
    result = get_pos_v2_return_context(sale_id=sale_id)
    if isinstance(result, dict):
        branch = result.get("branch")
        if branch:
            ensure_branch_access(branch)
    return result


@frappe.whitelist()
def create_pos_sales_return(original_sale=None, return_items=None, reason=None):
    if not str(reason or "").strip():
        frappe.throw("Return reason is required in Ledgix V2.")
    sale_branch = frappe.db.get_value("Ledgix Sale", original_sale, "branch") if original_sale else None
    if sale_branch:
        ensure_branch_access(sale_branch)
    return create_pos_v2_return(
        original_sale=original_sale,
        return_items=return_items,
        reason=reason,
    )


@frappe.whitelist()
def get_recent_pos_sales(limit=10, offset=0, query=None, branch=None):
    """Compatibility sale history restricted to the caller's authorized branches."""
    require_ledgix_cashier_or_above()
    limit = min(max(int(limit or 10), 1), 50)
    offset = max(int(offset or 0), 0)
    query = str(query or "").strip()

    allowed = get_allowed_branches()
    if branch:
        ensure_branch_access(branch)
        allowed = [branch]
    if not allowed:
        return {
            "success": True,
            "sales": [],
            "limit": limit,
            "offset": offset,
            "total_count": 0,
            "has_more": False,
        }

    filters = {"docstatus": 1, "branch": ["in", allowed]}
    or_filters = None
    if query:
        like = f"%{query}%"
        or_filters = [
            ["name", "like", like],
            ["invoice_number", "like", like],
            ["customer", "like", like],
        ]

    rows = frappe.get_all(
        "Ledgix Sale",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "invoice_number",
            "creation",
            "sale_date",
            "branch",
            "stock_location",
            "customer",
            "sale_channel",
            "pos_shift",
            "total_amount",
            "tax_amount",
            "grand_total",
            "paid_amount",
            "change_amount",
            "payment_status",
            "owner",
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=limit,
    )

    total_count = frappe.db.count("Ledgix Sale", filters=filters)
    for sale in rows:
        item_rows = frappe.get_all(
            "Ledgix Sale Item",
            filters={"parent": sale.name, "parenttype": "Ledgix Sale", "parentfield": "items"},
            fields=["item", "quantity"],
            order_by="idx asc",
            limit_page_length=4,
        )
        sale["item_count"] = frappe.db.count(
            "Ledgix Sale Item",
            filters={"parent": sale.name, "parenttype": "Ledgix Sale", "parentfield": "items"},
        )
        sale["items_preview"] = ", ".join(
            f"{frappe.db.get_value('Ledgix Item', row.item, 'item_name') or row.item} x {flt(row.quantity):g}"
            for row in item_rows
        )

    return {
        "success": True,
        "sales": rows,
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + limit < total_count,
    }


@frappe.whitelist()
def get_pos_sale_receipt_data(sale_id=None):
    """Compatibility receipt read. Current V2 printing uses Frappe Print Formats."""
    require_ledgix_cashier_or_above()
    if not sale_id:
        frappe.throw("Sale ID is required")
    sale = frappe.get_doc("Ledgix Sale", sale_id)
    if sale.docstatus != 1:
        frappe.throw("Only submitted sales can be printed")
    if getattr(sale, "branch", None):
        ensure_branch_access(sale.branch)

    payments = frappe.db.sql(
        """
        SELECT
            p.payment_method,
            p.amount,
            p.amount_tendered,
            p.change_amount,
            p.reference_number,
            p.reversal_of
        FROM `tabLedgix Payment` p
        INNER JOIN `tabLedgix Payment Allocation` a ON a.parent = p.name
        WHERE p.docstatus = 1
          AND a.reference_doctype = 'Ledgix Sale'
          AND a.reference_name = %s
        ORDER BY p.payment_date ASC, p.creation ASC
        """,
        (sale.name,),
        as_dict=True,
    ) if frappe.db.exists("DocType", "Ledgix Payment") else []

    return {
        "success": True,
        "receipt": {
            "sale_id": sale.name,
            "invoice_number": sale.invoice_number,
            "date_time": sale.creation,
            "branch": getattr(sale, "branch", None),
            "stock_location": getattr(sale, "stock_location", None),
            "customer": sale.customer,
            "cashier": sale.owner,
            "shift_id": sale.pos_shift,
            "items": [
                {
                    "item": row.item,
                    "item_name": frappe.db.get_value("Ledgix Item", row.item, "item_name") or row.item,
                    "qty": flt(row.quantity),
                    "rate": flt(row.rate),
                    "amount": flt(row.amount),
                }
                for row in sale.items
            ],
            "subtotal": flt(sale.subtotal_before_discount or sale.total_amount),
            "discount": flt(sale.discount_amount),
            "tax": flt(sale.tax_amount),
            "total": flt(sale.grand_total or sale.total_amount),
            "paid": flt(sale.paid_amount),
            "remaining": flt(sale.remaining_amount),
            "change": flt(sale.change_amount),
            "payment_status": sale.payment_status,
            "fbr_status": sale.fbr_status or "",
            "fbr_invoice_number": sale.fbr_invoice_number or "",
            "fbr_qr_code": sale.fbr_qr_code or "",
            "payments": payments,
        },
    }
