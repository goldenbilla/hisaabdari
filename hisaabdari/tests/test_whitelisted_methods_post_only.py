import importlib

import frappe

from hisaabdari.tests.utils import ERPNextTestSuite

POST_ONLY_METHODS = (
	"hisaabdari.controllers.accounts_controller.update_company_master_and_address",
	"hisaabdari.selling.doctype.customer.customer.Customer.get_customer_group_details",
	"hisaabdari.setup.doctype.company.company.add_node",
	"hisaabdari.stock.doctype.batch.batch.split_batch",
	"hisaabdari.stock.doctype.warehouse.warehouse.add_node",
)


class TestWhitelistedMethodsPostOnly(ERPNextTestSuite):
	def test_state_changing_methods_accept_only_post(self):
		for path in POST_ONLY_METHODS:
			with self.subTest(path=path):
				method = resolve(path)
				self.assertIn(method, frappe.whitelisted)
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func.get(method), ["POST"])


def resolve(path: str):
	"""Resolve a dotted path to a module function or a class method."""
	module_path, _, attribute = path.rpartition(".")
	try:
		return getattr(importlib.import_module(module_path), attribute)
	except ModuleNotFoundError:
		module_path, _, class_name = module_path.rpartition(".")
		return getattr(getattr(importlib.import_module(module_path), class_name), attribute)
