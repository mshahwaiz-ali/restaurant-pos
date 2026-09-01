from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.api.stock_identity_location import is_serial_based_item


@frappe.whitelist()
def get_available_pos_serials(item=None, limit=200, branch=None, stock_location=None):
    """Return available serial identities for one authorized POS stock location."""
    require_ledgix_cashier_or_above()
    item = str(item or "").strip()
    if not item or not frappe.db.exists("Ledgix Item", item):
        frappe.throw("Valid item is required.")
    if not is_serial_based_item(item):
        frappe.throw("Serial selection is only available for Serial Based items.")

    from ledgix_saas.services.organization import resolve_branch_location

    branch, stock_location = resolve_branch_location(
        branch,
        stock_location,
        purpose="consumption",
    )
    limit = min(max(int(limit or 200), 1), 500)
    rows = frappe.get_all(
        "Ledgix Stock Serial",
        filters={
            "item": item,
            "status": "Available",
            "stock_location": stock_location,
        },
        fields=["name", "serial_no", "purchase", "purchase_date"],
        order_by="purchase_date asc, creation asc, serial_no asc",
        limit_page_length=limit,
    )
    return {
        "item": item,
        "branch": branch,
        "stock_location": stock_location,
        "serials": [
            {
                "name": row.name,
                "serial_no": row.serial_no,
                "purchase": row.purchase,
                "purchase_date": row.purchase_date,
            }
            for row in rows
        ],
    }
