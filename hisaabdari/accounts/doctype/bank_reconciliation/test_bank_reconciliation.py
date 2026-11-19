# Copyright (c) 2026, HisaabDari contributors
# See license.txt

import os

import frappe
from frappe.utils import add_days, flt, nowdate

from hisaabdari.accounts.doctype.account.test_account import create_account
from hisaabdari.accounts.doctype.bank_reconciliation import bank_reconciliation as br
from hisaabdari.accounts.doctype.payment_entry.test_ledger_payment import make_ledger_payment
from hisaabdari.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company"


class TestBankReconciliation(ERPNextTestSuite):
	def setUp(self):
		# A bank account of its own, so entries made by other tests do not appear here.
		self.bank = create_account(
			account_name="Reconciliation Test Bank",
			parent_account="Bank Accounts - _TC",
			company=COMPANY,
			account_type="Bank",
		)
		self.other_bank = create_account(
			account_name="Reconciliation Other Bank",
			parent_account="Bank Accounts - _TC",
			company=COMPANY,
			account_type="Bank",
		)
		self.charges = create_account(
			account_name="Reconciliation Bank Charges", parent_account="Indirect Expenses - _TC", company=COMPANY
		)
		self.capital = create_account(
			account_name="Reconciliation Capital", parent_account="Equity - _TC", company=COMPANY
		)
		self.today = nowdate()
		self.doc = frappe.get_doc(
			{
				"doctype": "Bank Reconciliation",
				"company": COMPANY,
				"bank_account": self.bank,
				"from_date": add_days(self.today, -30),
				"to_date": self.today,
			}
		).insert()

	# helpers -----------------------------------------------------------------------------------

	def pay(self, account, amount, **args):
		return make_ledger_payment(
			"Pay", account, amount, cash_account=self.bank, reference_no="R1", reference_date=self.today, **args
		)

	def receive(self, account, amount, **args):
		return make_ledger_payment(
			"Receive", account, amount, cash_account=self.bank, reference_no="R1", reference_date=self.today, **args
		)

	def line(self, deposit=0, withdrawal=0, description="LINE", date=None, reference_no=None):
		br.add_statement_line(
			self.doc.name,
			date or self.today,
			description=description,
			deposit=deposit,
			withdrawal=withdrawal,
			reference_no=reference_no,
		)
		return frappe.get_all(
			"Bank Reconciliation Line",
			filters={"bank_reconciliation": self.doc.name},
			order_by="sequence desc",
			limit=1,
			pluck="name",
		)[0]

	def voucher(self, doc):
		return {"voucher_type": doc.doctype, "voucher_no": doc.name}

	def data(self):
		return frappe._dict(br.get_reconciliation_data(self.doc.name))

	def line_status(self, name):
		return frappe.db.get_value("Bank Reconciliation Line", name, "status")

	# matching ----------------------------------------------------------------------------------

	def test_one_line_to_one_entry(self):
		payment = self.pay(self.charges, 500)
		line = self.line(withdrawal=500, date=add_days(self.today, -1))

		data = self.data()
		self.assertEqual(len(data.to_check), 1)
		suggestion = data.to_check[0].suggestion
		self.assertEqual(suggestion["type"], "match")
		self.assertEqual(suggestion["vouchers"][0].voucher_no, payment.name)

		match = br.create_match(self.doc.name, [line], [self.voucher(payment)])
		self.assertEqual(self.line_status(line), "Done")
		self.assertEqual(
			str(frappe.db.get_value("Payment Entry", payment.name, "clearance_date")), add_days(self.today, -1)
		)
		self.assertEqual(frappe.db.get_value("Bank Match", match, "match_type"), "Match")

		data = self.data()
		self.assertEqual(data.to_check, [])
		self.assertEqual(data.not_on_statement, [])
		self.assertEqual(len(data.matches), 1)

	def test_many_lines_to_one_entry(self):
		"""Twelve bank charge lines on the statement against one entry of their total in the books."""
		payment = self.pay(self.charges, 2100)
		lines = [self.line(withdrawal=175, description=f"BANK CHARGES SMS {n:03d}") for n in range(12)]

		data = self.data()
		suggestions = [d.suggestion for d in data.to_check]
		self.assertTrue(all(s["type"] == "group" for s in suggestions))
		self.assertEqual({s["group"] for s in suggestions}, {suggestions[0]["group"]})
		self.assertEqual(suggestions[0]["size"], 12)
		self.assertEqual(suggestions[0]["total"], -2100)
		self.assertEqual(suggestions[0]["vouchers"][0].voucher_no, payment.name)

		br.create_match(self.doc.name, lines, [self.voucher(payment)])
		self.assertEqual({self.line_status(d) for d in lines}, {"Done"})
		self.assertEqual(self.data().summary["lines_to_check"], 0)

	def test_one_line_to_many_entries(self):
		first = self.pay(self.charges, 7000)
		second = self.pay(self.charges, 5000)
		line = self.line(withdrawal=12000)
		br.create_match(self.doc.name, [line], [self.voucher(first), self.voucher(second)])
		self.assertEqual(self.line_status(line), "Done")
		self.assertEqual(len(self.data().matches[0].entries), 2)

	def test_many_to_many(self):
		payments = [self.pay(self.charges, 300), self.pay(self.charges, 700)]
		lines = [self.line(withdrawal=400), self.line(withdrawal=600)]
		br.create_match(self.doc.name, lines, [self.voucher(d) for d in payments])
		self.assertEqual({self.line_status(d) for d in lines}, {"Done"})

	def test_unbalanced_match_is_refused(self):
		payment = self.pay(self.charges, 2100)
		line = self.line(withdrawal=2150)
		self.assertRaises(frappe.ValidationError, br.create_match, self.doc.name, [line], [self.voucher(payment)])
		self.assertEqual(self.line_status(line), "To Check")
		self.assertFalse(frappe.db.exists("Bank Match", {"bank_reconciliation": self.doc.name}))
		self.assertFalse(frappe.db.get_value("Payment Entry", payment.name, "clearance_date"))

	def test_money_in_does_not_match_money_out(self):
		payment = self.pay(self.charges, 500)
		line = self.line(deposit=500)
		self.assertIsNone(self.data().to_check[0].get("suggestion"))
		self.assertRaises(frappe.ValidationError, br.create_match, self.doc.name, [line], [self.voucher(payment)])

	def test_entry_cannot_be_matched_twice(self):
		payment = self.pay(self.charges, 500)
		first, second = self.line(withdrawal=500), self.line(withdrawal=500, description="SECOND")
		br.create_match(self.doc.name, [first], [self.voucher(payment)])
		self.assertRaises(frappe.ValidationError, br.create_match, self.doc.name, [second], [self.voucher(payment)])

	def test_entry_of_another_account_is_refused(self):
		other = make_ledger_payment(
			"Pay", self.charges, 500, cash_account=self.other_bank, reference_no="R1", reference_date=self.today
		)
		line = self.line(withdrawal=500)
		self.assertRaises(frappe.ValidationError, br.create_match, self.doc.name, [line], [self.voucher(other)])

	def test_undo_match(self):
		payment = self.pay(self.charges, 500)
		line = self.line(withdrawal=500)
		match = br.create_match(self.doc.name, [line], [self.voucher(payment)])
		br.undo_match(self.doc.name, match)

		self.assertEqual(self.line_status(line), "To Check")
		self.assertFalse(frappe.db.get_value("Bank Reconciliation Line", line, "bank_match"))
		self.assertFalse(frappe.db.get_value("Payment Entry", payment.name, "clearance_date"))
		self.assertEqual(len(self.data().not_on_statement), 1)

	# new entries -------------------------------------------------------------------------------

	def test_new_entry_for_money_out(self):
		line = self.line(withdrawal=150, description="BANK CHARGES SMS ALERT", reference_no="778")
		result = br.create_entry_and_match(
			self.doc.name, [line], {"party_or_ledger": "Ledger Account", "ledger_account": self.charges}
		)
		payment = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(payment.docstatus, 1)
		self.assertEqual(payment.payment_type, "Pay")
		self.assertEqual(payment.paid_from, self.bank)
		self.assertEqual(payment.paid_to, self.charges)
		self.assertEqual(payment.paid_amount, 150)
		self.assertEqual(payment.reference_no, "778")
		self.assertEqual(self.line_status(line), "Done")

		gl = {
			d.account: d
			for d in frappe.get_all(
				"GL Entry",
				filters={"voucher_no": payment.name, "is_cancelled": 0},
				fields=["account", "debit", "credit"],
			)
		}
		self.assertEqual(gl[self.charges].debit, 150)
		self.assertEqual(gl[self.bank].credit, 150)

		match = frappe.get_doc("Bank Match", result["bank_match"])
		self.assertEqual(match.match_type, "New Entry")
		self.assertEqual(match.entries[0].created_by_match, 1)

	def test_new_entry_for_money_in_from_customer(self):
		line = self.line(deposit=900, description="IBFT FROM CUSTOMER")
		result = br.create_entry_and_match(
			self.doc.name, [line], {"party_or_ledger": "Customer", "party": "_Test Customer"}
		)
		payment = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(payment.payment_type, "Receive")
		self.assertEqual(payment.party, "_Test Customer")
		self.assertEqual(payment.paid_to, self.bank)
		self.assertEqual(payment.unallocated_amount, 900)

	def test_new_entry_for_the_difference(self):
		"""Lines add up to 2,150 but the books hold 2,100: the 50 is entered and all of it matched."""
		payment = self.pay(self.charges, 2100)
		lines = [self.line(withdrawal=1000), self.line(withdrawal=1150)]
		result = br.create_entry_and_match(
			self.doc.name,
			lines,
			{"party_or_ledger": "Ledger Account", "ledger_account": self.charges},
			vouchers=[self.voucher(payment)],
		)
		extra = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(extra.payment_type, "Pay")
		self.assertEqual(extra.paid_amount, 50)
		self.assertEqual(len(frappe.get_doc("Bank Match", result["bank_match"]).entries), 2)
		self.assertEqual({self.line_status(d) for d in lines}, {"Done"})

	def test_undo_can_cancel_the_entry_it_created(self):
		line = self.line(withdrawal=150)
		result = br.create_entry_and_match(
			self.doc.name, [line], {"party_or_ledger": "Ledger Account", "ledger_account": self.charges}
		)
		br.undo_match(self.doc.name, result["bank_match"], cancel_created_entries=1)
		self.assertEqual(frappe.db.get_value("Payment Entry", result["payment_entry"], "docstatus"), 2)
		self.assertEqual(self.line_status(line), "To Check")
		self.assertEqual(self.data().not_on_statement, [])

	def test_new_entry_saves_a_rule_and_the_rule_is_suggested(self):
		first = self.line(withdrawal=150, description="BANK CHARGES SMS ALERT 001")
		br.create_entry_and_match(
			self.doc.name,
			[first],
			{
				"party_or_ledger": "Ledger Account",
				"ledger_account": self.charges,
				"save_rule": 1,
				"rule_text": "Bank Charges SMS",
			},
		)
		self.line(withdrawal=200, description="bank charges sms alert 002")
		suggestion = self.data().to_check[0].suggestion
		self.assertEqual(suggestion["type"], "rule")
		self.assertEqual(suggestion["ledger_account"], self.charges)

	def test_transfer(self):
		line = self.line(withdrawal=4000, description="TRANSFER TO OTHER ACCOUNT")
		result = br.create_transfer_and_match(self.doc.name, [line], self.other_bank)
		payment = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(payment.payment_type, "Internal Transfer")
		self.assertEqual(payment.paid_from, self.bank)
		self.assertEqual(payment.paid_to, self.other_bank)
		self.assertEqual(self.line_status(line), "Done")

		# The other bank's reconciliation sees the same transfer as money in, still to be matched.
		entries = br.get_uncleared_entries(self.other_bank, self.today)
		self.assertEqual([(d.voucher_no, d.amount) for d in entries], [(payment.name, 4000)])

	# without a statement file --------------------------------------------------------------------

	def test_mark_cleared_without_statement(self):
		payment = self.pay(self.charges, 500)
		br.mark_cleared(self.doc.name, [self.voucher(payment)], clearance_date=self.today)
		data = self.data()
		self.assertEqual(data.not_on_statement, [])
		self.assertEqual(data.matches[0].match_type, "Without Statement")
		self.assertEqual(str(frappe.db.get_value("Payment Entry", payment.name, "clearance_date")), self.today)

	def test_mark_all_cleared(self):
		self.pay(self.charges, 500)
		self.receive(self.capital, 9000)
		self.assertEqual(br.mark_all_cleared(self.doc.name, self.today), 2)
		self.assertEqual(self.data().not_on_statement, [])

	def test_entry_cleared_by_erpnext_before_is_not_offered(self):
		payment = self.pay(self.charges, 500)
		frappe.db.set_value("Payment Entry", payment.name, "clearance_date", self.today)
		self.assertEqual(self.data().not_on_statement, [])

	# summary -----------------------------------------------------------------------------------

	def test_summary(self):
		self.receive(self.capital, 10000)  # on the statement
		cleared_payment = self.pay(self.charges, 1500)  # on the statement
		self.pay(self.charges, 700)  # cheque not yet presented
		self.receive(self.capital, 300)  # deposit not yet credited

		in_line = self.line(deposit=10000)
		out_line = self.line(withdrawal=1500)
		self.line(withdrawal=40, description="BANK CHARGES")  # at the bank, not in the books

		capital_entry = [d for d in self.data().candidates if d.amount == 10000][0]
		br.create_match(self.doc.name, [in_line], [capital_entry])
		br.create_match(self.doc.name, [out_line], [self.voucher(cleared_payment)])

		# statement: +10,000 - 1,500 - 40
		self.doc.db_set("statement_closing_balance", 8460)
		self.doc.reload()
		summary = self.data().summary
		self.assertEqual(summary["book_balance"], 8100)  # 10,000 - 1,500 - 700 + 300
		self.assertEqual(summary["payments_not_presented"], 700)
		self.assertEqual(summary["receipts_not_credited"], 300)
		self.assertEqual(summary["expected_bank_balance"], 8500)
		self.assertEqual(summary["unbooked_out"], 40)
		self.assertEqual(summary["lines_to_check"], 1)
		self.assertEqual(summary["difference"], 0)

		self.assertRaises(frappe.ValidationError, br.close_reconciliation, self.doc.name)

		charges_line = self.data().to_check[0].name
		br.create_entry_and_match(
			self.doc.name, [charges_line], {"party_or_ledger": "Ledger Account", "ledger_account": self.charges}
		)
		summary = br.close_reconciliation(self.doc.name)
		self.assertEqual(summary["book_balance"], 8060)
		self.assertEqual(summary["expected_bank_balance"], 8460)
		self.assertEqual(summary["difference"], 0)

		self.doc.reload()
		self.assertEqual(self.doc.status, "Closed")
		self.assertEqual(self.doc.book_balance, 8060)
		self.assertRaises(frappe.ValidationError, br.add_statement_line, self.doc.name, self.today, deposit=5)

		br.reopen_reconciliation(self.doc.name)
		self.assertEqual(frappe.db.get_value("Bank Reconciliation", self.doc.name, "status"), "Open")

	def test_close_refused_when_balance_differs(self):
		self.receive(self.capital, 10000)
		entry = self.data().candidates[0]
		line = self.line(deposit=10000)
		br.create_match(self.doc.name, [line], [entry])
		self.doc.db_set("statement_closing_balance", 9000)
		self.assertRaises(frappe.ValidationError, br.close_reconciliation, self.doc.name)

	# statement lines ---------------------------------------------------------------------------

	def test_duplicate_lines_are_left_out(self):
		lines = [
			{"date": self.today, "description": "ATM WITHDRAWAL", "withdrawal": 5000, "deposit": 0},
			{"date": self.today, "description": "ATM WITHDRAWAL", "withdrawal": 5000, "deposit": 0},
			{"date": self.today, "description": "SALARY", "withdrawal": 0, "deposit": 90000},
		]
		# Two identical lines in one file are two real transactions.
		self.assertEqual(br.add_lines(self.doc, lines), (3, 0))
		# The same file again adds nothing.
		self.assertEqual(br.add_lines(self.doc, lines), (0, 3))
		# A file that overlaps adds only what is new.
		lines.append({"date": self.today, "description": "CHEQUE 12", "withdrawal": 100, "deposit": 0})
		self.assertEqual(br.add_lines(self.doc, lines), (1, 3))

	def test_line_needs_exactly_one_side(self):
		self.assertRaises(frappe.ValidationError, br.add_statement_line, self.doc.name, self.today)
		self.assertRaises(
			frappe.ValidationError, br.add_statement_line, self.doc.name, self.today, deposit=5, withdrawal=5
		)

	def test_delete_reconciliation(self):
		payment = self.pay(self.charges, 500)
		line = self.line(withdrawal=500)
		match = br.create_match(self.doc.name, [line], [self.voucher(payment)])
		self.assertRaises(frappe.ValidationError, self.doc.delete)
		br.undo_match(self.doc.name, match)
		self.doc.delete()
		self.assertFalse(frappe.db.exists("Bank Reconciliation Line", line))

	def test_only_bank_and_cash_accounts(self):
		doc = frappe.get_doc(
			{
				"doctype": "Bank Reconciliation",
				"company": COMPANY,
				"bank_account": self.charges,
				"from_date": self.today,
				"to_date": self.today,
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	# statement files ---------------------------------------------------------------------------

	def upload(self, file_name):
		path = os.path.join(
			os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "test_files", "bank_statements", file_name
		)
		with open(path, "rb") as f:
			content = f.read()
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{frappe.generate_hash(length=6)}-{file_name}",
				"content": content,
				"is_private": 1,
				"attached_to_doctype": "Bank Reconciliation",
				"attached_to_name": self.doc.name,
			}
		).insert()
		return file.file_url

	def test_read_and_import_csv(self):
		file_url = self.upload("separate_columns.csv")

		preview = br.read_statement_file(self.doc.name, file_url)
		self.assertEqual(preview["line_count"], 4)
		self.assertEqual(preview["header"]["iban"], "PK36SMPL0000111122223333")
		self.assertEqual(preview["account_check"]["status"], "unknown")
		self.assertFalse(frappe.db.exists("Bank Reconciliation Line", {"bank_reconciliation": self.doc.name}))

		result = br.import_statement_file(self.doc.name, file_url)
		self.assertEqual((result["added"], result["skipped"]), (4, 0))
		lines = frappe.get_all(
			"Bank Reconciliation Line",
			filters={"bank_reconciliation": self.doc.name},
			fields=["date", "description", "reference_no", "withdrawal", "deposit", "balance", "status"],
			order_by="sequence",
		)
		self.assertEqual(len(lines), 4)
		self.assertEqual(str(lines[0].date), "2026-10-01")
		self.assertEqual(lines[0].description, "Cheque paid Karim Packaging")
		self.assertEqual(lines[0].reference_no, "00451201")
		self.assertEqual((lines[0].withdrawal, lines[0].deposit, lines[0].balance), (1250, 0, 98750))
		self.assertEqual({d.status for d in lines}, {"To Check"})

		# The closing balance printed on the statement is filled in, and the layout is remembered.
		self.assertEqual(frappe.db.get_value("Bank Reconciliation", self.doc.name, "statement_closing_balance"), 114595.25)
		self.assertEqual(frappe.db.get_value("Bank Statement Layout", self.bank, "file_type"), "csv")

		# The same file again adds nothing.
		again = br.import_statement_file(self.doc.name, self.upload("separate_columns.csv"))
		self.assertEqual((again["added"], again["skipped"]), (0, 4))

	def test_import_pdf_with_header(self):
		file_url = self.upload("multi_page.pdf")
		preview = br.read_statement_file(self.doc.name, file_url)
		self.assertEqual(preview["file_type"], "pdf")
		self.assertEqual(preview["header"]["account_title"], "Sitara Hardware Store")
		self.assertEqual(preview["header"]["closing_balance"], 250984.75)

		result = br.import_statement_file(self.doc.name, file_url)
		self.assertEqual(result["added"], preview["line_count"])
		line = frappe.qb.DocType("Bank Reconciliation Line")
		totals = (
			frappe.qb.from_(line)
			.select(frappe.query_builder.functions.Sum(line.deposit), frappe.query_builder.functions.Sum(line.withdrawal))
			.where(line.bank_reconciliation == self.doc.name)
		).run()[0]
		# opening 250,000.00 plus money in less money out is the closing balance printed in the header
		self.assertEqual(flt(250000 + totals[0] - totals[1], 2), 250984.75)

	def test_account_number_check(self):
		header = {"iban": "PK36 SMPL 0000 1111 2222 3333", "account_number": "0123-4567890-01"}
		self.assertEqual(br.check_account(self.doc, header)["status"], "unknown")
		self.assertEqual(br.check_account(self.doc, {})["status"], "unknown")

		if not frappe.db.exists("Bank", "Reconciliation Test Bank"):
			frappe.get_doc({"doctype": "Bank", "bank_name": "Reconciliation Test Bank"}).insert()
		record = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": "Reconciliation Test",
				"bank": "Reconciliation Test Bank",
				"account": self.bank,
				"company": COMPANY,
				"is_company_account": 1,
				"bank_account_no": "0123456789001",
			}
		).insert()
		self.assertEqual(br.check_account(self.doc, header)["status"], "ok")

		record.db_set("bank_account_no", "9999999999999")
		self.assertEqual(br.check_account(self.doc, header)["status"], "mismatch")

	def test_unreadable_file_gives_a_plain_message(self):
		file_url = self.upload("scanned.pdf")
		self.assertRaises(frappe.ValidationError, br.read_statement_file, self.doc.name, file_url)
