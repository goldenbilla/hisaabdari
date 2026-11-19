# Copyright (c) 2026, HisaabDari contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class BankMatch(Document):
	"""One agreed match between bank statement lines and entries in the books.

	The statement lines point at this document (`Bank Reconciliation Line.bank_match`); the book
	entries are in `entries`. Deleting the document undoes the match.
	"""

	def validate(self):
		self.validate_entries()

	def validate_entries(self):
		from hisaabdari.accounts.doctype.bank_reconciliation.bank_reconciliation import (
			get_book_entry_amounts,
			get_cleared_vouchers,
		)

		seen = set()
		for row in self.entries:
			key = (row.voucher_type, row.voucher_no)
			if key in seen:
				frappe.throw(_("{0} {1} is entered twice").format(_(row.voucher_type), row.voucher_no))
			seen.add(key)

		amounts = get_book_entry_amounts(self.bank_account, list(seen))
		cleared = get_cleared_vouchers(self.bank_account, exclude_match=self.name)
		for row in self.entries:
			key = (row.voucher_type, row.voucher_no)
			if key not in amounts:
				frappe.throw(
					_("{0} {1} has no entry in {2}").format(_(row.voucher_type), row.voucher_no, self.bank_account)
				)
			if key in cleared:
				frappe.throw(
					_("{0} {1} is already matched to the bank statement").format(_(row.voucher_type), row.voucher_no)
				)
			row.amount = amounts[key]

	def get_statement_lines(self):
		return frappe.get_all(
			"Bank Reconciliation Line",
			filters={"bank_match": self.name},
			fields=["name", "deposit", "withdrawal", "date"],
		)

	def validate_balance(self, lines):
		"""The statement lines and the book entries of a match must add up to the same amount."""
		if self.match_type == "Without Statement":
			return

		precision = self.entries[0].precision("amount") if self.entries else 2
		line_total = flt(sum(flt(d.deposit) - flt(d.withdrawal) for d in lines), precision)
		entry_total = flt(sum(flt(d.amount) for d in self.entries), precision)
		if line_total != entry_total:
			frappe.throw(
				_("The statement lines add up to {0} but the entries in the books add up to {1}").format(
					frappe.format_value(line_total, {"fieldtype": "Currency"}),
					frappe.format_value(entry_total, {"fieldtype": "Currency"}),
				)
			)

	def set_clearance_dates(self, clearance_date):
		for row in self.entries:
			set_voucher_clearance_date(row.voucher_type, row.voucher_no, self.bank_account, clearance_date)

	def on_trash(self):
		for line in frappe.get_all("Bank Reconciliation Line", filters={"bank_match": self.name}, pluck="name"):
			frappe.db.set_value("Bank Reconciliation Line", line, {"bank_match": None, "status": "To Check"})
		self.set_clearance_dates(None)


def set_voucher_clearance_date(voucher_type, voucher_no, bank_account, clearance_date):
	"""Keep ERPNext's own clearance date fields in step, where the document has one."""
	if voucher_type in ("Payment Entry", "Journal Entry"):
		frappe.db.set_value(voucher_type, voucher_no, "clearance_date", clearance_date, update_modified=False)
	elif voucher_type == "Purchase Invoice":
		if frappe.db.get_value(voucher_type, voucher_no, "cash_bank_account") == bank_account:
			frappe.db.set_value(voucher_type, voucher_no, "clearance_date", clearance_date, update_modified=False)
	elif voucher_type == "Sales Invoice":
		for payment in frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": voucher_no, "parenttype": "Sales Invoice", "account": bank_account},
			pluck="name",
		):
			frappe.db.set_value(
				"Sales Invoice Payment", payment, "clearance_date", clearance_date, update_modified=False
			)
