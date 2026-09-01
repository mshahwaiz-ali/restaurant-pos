from __future__ import annotations

import frappe

from ledgix_saas.api.security import require_ledgix_cashier_or_above
from ledgix_saas.services.restaurant_settlement import (
	preview_restaurant_settlement,
	settle_restaurant_order,
)


@frappe.whitelist()
def preview(
	restaurant_order,
	discount_amount=None,
	service_charge=None,
	tip_amount=None,
):
	require_ledgix_cashier_or_above()
	return preview_restaurant_settlement(
		restaurant_order,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
	)


@frappe.whitelist()
def settle(
	restaurant_order,
	tenders,
	client_sale_id,
	discount_amount=None,
	service_charge=None,
	tip_amount=None,
	adjustment_reason=None,
	request_id=None,
):
	require_ledgix_cashier_or_above()
	return settle_restaurant_order(
		restaurant_order,
		tenders=tenders,
		client_sale_id=client_sale_id,
		discount_amount=discount_amount,
		service_charge=service_charge,
		tip_amount=tip_amount,
		adjustment_reason=adjustment_reason,
		request_id=request_id,
	)
