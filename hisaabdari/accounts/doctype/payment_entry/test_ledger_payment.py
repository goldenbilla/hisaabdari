# Copyright (c) 2026, HisaabDari contributors
# See license.txt

import frappe
from frappe.utils import nowdate

from hisaabdari.accounts.doctype.account.test_account import create_account
from hisaabdari.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company"
CASH = "_Test Cash - _TC"


def make_ledger_payment(payment_type, ledger_account, amount=500, submit=True, **args):
	pe = frappe.new_doc("Payment Entry")
	pe.company = COMPANY
	pe.posting_date = nowdate()
	pe.payment_type = payment_type
	pe.party_or_ledger = "Ledger Account"
	pe.ledger_account = ledger_account
	pe.set("paid_from" if payment_type == "Pay" else "paid_to", args.get("cash_account") or CASH)
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.update({k: v for k, v in args.items() if k != "cash_account"})
	pe.insert()
	if submit:
		pe.submit()
	return pe


def get_gl(voucher_no):
	return {
		row.account: row
		for row in frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": voucher_no, "is_cancelled": 0},
			fields=["account", "debit", "credit", "party_type", "party", "against", "cost_center"],
		)
	}


class TestLedgerPayment(ERPNextTestSuite):
	def setUp(self):
		self.expense_account = create_account(
			account_name="Ledger Payment Expense", parent_account="Indirect Expenses - _TC", company=COMPANY
		)
		self.equity_account = create_account(
			account_name="Ledger Payment Capital", parent_account="Equity - _TC", company=COMPANY
		)

	def test_pay_to_expense_account(self):
		pe = make_ledger_payment("Pay", self.expense_account, 500)

		self.assertEqual(pe.paid_to, self.expense_account)
		self.assertEqual(pe.paid_from, CASH)
		self.assertFalse(pe.party_type)
		self.assertFalse(pe.party)
		self.assertEqual(pe.title, self.expense_account)
		self.assertEqual(pe.difference_amount, 0)
		self.assertEqual(pe.unallocated_amount, 0)
		self.assertEqual(pe.status, "Submitted")

		gl = get_gl(pe.name)
		self.assertEqual(len(gl), 2)
		self.assertEqual(gl[self.expense_account].debit, 500)
		self.assertEqual(gl[self.expense_account].credit, 0)
		self.assertEqual(gl[CASH].credit, 500)
		self.assertEqual(gl[CASH].debit, 0)
		self.assertFalse(gl[self.expense_account].party)
		self.assertEqual(gl[self.expense_account].against, CASH)
		self.assertEqual(gl[CASH].against, self.expense_account)
		self.assertTrue(gl[self.expense_account].cost_center)

		self.assertFalse(
			frappe.db.exists("Payment Ledger Entry", {"voucher_type": "Payment Entry", "voucher_no": pe.name})
		)

	def test_receive_into_equity_account(self):
		pe = make_ledger_payment("Receive", self.equity_account, 2000)

		self.assertEqual(pe.paid_from, self.equity_account)
		self.assertEqual(pe.paid_to, CASH)

		gl = get_gl(pe.name)
		self.assertEqual(len(gl), 2)
		self.assertEqual(gl[self.equity_account].credit, 2000)
		self.assertEqual(gl[CASH].debit, 2000)

	def test_cancel_reverses_ledger(self):
		pe = make_ledger_payment("Pay", self.expense_account, 300)
		pe.cancel()
		self.assertEqual(get_gl(pe.name), {})
		self.assertEqual(pe.status, "Cancelled")

	def test_receivable_and_payable_accounts_are_refused(self):
		for account in ("Debtors - _TC", "Creditors - _TC"):
			self.assertRaises(
				frappe.ValidationError, make_ledger_payment, "Pay", account, submit=False
			)

	def test_group_account_is_refused(self):
		self.assertRaises(
			frappe.ValidationError, make_ledger_payment, "Pay", "Indirect Expenses - _TC", submit=False
		)

	def test_same_account_on_both_sides_is_refused(self):
		self.assertRaises(frappe.ValidationError, make_ledger_payment, "Pay", CASH, submit=False)

	def test_ledger_account_is_mandatory(self):
		self.assertRaises(frappe.ValidationError, make_ledger_payment, "Pay", None, submit=False)

	def test_party_details_are_cleared(self):
		pe = make_ledger_payment(
			"Pay", self.expense_account, 100, submit=False, party_type="Supplier", party="_Test Supplier"
		)
		self.assertFalse(pe.party_type)
		self.assertFalse(pe.party)
		self.assertEqual(pe.paid_to, self.expense_account)

	def test_party_payment_fills_the_selector(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry

		pe = create_payment_entry(save=True)
		self.assertEqual(pe.party_or_ledger, "Supplier")
		self.assertFalse(pe.ledger_account)
		self.assertEqual(pe.title, "_Test Supplier")

	def test_internal_transfer_ignores_the_selector(self):
		pe = frappe.new_doc("Payment Entry")
		pe.update(
			{
				"company": COMPANY,
				"payment_type": "Internal Transfer",
				"party_or_ledger": "Ledger Account",
				"ledger_account": self.expense_account,
				"paid_from": CASH,
				"paid_to": "_Test Bank - _TC",
				"paid_amount": 100,
				"received_amount": 100,
				"reference_no": "T1",
				"reference_date": nowdate(),
			}
		)
		pe.insert()
		self.assertFalse(pe.party_or_ledger)
		self.assertFalse(pe.ledger_account)
		self.assertEqual(pe.paid_to, "_Test Bank - _TC")
