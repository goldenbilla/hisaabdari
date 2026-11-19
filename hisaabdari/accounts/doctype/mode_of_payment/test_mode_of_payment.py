# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import frappe

from hisaabdari.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company"


class TestModeofPayment(ERPNextTestSuite):
	"""Mode of Payment validates its per-company default accounts (account company
	must match the row, no company twice)."""

	def setUp(self):
		frappe.set_user("Administrator")

	def make_mop(self, accounts=None, enabled=1):
		doc = frappe.new_doc("Mode of Payment")
		doc.mode_of_payment = f"_Test MoP {frappe.generate_hash(length=6)}"
		doc.type = "General"
		doc.enabled = enabled
		for company, account in accounts or []:
			doc.append("accounts", {"company": company, "default_account": account})
		return doc

	def test_valid_mode_of_payment_saves(self):
		for account in ("_Test Bank - _TC", "Cash - _TC", "Debtors - _TC"):
			with self.subTest(account=account):
				doc = self.make_mop(accounts=[(COMPANY, account)]).insert()
				self.assertTrue(doc.name)

	def test_invalid_default_accounts_are_rejected(self):
		frappe.db.set_value("Account", "Cash - _TC", "disabled", 1)
		for account, error in (
			("Bank Accounts - _TC", "must be a ledger account"),
			("Sales - _TC", "must be a ledger account"),
			("Creditors - _TC", "must be a ledger account"),
			("Cash - _TC", "is disabled"),
		):
			with self.subTest(account=account):
				doc = self.make_mop(accounts=[(COMPANY, account)])
				with self.assertRaisesRegex(frappe.ValidationError, error):
					doc.insert()

	def test_disabled_mode_cannot_be_used_on_transactions(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry
		from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		mode = self.make_mop(accounts=[(COMPANY, "Cash - _TC")]).insert()
		payment = create_payment_entry()
		payment.mode_of_payment = mode.name
		payment.insert()
		mode.enabled = 0
		mode.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Mode of Payment .* is disabled"):
			payment.submit()

		payment.reload()
		mode.enabled = 1
		mode.save()
		payment.submit()
		self.assertEqual(payment.docstatus, 1)
		mode.enabled = 0
		mode.save()
		payment.cancel()
		self.assertEqual(payment.docstatus, 2)

		invoice = create_sales_invoice(is_pos=1, do_not_save=True)
		invoice.append("payments", {"mode_of_payment": mode.name, "amount": 100, "account": "Cash - _TC"})
		with self.assertRaisesRegex(frappe.ValidationError, "Mode of Payment .* is disabled"):
			invoice.insert()

	def test_account_of_wrong_company_throws(self):
		other_account = frappe.db.get_value("Account", {"company": "_Test Company 1", "is_group": 0}, "name")
		self.assertTrue(other_account, "need a non-group account in _Test Company 1")
		doc = self.make_mop(accounts=[(COMPANY, other_account)])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_repeating_company_throws(self):
		doc = self.make_mop(accounts=[(COMPANY, "Cash - _TC"), (COMPANY, "Debtors - _TC")])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_disabling_unreferenced_mode_succeeds(self):
		doc = self.make_mop(accounts=[(COMPANY, "Cash - _TC")], enabled=0)
		doc.insert()
		self.assertEqual(doc.enabled, 0)


def set_default_account_for_mode_of_payment(mode_of_payment, company, account):
	mode_of_payment.reload()
	if frappe.db.exists(
		"Mode of Payment Account", {"parent": mode_of_payment.mode_of_payment, "company": company}
	):
		frappe.db.set_value(
			"Mode of Payment Account",
			{"parent": mode_of_payment.mode_of_payment, "company": company},
			"default_account",
			account,
		)
		return

	mode_of_payment.append("accounts", {"company": company, "default_account": account})
	mode_of_payment.save()
