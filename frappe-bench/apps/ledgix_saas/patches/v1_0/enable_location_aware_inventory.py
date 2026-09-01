from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
	"Ledgix Sale": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "pos_shift",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Stock Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Purchase": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "purchase_date",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Receiving Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Sales Return": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "return_date",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Return Stock Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix POS Shift": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "opened_by",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Stock Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Stock Movement": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "item",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Stock Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Stock Lot": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "item",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Stock Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Stock Serial": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "item",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
		{
			"fieldname": "stock_location",
			"label": "Stock Location",
			"fieldtype": "Link",
			"options": "Ledgix Stock Location",
			"insert_after": "branch",
			"read_only": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
	"Ledgix Payment": [
		{
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Ledgix Branch",
			"insert_after": "pos_shift",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Ledgix",
		},
	],
}


def execute():
	"""Introduce branch/location snapshots without rewriting transaction history.

	All legacy data belongs to the compatibility MAIN branch/location created by
	bootstrap_restaurant_foundation unless a stronger relationship (shift, sale or
	purchase) can deterministically supply the context.
	"""
	create_custom_fields(CUSTOM_FIELDS, update=True)

	branch = frappe.db.get_value("Ledgix Branch", {"is_active": 1}, "name", order_by="creation asc")
	if not branch:
		frappe.throw("Restaurant branch foundation is missing. Run bootstrap_restaurant_foundation first.")

	location = frappe.db.get_value(
		"Ledgix Branch", branch, "default_stock_location"
	) or frappe.db.get_value(
		"Ledgix Stock Location",
		{"branch": branch, "is_active": 1},
		"name",
		order_by="creation asc",
	)
	if not location:
		frappe.throw("Restaurant stock-location foundation is missing.")

	_backfill_shifts(branch, location)
	_backfill_sales(branch, location)
	_backfill_purchases(branch, location)
	_backfill_returns(branch, location)
	_backfill_movements(branch, location)
	_backfill_lots(branch, location)
	_backfill_serials(branch, location)
	_backfill_payments(branch)
	frappe.clear_cache()


def _backfill_shifts(branch, location):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix POS Shift`
		SET branch = COALESCE(NULLIF(branch, ''), %s),
		    stock_location = COALESCE(NULLIF(stock_location, ''), %s)
		WHERE COALESCE(branch, '') = '' OR COALESCE(stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_sales(branch, location):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix Sale` s
		LEFT JOIN `tabLedgix POS Shift` sh ON sh.name = s.pos_shift
		SET s.branch = COALESCE(NULLIF(s.branch, ''), NULLIF(sh.branch, ''), %s),
		    s.stock_location = COALESCE(NULLIF(s.stock_location, ''), NULLIF(sh.stock_location, ''), %s)
		WHERE COALESCE(s.branch, '') = '' OR COALESCE(s.stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_purchases(branch, location):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix Purchase`
		SET branch = COALESCE(NULLIF(branch, ''), %s),
		    stock_location = COALESCE(NULLIF(stock_location, ''), %s)
		WHERE COALESCE(branch, '') = '' OR COALESCE(stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_returns(branch, location):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix Sales Return` r
		LEFT JOIN `tabLedgix Sale` s ON s.name = r.original_sale
		SET r.branch = COALESCE(NULLIF(r.branch, ''), NULLIF(s.branch, ''), %s),
		    r.stock_location = COALESCE(NULLIF(r.stock_location, ''), NULLIF(s.stock_location, ''), %s)
		WHERE COALESCE(r.branch, '') = '' OR COALESCE(r.stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_movements(branch, location):
	for reference_doctype, table in (
		("Ledgix Sale", "tabLedgix Sale"),
		("Ledgix Purchase", "tabLedgix Purchase"),
		("Ledgix Sales Return", "tabLedgix Sales Return"),
	):
		frappe.db.sql(
			f"""
			UPDATE `tabLedgix Stock Movement` m
			JOIN `{table}` d ON d.name = m.reference_name
			SET m.branch = COALESCE(NULLIF(m.branch, ''), NULLIF(d.branch, ''), %s),
			    m.stock_location = COALESCE(NULLIF(m.stock_location, ''), NULLIF(d.stock_location, ''), %s)
			WHERE m.reference_doctype = %s
			  AND (COALESCE(m.branch, '') = '' OR COALESCE(m.stock_location, '') = '')
			""",
			(branch, location, reference_doctype),
		)

	frappe.db.sql(
		"""
		UPDATE `tabLedgix Stock Movement`
		SET branch = COALESCE(NULLIF(branch, ''), %s),
		    stock_location = COALESCE(NULLIF(stock_location, ''), %s)
		WHERE COALESCE(branch, '') = '' OR COALESCE(stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_lots(branch, location):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix Stock Lot` l
		LEFT JOIN `tabLedgix Purchase` p ON p.name = l.purchase
		SET l.branch = COALESCE(NULLIF(l.branch, ''), NULLIF(p.branch, ''), %s),
		    l.stock_location = COALESCE(NULLIF(l.stock_location, ''), NULLIF(p.stock_location, ''), %s)
		WHERE COALESCE(l.branch, '') = '' OR COALESCE(l.stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_serials(branch, location):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix Stock Serial` sn
		LEFT JOIN `tabLedgix Purchase` p ON p.name = sn.purchase
		SET sn.branch = COALESCE(NULLIF(sn.branch, ''), NULLIF(p.branch, ''), %s),
		    sn.stock_location = COALESCE(NULLIF(sn.stock_location, ''), NULLIF(p.stock_location, ''), %s)
		WHERE COALESCE(sn.branch, '') = '' OR COALESCE(sn.stock_location, '') = ''
		""",
		(branch, location),
	)


def _backfill_payments(branch):
	frappe.db.sql(
		"""
		UPDATE `tabLedgix Payment` p
		LEFT JOIN `tabLedgix POS Shift` sh ON sh.name = p.pos_shift
		SET p.branch = COALESCE(NULLIF(p.branch, ''), NULLIF(sh.branch, ''), %s)
		WHERE COALESCE(p.branch, '') = ''
		""",
		(branch,),
	)

	frappe.db.sql(
		"""
		UPDATE `tabLedgix Payment` p
		JOIN `tabLedgix Payment Allocation` pa ON pa.parent = p.name
		JOIN `tabLedgix Sale` s ON pa.reference_doctype = 'Ledgix Sale' AND s.name = pa.reference_name
		SET p.branch = s.branch
		WHERE COALESCE(p.branch, '') = '' AND COALESCE(s.branch, '') != ''
		"""
	)

	frappe.db.sql(
		"UPDATE `tabLedgix Payment` SET branch=%s WHERE COALESCE(branch, '') = ''",
		(branch,),
	)
