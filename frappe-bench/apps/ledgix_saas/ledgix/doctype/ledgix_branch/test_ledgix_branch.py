import frappe
from frappe.tests.utils import FrappeTestCase


class TestLedgixBranch(FrappeTestCase):
	def test_branch_code_is_normalized(self):
		brand = frappe.get_doc(
			{
				"doctype": "Ledgix Restaurant Brand",
				"brand_code": "TESTBRAND",
				"brand_name": "Test Brand",
			}
		).insert()
		branch = frappe.get_doc(
			{
				"doctype": "Ledgix Branch",
				"restaurant_brand": brand.name,
				"branch_code": "branch_01",
				"branch_name": "Branch 01",
			}
		).insert()
		self.assertEqual(branch.name, "BRANCH_01")
