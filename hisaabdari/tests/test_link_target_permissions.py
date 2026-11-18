import frappe
from frappe.core.doctype.user_permission.test_user_permission import create_user
from frappe.permissions import add_user_permission, remove_user_permission

from hisaabdari.tests.utils import ERPNextTestSuite


class TestLinkTargetSelectPermissions(ERPNextTestSuite):
	"""A role that can write a form must be able to use that form's link pickers.

	The DocPerm rows behind this grant `select` on the link target and nothing else, so
	each case asserts both halves: the picker fills, and no `read` arrives with it.
	Delivery User on Supplier stands in for these rows; it holds no other right on Supplier.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.user = create_user("_test_link_target_select@example.com", "Delivery User").name
		cls.supplier = cls.make_supplier("_Test Link Target Supplier")
		cls.other_supplier = cls.make_supplier("_Test Link Target Supplier 2")

	@staticmethod
	def make_supplier(supplier_name):
		if existing := frappe.db.get_value("Supplier", {"supplier_name": supplier_name}):
			return existing

		return (
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": supplier_name,
					"supplier_group": "_Test Supplier Group",
					"website": "https://example.com",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_granted_role_can_search_the_link_target(self):
		frappe.set_user(self.user)

		self.assertTrue(frappe.has_permission("Supplier", "select"))
		self.assertIn(self.supplier, frappe.get_list("Supplier", pluck="name"))

	def test_select_does_not_grant_read(self):
		self.assertFalse(frappe.has_permission("Supplier", "read", user=self.user))
		self.assertFalse(frappe.has_permission("Supplier", "write", user=self.user))

	def test_select_exposes_search_fields_only(self):
		frappe.set_user(self.user)

		row = frappe.get_list("Supplier", filters={"name": self.supplier}, fields=["name", "website"])[0]

		# website is not a Supplier search field, so a select-only role never receives it
		self.assertIn("name", row)
		self.assertNotIn("website", row)

	def test_doctype_without_a_grant_stays_denied(self):
		frappe.set_user(self.user)

		self.assertRaises(frappe.PermissionError, frappe.get_list, "Sales Invoice")

	def test_user_permissions_still_filter_a_select_only_target(self):
		add_user_permission("Supplier", self.supplier, self.user)
		try:
			frappe.set_user(self.user)
			self.assertEqual(frappe.get_list("Supplier", pluck="name"), [self.supplier])
		finally:
			frappe.set_user("Administrator")
			remove_user_permission("Supplier", self.supplier, self.user)
