import importlib

import frappe

from hisaabdari.tests.utils import ERPNextTestSuite

POST_ONLY_METHODS = (
	"hisaabdari.accounts.doctype.bank_account.bank_account.set_closing_balance_as_per_statement",
	"hisaabdari.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.update_bank_transaction",
	"hisaabdari.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.create_journal_entry_bts",
	"hisaabdari.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.create_payment_entry_bts",
	"hisaabdari.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.create_internal_transfer",
	"hisaabdari.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.reconcile_vouchers",
	"hisaabdari.accounts.doctype.bank_transaction.bank_transaction.unreconcile_transaction_entry",
	"hisaabdari.accounts.doctype.bisect_accounting_statements.bisect_accounting_statements.BisectAccountingStatements.bisect_left",
	"hisaabdari.accounts.doctype.bisect_accounting_statements.bisect_accounting_statements.BisectAccountingStatements.bisect_right",
	"hisaabdari.accounts.doctype.bisect_accounting_statements.bisect_accounting_statements.BisectAccountingStatements.move_up",
	"hisaabdari.accounts.doctype.budget.budget.revise_budget",
	"hisaabdari.accounts.doctype.cheque_print_template.cheque_print_template.create_or_update_cheque_print_format",
	"hisaabdari.accounts.doctype.payment_request.payment_request.make_payment_request",
	"hisaabdari.assets.doctype.location.location.add_node",
	"hisaabdari.buying.doctype.request_for_quotation.request_for_quotation.create_supplier_quotation",
	"hisaabdari.controllers.accounts_controller.update_company_master_and_address",
	"hisaabdari.controllers.stock_controller.make_quality_inspections",
	"hisaabdari.crm.doctype.lead.lead.make_lead_from_communication",
	"hisaabdari.crm.doctype.opportunity.opportunity.set_multiple_status",
	"hisaabdari.crm.doctype.opportunity.opportunity.make_opportunity_from_communication",
	"hisaabdari.manufacturing.doctype.work_order.work_order.set_work_order_ops",
	"hisaabdari.manufacturing.doctype.workstation.workstation.Workstation.start_job",
	"hisaabdari.manufacturing.doctype.workstation.workstation.Workstation.complete_job",
	"hisaabdari.projects.doctype.project.project.create_duplicate_project",
	"hisaabdari.projects.doctype.project.project.set_project_status",
	"hisaabdari.projects.doctype.task.task.set_multiple_status",
	"hisaabdari.projects.doctype.task.task.add_node",
	"hisaabdari.projects.doctype.task.task.add_multiple_tasks",
	"hisaabdari.quality_management.doctype.quality_procedure.quality_procedure.add_node",
	"hisaabdari.selling.doctype.customer.customer.Customer.get_customer_group_details",
	"hisaabdari.selling.doctype.sales_order.sales_order.make_work_orders",
	"hisaabdari.selling.page.point_of_sale.point_of_sale.set_customer_info",
	"hisaabdari.setup.doctype.company.company.add_node",
	"hisaabdari.setup.doctype.company.company.create_transaction_deletion_request",
	"hisaabdari.setup.doctype.department.department.add_node",
	"hisaabdari.setup.doctype.employee.employee.create_user",
	"hisaabdari.stock.doctype.batch.batch.split_batch",
	"hisaabdari.stock.doctype.material_request.material_request.raise_work_orders",
	"hisaabdari.stock.doctype.warehouse.warehouse.add_node",
	"hisaabdari.stock.report.stock_and_account_value_comparison.stock_and_account_value_comparison.create_reposting_entries",
	"hisaabdari.stock.report.stock_ledger_invariant_check.stock_ledger_invariant_check.create_reposting_entries",
	"hisaabdari.subcontracting.doctype.subcontracting_receipt.subcontracting_receipt.make_purchase_receipt",
	"hisaabdari.support.doctype.issue.issue.Issue.split_issue",
	"hisaabdari.support.doctype.issue.issue.make_issue_from_communication",
	"hisaabdari.support.doctype.service_level_agreement.service_level_agreement.reset_service_level_agreement",
	"hisaabdari.telephony.doctype.call_log.call_log.add_call_summary_and_call_type",
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
