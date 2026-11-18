# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

import frappe
from frappe.utils import today

from hisaabdari.accounts.report.trial_balance.trial_balance import execute
from hisaabdari.tests.utils import ERPNextTestSuite


class TestTrialBalance(ERPNextTestSuite):
	def test_opening_balances_follow_user_permissions(self):
		from frappe.utils import add_days

		from hisaabdari.accounts.doctype.journal_entry.test_journal_entry import make_journal_entry
		from hisaabdari.accounts.utils import get_fiscal_year
		from hisaabdari.tests.permission_test_utils import as_user, make_fenced_user

		fiscal_year, year_start, year_end = get_fiscal_year(today(), company="_Test Company")
		make_journal_entry("_Test Bank - _TC", "_Test Cash - _TC", 500, posting_date=year_start, submit=True)
		filters = frappe._dict(
			company="_Test Company",
			fiscal_year=fiscal_year,
			from_date=add_days(year_start, 5),
			to_date=year_end,
		)
		user = make_fenced_user(
			"tb-opening@example.com", ["Accounts User"], [("Account", "_Test Write Off - _TC")]
		)
		# a perpetual inventory company links an account the user is not permitted
		inventory_account = frappe.db.get_value("Company", "_Test Company", "default_inventory_account")
		self.addCleanup(
			frappe.db.set_value, "Company", "_Test Company", "default_inventory_account", inventory_account
		)
		frappe.db.set_value("Company", "_Test Company", "default_inventory_account", "Stock In Hand - _TC")
		with as_user(user):
			total_row = execute(frappe._dict(filters))[1][-1]
		self.assertEqual((total_row["opening_debit"], total_row["opening_credit"]), (0, 0))

		other_company_user = make_fenced_user(
			"tb-other-company@example.com", ["Accounts User"], [("Company", "_Test Company 1")]
		)
		with as_user(other_company_user):
			self.assertRaises(frappe.PermissionError, execute, frappe._dict(filters))

		with as_user(make_fenced_user("tb-auditor@example.com", ["Auditor"])):
			total_row = execute(frappe._dict(filters))[1][-1]
		self.assertEqual(total_row["opening_debit"], total_row["opening_credit"])

	def test_company_permission_follows_applicable_for(self):
		from hisaabdari.accounts.utils import get_fiscal_year
		from hisaabdari.tests.permission_test_utils import as_user, make_fenced_user

		company = "_Test Company"
		user = make_fenced_user("tb-company@example.com", ["Accounts User"])
		# a permission for another company, limited to Sales Invoice
		user_permission = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Company",
				"for_value": "_Test Company 1",
				"apply_to_all_doctypes": 0,
				"applicable_for": "Sales Invoice",
			}
		).insert(ignore_permissions=True)
		filters = frappe._dict(company=company, fiscal_year=get_fiscal_year(today(), company=company)[0])

		with as_user(user):
			execute(frappe._dict(filters))

		user_permission.update({"apply_to_all_doctypes": 1, "applicable_for": None})
		user_permission.save(ignore_permissions=True)
		with as_user(user), self.assertRaisesRegex(frappe.PermissionError, company):
			execute(frappe._dict(filters))
