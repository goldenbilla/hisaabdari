# Copyright (c) 2026, HisaabDari contributors
# License: GNU General Public License v3. See license.txt

"""Bank reconciliation.

A Bank Reconciliation covers one bank account for one statement period. The statement is held as
Bank Reconciliation Line records (uploaded from a file or typed in), and every agreed match between
statement lines and entries in the books is a Bank Match. An entry in the books is "cleared" when
a Bank Match holds it, or when it already carries a clearance date from before this feature.
"""

import hashlib
import json
import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max, Min, Sum
from frappe.utils import add_days, cint, date_diff, flt, getdate

CLEARANCE_DATE_DOCTYPES = ("Payment Entry", "Journal Entry")


class BankReconciliation(Document):
	def validate(self):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("Statement From cannot be after Statement To"))

		account = frappe.get_cached_value(
			"Account", self.bank_account, ["company", "is_group", "account_type"], as_dict=True
		)
		if not account or account.company != self.company:
			frappe.throw(_("Bank Account {0} does not belong to company {1}").format(self.bank_account, self.company))
		if account.is_group or account.account_type not in ("Bank", "Cash"):
			frappe.throw(_("{0} is not a bank or cash account").format(self.bank_account))

		if not self.is_new() and self.has_value_changed("bank_account"):
			if frappe.db.exists("Bank Reconciliation Line", {"bank_reconciliation": self.name}) or frappe.db.exists(
				"Bank Match", {"bank_reconciliation": self.name}
			):
				frappe.throw(_("The bank account cannot be changed once the reconciliation has lines or matches"))

	def on_trash(self):
		if frappe.db.exists("Bank Match", {"bank_reconciliation": self.name}):
			frappe.throw(_("Undo the matches of this reconciliation before deleting it"))
		frappe.db.delete("Bank Reconciliation Line", {"bank_reconciliation": self.name})

	def check_open(self):
		if self.status == "Closed":
			frappe.throw(_("This reconciliation is closed. Reopen it to make changes."))


# ---------------------------------------------------------------------------------------------
# Reading the books
# ---------------------------------------------------------------------------------------------


def get_book_entry_amounts(bank_account, vouchers=None, to_date=None):
	"""Net movement of each document on the bank account: {(voucher_type, voucher_no): amount}.

	Positive is money into the account. Amounts are in the account's own currency.
	"""
	gle = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gle)
		.select(
			gle.voucher_type,
			gle.voucher_no,
			(Sum(gle.debit_in_account_currency) - Sum(gle.credit_in_account_currency)).as_("amount"),
		)
		.where((gle.account == bank_account) & (gle.is_cancelled == 0))
		.groupby(gle.voucher_type, gle.voucher_no)
	)
	if to_date:
		query = query.where(gle.posting_date <= to_date)
	if vouchers is not None:
		if not vouchers:
			return {}
		query = query.where(gle.voucher_no.isin([v[1] for v in vouchers]))

	wanted = set(vouchers) if vouchers is not None else None
	return {
		(row.voucher_type, row.voucher_no): flt(row.amount)
		for row in query.run(as_dict=True)
		if flt(row.amount) and (wanted is None or (row.voucher_type, row.voucher_no) in wanted)
	}


def get_book_balance(bank_account, to_date):
	gle = frappe.qb.DocType("GL Entry")
	return flt(
		(
			frappe.qb.from_(gle)
			.select(Sum(gle.debit_in_account_currency) - Sum(gle.credit_in_account_currency))
			.where((gle.account == bank_account) & (gle.is_cancelled == 0) & (gle.posting_date <= to_date))
		).run()[0][0]
	)


def get_cleared_vouchers(bank_account, exclude_match=None):
	"""Documents already agreed with a statement: {(voucher_type, voucher_no): {clearance_date, bank_match}}."""
	match = frappe.qb.DocType("Bank Match")
	entry = frappe.qb.DocType("Bank Match Entry")
	query = (
		frappe.qb.from_(entry)
		.join(match)
		.on(match.name == entry.parent)
		.select(entry.voucher_type, entry.voucher_no, match.clearance_date, match.name.as_("bank_match"))
		.where(match.bank_account == bank_account)
	)
	if exclude_match:
		query = query.where(match.name != exclude_match)

	cleared = {
		(row.voucher_type, row.voucher_no): frappe._dict(clearance_date=row.clearance_date, bank_match=row.bank_match)
		for row in query.run(as_dict=True)
	}

	# Entries cleared before this feature existed (ERPNext's Bank Clearance) carry only a date.
	# A document matched here for any account is left out: its date field is written by that match,
	# and a transfer between two banks has one date field but is matched once for each account.
	matched_anywhere = set(
		frappe.get_all("Bank Match Entry", fields=["voucher_type", "voucher_no"], as_list=True, distinct=True)
	)
	for doctype in CLEARANCE_DATE_DOCTYPES:
		for row in frappe.get_all(
			doctype,
			filters={"docstatus": 1, "clearance_date": ["is", "set"]},
			or_filters=get_bank_account_filters(doctype, bank_account),
			fields=["name", "clearance_date"],
		):
			if (doctype, row.name) in matched_anywhere:
				continue
			cleared.setdefault(
				(doctype, row.name), frappe._dict(clearance_date=row.clearance_date, bank_match=None)
			)

	return cleared


def get_bank_account_filters(doctype, bank_account):
	if doctype == "Payment Entry":
		return {"paid_from": bank_account, "paid_to": bank_account}
	# Journal Entry: the account sits on the rows
	names = frappe.get_all(
		"Journal Entry Account", filters={"account": bank_account, "docstatus": 1}, pluck="parent", distinct=True
	)
	return {"name": ["in", names or [""]]}


def get_book_entries(bank_account, to_date, vouchers=None):
	"""Every document that moved the bank account up to `to_date`, with what a person needs to recognise it."""
	amounts = get_book_entry_amounts(bank_account, vouchers=vouchers, to_date=to_date)
	if not amounts:
		return []

	gle = frappe.qb.DocType("GL Entry")
	details = {
		(row.voucher_type, row.voucher_no): row
		for row in (
			frappe.qb.from_(gle)
			.select(
				gle.voucher_type,
				gle.voucher_no,
				Min(gle.posting_date).as_("posting_date"),
				Max(gle.against).as_("against"),
				Max(gle.remarks).as_("remarks"),
			)
			.where((gle.account == bank_account) & (gle.is_cancelled == 0))
			.where(gle.voucher_no.isin([v[1] for v in amounts]))
			.groupby(gle.voucher_type, gle.voucher_no)
		).run(as_dict=True)
	}

	extra = {}
	by_type = defaultdict(list)
	for voucher_type, voucher_no in amounts:
		by_type[voucher_type].append(voucher_no)

	if by_type.get("Payment Entry"):
		for row in frappe.get_all(
			"Payment Entry",
			filters={"name": ["in", by_type["Payment Entry"]]},
			fields=["name", "party", "party_name", "ledger_account", "reference_no", "payment_type", "paid_from", "paid_to"],
		):
			if row.payment_type == "Internal Transfer":
				other = row.paid_to if row.paid_from == bank_account else row.paid_from
				title = _("Transfer: {0}").format(other)
			else:
				title = row.party_name or row.party or row.ledger_account
			extra[("Payment Entry", row.name)] = (title, row.reference_no)

	if by_type.get("Journal Entry"):
		for row in frappe.get_all(
			"Journal Entry",
			filters={"name": ["in", by_type["Journal Entry"]]},
			fields=["name", "title", "pay_to_recd_from", "cheque_no", "user_remark"],
		):
			extra[("Journal Entry", row.name)] = (row.pay_to_recd_from or row.user_remark or row.title, row.cheque_no)

	for doctype, party_field in (("Sales Invoice", "customer_name"), ("Purchase Invoice", "supplier_name")):
		if by_type.get(doctype):
			for row in frappe.get_all(doctype, filters={"name": ["in", by_type[doctype]]}, fields=["name", party_field]):
				extra[(doctype, row.name)] = (row.get(party_field), None)

	entries = []
	for key, amount in amounts.items():
		detail = details.get(key) or frappe._dict()
		title, reference_no = extra.get(key) or (None, None)
		entries.append(
			frappe._dict(
				voucher_type=key[0],
				voucher_no=key[1],
				posting_date=detail.posting_date,
				amount=amount,
				title=title or detail.against or "",
				reference_no=reference_no or "",
				remarks=(detail.remarks or "")[:140],
			)
		)

	entries.sort(key=lambda d: (d.posting_date, d.voucher_no))
	return entries


def get_uncleared_entries(bank_account, to_date):
	"""Entries in the books up to `to_date` that no statement has confirmed yet."""
	cleared = get_cleared_vouchers(bank_account)
	return [d for d in get_book_entries(bank_account, to_date) if (d.voucher_type, d.voucher_no) not in cleared]


# ---------------------------------------------------------------------------------------------
# The screen's data
# ---------------------------------------------------------------------------------------------


def get_doc_for_change(name):
	doc = frappe.get_doc("Bank Reconciliation", name)
	doc.check_permission("write")
	doc.check_open()
	return doc


def line_amount(line):
	return flt(line.deposit) - flt(line.withdrawal)


@frappe.whitelist()
def get_reconciliation_data(name: str):
	doc = frappe.get_doc("Bank Reconciliation", name)
	doc.check_permission("read")

	lines = frappe.get_all(
		"Bank Reconciliation Line",
		filters={"bank_reconciliation": name},
		fields=["name", "date", "description", "reference_no", "deposit", "withdrawal", "balance", "status", "bank_match"],
		order_by="date asc, sequence asc, creation asc",
	)
	to_check = [d for d in lines if d.status == "To Check"]
	done_lines = defaultdict(list)
	for d in lines:
		if d.bank_match:
			done_lines[d.bank_match].append(d)

	# Entries posted shortly after the statement ends can still belong to a statement line.
	look_ahead = add_days(doc.to_date, 15)
	cleared = get_cleared_vouchers(doc.bank_account)
	all_entries = get_book_entries(doc.bank_account, look_ahead)
	uncleared = [d for d in all_entries if (d.voucher_type, d.voucher_no) not in cleared]
	entry_by_key = {(d.voucher_type, d.voucher_no): d for d in all_entries}

	rules = get_rules(doc.bank_account)
	suggest(to_check, uncleared, rules)

	matches = []
	for match in frappe.get_all(
		"Bank Match",
		filters={"bank_reconciliation": name},
		fields=["name", "match_type", "clearance_date"],
		order_by="clearance_date desc, creation desc",
	):
		entries = frappe.get_all(
			"Bank Match Entry",
			filters={"parent": match.name},
			fields=["voucher_type", "voucher_no", "amount", "created_by_match"],
			order_by="idx",
		)
		for entry in entries:
			detail = entry_by_key.get((entry.voucher_type, entry.voucher_no)) or frappe._dict()
			entry.title = detail.get("title") or ""
			entry.posting_date = detail.get("posting_date")
		match.entries = entries
		match.lines = done_lines.get(match.name, [])
		matches.append(match)

	not_on_statement = [d for d in uncleared if getdate(d.posting_date) <= getdate(doc.to_date)]

	return {
		"status": doc.status,
		"currency": frappe.get_cached_value("Account", doc.bank_account, "account_currency")
		or frappe.get_cached_value("Company", doc.company, "default_currency"),
		"to_check": to_check,
		"matches": matches,
		"not_on_statement": not_on_statement,
		"candidates": uncleared,
		"summary": get_summary(doc, lines=lines, uncleared=uncleared),
		"has_statement": bool(lines),
	}


def get_summary(doc, lines=None, uncleared=None):
	"""The reconciliation statement: from the balance in the books to the balance at the bank."""
	if lines is None:
		lines = frappe.get_all(
			"Bank Reconciliation Line",
			filters={"bank_reconciliation": doc.name},
			fields=["deposit", "withdrawal", "status"],
		)
	if uncleared is None:
		uncleared = get_uncleared_entries(doc.bank_account, doc.to_date)

	to_date = getdate(doc.to_date)
	book_balance = get_book_balance(doc.bank_account, doc.to_date)

	# Entries cleared by a statement dated after this one were still outstanding at `to_date`.
	outstanding = [d for d in uncleared if getdate(d.posting_date) <= to_date]
	for key, info in get_cleared_vouchers(doc.bank_account).items():
		if info.clearance_date and getdate(info.clearance_date) > to_date:
			entries = get_book_entries(doc.bank_account, doc.to_date, vouchers=[key])
			outstanding.extend(entries)

	payments_not_presented = sum(-d.amount for d in outstanding if d.amount < 0)
	receipts_not_credited = sum(d.amount for d in outstanding if d.amount > 0)
	expected_bank_balance = book_balance + payments_not_presented - receipts_not_credited

	unchecked = [d for d in lines if d.status == "To Check"]
	unbooked_in = sum(flt(d.deposit) for d in unchecked)
	unbooked_out = sum(flt(d.withdrawal) for d in unchecked)

	statement_balance = flt(doc.statement_closing_balance)
	difference = statement_balance - (expected_bank_balance + unbooked_in - unbooked_out)

	return {
		"book_balance": flt(book_balance, 2),
		"payments_not_presented": flt(payments_not_presented, 2),
		"receipts_not_credited": flt(receipts_not_credited, 2),
		"expected_bank_balance": flt(expected_bank_balance, 2),
		"unbooked_in": flt(unbooked_in, 2),
		"unbooked_out": flt(unbooked_out, 2),
		"statement_closing_balance": flt(statement_balance, 2),
		"difference": flt(difference, 2),
		"lines_total": len(lines),
		"lines_to_check": len(unchecked),
		"outstanding_count": len(outstanding),
	}


# ---------------------------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------------------------


def normalise(text):
	"""A description with the parts that change from line to line removed, to spot repeating lines."""
	text = re.sub(r"[0-9]+", " ", (text or "").upper())
	text = re.sub(r"[^A-Z ]+", " ", text)
	return " ".join(text.split()[:4])


def get_rules(bank_account):
	return frappe.get_all(
		"Bank Statement Rule",
		filters={"disabled": 0, "bank_account": ["in", ["", None, bank_account]]},
		fields=["name", "description_contains", "applies_to", "party_or_ledger", "ledger_account", "party"],
		order_by="creation asc",
	)


def find_rule(line, rules):
	description = (line.description or "").upper()
	for rule in rules:
		if rule.applies_to == "Money Out" and not flt(line.withdrawal):
			continue
		if rule.applies_to == "Money In" and not flt(line.deposit):
			continue
		if (rule.description_contains or "").strip().upper() in description:
			return rule
	return None


def suggest(lines, uncleared, rules):
	"""Attach a `suggestion` to each statement line that is still to check.

	One of: {"type": "match", "vouchers": [...]} for a single entry of the same amount;
	{"type": "group", "group": id, "vouchers": [...]} when several similar lines add up to one entry;
	{"type": "rule", ...} when a rule says how to enter the line; or nothing.
	"""
	by_amount = defaultdict(list)
	for entry in uncleared:
		by_amount[flt(entry.amount, 2)].append(entry)

	used = set()
	unmatched = []
	for line in lines:
		amount = flt(line_amount(line), 2)
		candidates = [d for d in by_amount.get(amount, []) if (d.voucher_type, d.voucher_no) not in used]
		if not candidates:
			unmatched.append(line)
			continue

		reference = (line.reference_no or "").strip().lstrip("0")
		description = (line.description or "").upper()

		def score(entry):
			entry_reference = (entry.reference_no or "").strip().lstrip("0")
			reference_hit = bool(
				entry_reference
				and (entry_reference == reference or (len(entry_reference) >= 4 and entry_reference in description))
			)
			return (0 if reference_hit else 1, abs(date_diff(line.date, entry.posting_date)))

		best = min(candidates, key=score)
		used.add((best.voucher_type, best.voucher_no))
		line.suggestion = {
			"type": "match",
			"vouchers": [best],
			"others": len(candidates) - 1,
			"days_apart": abs(date_diff(line.date, best.posting_date)),
		}

	# Several similar lines (bank charges taken one by one) against one entry of their total.
	groups = defaultdict(list)
	for line in unmatched:
		groups[(normalise(line.description), line_amount(line) > 0)].append(line)

	for (key, _is_deposit), group in groups.items():
		if len(group) < 2 or not key:
			continue
		total = flt(sum(line_amount(d) for d in group), 2)
		candidates = [d for d in by_amount.get(total, []) if (d.voucher_type, d.voucher_no) not in used]
		if not candidates:
			continue
		best = candidates[0]
		used.add((best.voucher_type, best.voucher_no))
		for line in group:
			line.suggestion = {"type": "group", "group": group[0].name, "size": len(group), "total": total, "vouchers": [best]}

	for line in unmatched:
		if line.get("suggestion"):
			continue
		rule = find_rule(line, rules)
		if rule:
			line.suggestion = {
				"type": "rule",
				"rule": rule.name,
				"party_or_ledger": rule.party_or_ledger,
				"ledger_account": rule.ledger_account,
				"party": rule.party,
			}


# ---------------------------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------------------------


def parse_list(value):
	value = frappe.parse_json(value) if isinstance(value, str) else value
	return list(value or [])


def get_lines_to_match(doc, lines):
	names = parse_list(lines)
	rows = frappe.get_all(
		"Bank Reconciliation Line",
		filters={"name": ["in", names or [""]], "bank_reconciliation": doc.name},
		fields=["name", "date", "description", "reference_no", "deposit", "withdrawal", "status"],
	)
	if len(rows) != len(set(names)):
		frappe.throw(_("Some statement lines were not found in this reconciliation. Refresh and try again."))
	for row in rows:
		if row.status != "To Check":
			frappe.throw(_("The statement line of {0} is already matched").format(frappe.format_value(row.date, {"fieldtype": "Date"})))
	return rows


def make_match(doc, lines, vouchers, match_type="Match", clearance_date=None, created=None):
	match = frappe.new_doc("Bank Match")
	match.bank_reconciliation = doc.name
	match.bank_account = doc.bank_account
	match.company = doc.company
	match.match_type = match_type
	match.clearance_date = clearance_date or max(getdate(d.date) for d in lines)
	for voucher in vouchers:
		key = (voucher["voucher_type"], voucher["voucher_no"])
		match.append(
			"entries",
			{"voucher_type": key[0], "voucher_no": key[1], "created_by_match": 1 if created and key in created else 0},
		)
	match.validate_entries()
	match.validate_balance(lines)
	match.flags.ignore_permissions = True
	match.insert()

	for line in lines:
		frappe.db.set_value("Bank Reconciliation Line", line.name, {"bank_match": match.name, "status": "Done"})
	match.set_clearance_dates(match.clearance_date)
	return match


@frappe.whitelist(methods=["POST"])
def create_match(name: str, lines: str | list, vouchers: str | list):
	"""Agree one or more statement lines with one or more entries in the books. The totals must be equal."""
	doc = get_doc_for_change(name)
	rows = get_lines_to_match(doc, lines)
	vouchers = parse_list(vouchers)
	if not rows or not vouchers:
		frappe.throw(_("Select at least one statement line and one entry"))
	return make_match(doc, rows, vouchers).name


@frappe.whitelist(methods=["POST"])
def create_entry_and_match(name: str, lines: str | list, entry: str | dict, vouchers: str | list | None = None):
	"""Enter what the statement shows as a new Payment Entry and match it.

	With `vouchers`, the new entry covers only the difference between the lines and those entries.
	"""
	doc = get_doc_for_change(name)
	rows = get_lines_to_match(doc, lines)
	if not rows:
		frappe.throw(_("Select at least one statement line"))
	entry = frappe._dict(frappe.parse_json(entry) if isinstance(entry, str) else entry)
	vouchers = parse_list(vouchers)

	amount = sum(line_amount(d) for d in rows)
	if vouchers:
		keys = [(v["voucher_type"], v["voucher_no"]) for v in vouchers]
		amount -= sum(get_book_entry_amounts(doc.bank_account, keys).values())
	amount = flt(amount, 2)
	if not amount:
		frappe.throw(_("There is nothing left to enter: the lines and the selected entries already agree"))

	payment = make_payment_entry(doc, rows, amount, entry)
	created = {("Payment Entry", payment.name)}
	vouchers.append({"voucher_type": "Payment Entry", "voucher_no": payment.name})
	match = make_match(doc, rows, vouchers, match_type="New Entry", created=created)

	if cint(entry.get("save_rule")) and entry.get("rule_text"):
		save_rule(doc, rows[0], entry)

	return {"bank_match": match.name, "payment_entry": payment.name}


def make_payment_entry(doc, rows, amount, entry):
	"""A submitted Payment Entry of `amount` on the bank account (positive is money in)."""
	last = max(rows, key=lambda d: getdate(d.date))
	payment = frappe.new_doc("Payment Entry")
	payment.company = doc.company
	payment.posting_date = last.date
	payment.payment_type = "Receive" if amount > 0 else "Pay"
	bank_field = "paid_to" if amount > 0 else "paid_from"
	payment.set(bank_field, doc.bank_account)

	if entry.get("party_or_ledger") in ("Customer", "Supplier"):
		from hisaabdari.accounts.party import get_party_account

		if not entry.get("party"):
			frappe.throw(_("Select the {0}").format(_(entry.party_or_ledger)))
		payment.party_or_ledger = entry.party_or_ledger
		payment.party_type = entry.party_or_ledger
		payment.party = entry.party
		payment.set(
			"paid_from" if amount > 0 else "paid_to",
			get_party_account(entry.party_or_ledger, entry.party, doc.company),
		)
	else:
		if not entry.get("ledger_account"):
			frappe.throw(_("Select the account this was for"))
		payment.party_or_ledger = "Ledger Account"
		payment.ledger_account = entry.ledger_account

	payment.paid_amount = abs(amount)
	payment.received_amount = abs(amount)
	payment.reference_no = (last.reference_no or "").strip() or _("Bank statement")
	payment.reference_date = last.date
	if entry.get("remarks"):
		payment.custom_remarks = 1
		payment.remarks = entry.remarks
	elif last.description:
		payment.custom_remarks = 1
		payment.remarks = last.description if len(rows) == 1 else _("{0} ({1} statement lines)").format(
			last.description, len(rows)
		)
	payment.insert()
	payment.submit()
	return payment


def save_rule(doc, line, entry):
	text = (entry.rule_text or "").strip()
	if not text or frappe.db.exists("Bank Statement Rule", {"description_contains": text}):
		return
	title = text[:120]
	if frappe.db.exists("Bank Statement Rule", title):
		return
	rule = frappe.new_doc("Bank Statement Rule")
	rule.title = title
	rule.description_contains = text
	rule.applies_to = "Money In" if flt(line.deposit) else "Money Out"
	rule.party_or_ledger = entry.get("party_or_ledger") or "Ledger Account"
	rule.ledger_account = entry.get("ledger_account")
	rule.party = entry.get("party")
	rule.insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def create_transfer_and_match(name: str, lines: str | list, other_account: str):
	"""The statement lines are money moved to or from another of the company's own accounts."""
	doc = get_doc_for_change(name)
	rows = get_lines_to_match(doc, lines)
	amount = flt(sum(line_amount(d) for d in rows), 2)
	if not rows or not amount:
		frappe.throw(_("Select at least one statement line"))
	if other_account == doc.bank_account:
		frappe.throw(_("Choose a different account for the other side of the transfer"))

	last = max(rows, key=lambda d: getdate(d.date))
	payment = frappe.new_doc("Payment Entry")
	payment.company = doc.company
	payment.posting_date = last.date
	payment.payment_type = "Internal Transfer"
	payment.paid_from = other_account if amount > 0 else doc.bank_account
	payment.paid_to = doc.bank_account if amount > 0 else other_account
	payment.paid_amount = abs(amount)
	payment.received_amount = abs(amount)
	payment.reference_no = (last.reference_no or "").strip() or _("Bank statement")
	payment.reference_date = last.date
	payment.insert()
	payment.submit()

	match = make_match(
		doc,
		rows,
		[{"voucher_type": "Payment Entry", "voucher_no": payment.name}],
		match_type="Transfer",
		created={("Payment Entry", payment.name)},
	)
	return {"bank_match": match.name, "payment_entry": payment.name}


@frappe.whitelist(methods=["POST"])
def mark_cleared(name: str, vouchers: str | list, clearance_date: str | None = None):
	"""No statement file: tick entries that appear on the printed statement, with the date the bank shows."""
	doc = get_doc_for_change(name)
	vouchers = parse_list(vouchers)
	if not vouchers:
		frappe.throw(_("Select at least one entry"))

	dates = {
		(d.voucher_type, d.voucher_no): d.posting_date
		for d in get_book_entries(doc.bank_account, None, vouchers=[(v["voucher_type"], v["voucher_no"]) for v in vouchers])
	}
	made = []
	for voucher in vouchers:
		key = (voucher["voucher_type"], voucher["voucher_no"])
		date = clearance_date or voucher.get("clearance_date") or dates.get(key)
		made.append(make_match(doc, [], [voucher], match_type="Without Statement", clearance_date=date).name)
	return made


@frappe.whitelist(methods=["POST"])
def mark_all_cleared(name: str, up_to_date: str):
	"""Starting out: treat every entry up to a date as already agreed with the bank, each on its own date."""
	doc = get_doc_for_change(name)
	entries = get_uncleared_entries(doc.bank_account, up_to_date)
	for entry in entries:
		make_match(
			doc,
			[],
			[{"voucher_type": entry.voucher_type, "voucher_no": entry.voucher_no}],
			match_type="Without Statement",
			clearance_date=entry.posting_date,
		)
	return len(entries)


@frappe.whitelist(methods=["POST"])
def undo_match(name: str, bank_match: str, cancel_created_entries: int | str = 0):
	doc = get_doc_for_change(name)
	match = frappe.get_doc("Bank Match", bank_match)
	if match.bank_reconciliation != doc.name:
		frappe.throw(_("This match belongs to another reconciliation"))

	created = [(d.voucher_type, d.voucher_no) for d in match.entries if d.created_by_match]
	match.flags.ignore_permissions = True
	match.delete()

	cancelled = []
	if cint(cancel_created_entries):
		for voucher_type, voucher_no in created:
			voucher = frappe.get_doc(voucher_type, voucher_no)
			if voucher.docstatus == 1:
				voucher.cancel()
				cancelled.append(voucher_no)
	return {"cancelled": cancelled, "created": [v[1] for v in created]}


# ---------------------------------------------------------------------------------------------
# Statement lines
# ---------------------------------------------------------------------------------------------


def make_import_key(bank_account, line, occurrence):
	text = "|".join(
		[
			bank_account,
			str(line.get("date")),
			f"{flt(line.get('withdrawal')):.2f}",
			f"{flt(line.get('deposit')):.2f}",
			" ".join((line.get("description") or "").split()).upper(),
			(line.get("reference_no") or "").strip(),
			str(occurrence),
		]
	)
	return hashlib.sha1(text.encode()).hexdigest()


def add_lines(doc, lines):
	"""Insert statement lines, leaving out any this bank account already has. Returns (added, skipped)."""
	seen = defaultdict(int)
	prepared = []
	for line in lines:
		base = make_import_key(doc.bank_account, line, 0)
		seen[base] += 1
		prepared.append((line, make_import_key(doc.bank_account, line, seen[base])))

	existing = set(
		frappe.get_all(
			"Bank Reconciliation Line",
			filters={"bank_account": doc.bank_account, "import_key": ["in", [key for _line, key in prepared] or [""]]},
			pluck="import_key",
		)
	)
	line = frappe.qb.DocType("Bank Reconciliation Line")
	sequence = cint(
		(frappe.qb.from_(line).select(Max(line.sequence)).where(line.bank_reconciliation == doc.name)).run()[0][0]
	)

	added = skipped = 0
	for line, key in prepared:
		if key in existing:
			skipped += 1
			continue
		sequence += 1
		row = frappe.new_doc("Bank Reconciliation Line")
		row.update(
			{
				"bank_reconciliation": doc.name,
				"bank_account": doc.bank_account,
				"company": doc.company,
				"date": line.get("date"),
				"description": (line.get("description") or "").strip(),
				"reference_no": (line.get("reference_no") or "").strip(),
				"deposit": flt(line.get("deposit")),
				"withdrawal": flt(line.get("withdrawal")),
				"balance": line.get("balance"),
				"sequence": sequence,
				"import_key": key,
			}
		)
		row.insert(ignore_permissions=True)
		added += 1
	return added, skipped


@frappe.whitelist(methods=["POST"])
def add_statement_line(
	name: str,
	date: str,
	description: str | None = None,
	deposit: float | str = 0,
	withdrawal: float | str = 0,
	reference_no: str | None = None,
):
	doc = get_doc_for_change(name)
	deposit, withdrawal = flt(deposit), flt(withdrawal)
	if bool(deposit) == bool(withdrawal):
		frappe.throw(_("Enter either money in or money out"))
	if deposit < 0 or withdrawal < 0:
		frappe.throw(_("Amounts cannot be negative"))
	added, skipped = add_lines(
		doc,
		[{"date": date, "description": description, "deposit": deposit, "withdrawal": withdrawal, "reference_no": reference_no}],
	)
	if skipped:
		frappe.throw(_("The same line is already on a statement of this bank account"))
	return added


@frappe.whitelist(methods=["POST"])
def delete_statement_lines(name: str, lines: str | list):
	doc = get_doc_for_change(name)
	rows = get_lines_to_match(doc, lines)
	for row in rows:
		frappe.delete_doc("Bank Reconciliation Line", row.name, ignore_permissions=True)
	return len(rows)


@frappe.whitelist(methods=["POST"])
def read_statement_file(name: str, file_url: str, layout: str | dict | None = None):
	"""Read an uploaded statement and show what was found, without saving any line."""
	doc = get_doc_for_change(name)
	result = read_file(doc, file_url, layout)
	result["account_check"] = check_account(doc, result.get("header") or {})
	result["line_count"] = len(result["lines"])
	result["lines"] = result["lines"][:200]
	return result


@frappe.whitelist(methods=["POST"])
def import_statement_file(name: str, file_url: str, layout: str | dict | None = None, set_closing_balance: int | str = 1):
	doc = get_doc_for_change(name)
	result = read_file(doc, file_url, layout)
	added, skipped = add_lines(doc, result["lines"])

	save_layout(doc.bank_account, result)
	closing = (result.get("header") or {}).get("closing_balance")
	if cint(set_closing_balance) and closing is not None and not flt(doc.statement_closing_balance):
		doc.db_set("statement_closing_balance", flt(closing))

	return {"added": added, "skipped": skipped, "warnings": result.get("warnings") or []}


def read_file(doc, file_url, layout=None):
	from hisaabdari.accounts.bank_statement_reader import StatementReadError, read_statement

	file = frappe.get_doc("File", {"file_url": file_url})
	file.check_permission("read")
	layout = frappe.parse_json(layout) if isinstance(layout, str) and layout else layout
	if not layout:
		saved = frappe.db.get_value("Bank Statement Layout", doc.bank_account, ["layout", "file_type"], as_dict=True)
		extension = (file.file_name or "").rsplit(".", 1)[-1].lower()
		if saved and saved.layout and saved.file_type == extension:
			layout = json.loads(saved.layout)

	password = None
	bank_account = frappe.db.get_value("Bank Account", {"account": doc.bank_account, "is_company_account": 1}, "name")
	if bank_account:
		password = frappe.get_doc("Bank Account", bank_account).get_password("statement_password", raise_exception=False)

	try:
		return read_statement(file.file_name, file.get_content(), layout=layout, password=password)
	except StatementReadError as e:
		frappe.throw(str(e), title=_("Could not read the statement"))


def check_account(doc, header):
	"""Compare the account printed on the statement with the bank account record, when both are known."""
	record = frappe.db.get_value(
		"Bank Account",
		{"account": doc.bank_account, "is_company_account": 1},
		["bank_account_no", "iban"],
		as_dict=True,
	)

	def digits(value):
		return re.sub(r"[^A-Z0-9]", "", (value or "").upper())

	found = [digits(header.get("iban")), digits(header.get("account_number"))]
	found = [d for d in found if d]
	if not found:
		return {"status": "unknown", "message": _("No account number was found on the statement.")}
	if not record or not (record.iban or record.bank_account_no):
		return {
			"status": "unknown",
			"message": _("The statement is for account {0}. Add the account number to the Bank Account record to have it checked.").format(
				header.get("iban") or header.get("account_number")
			),
		}

	known = [digits(record.iban), digits(record.bank_account_no)]
	known = [d for d in known if d]
	if any(a == b or a.endswith(b) or b.endswith(a) for a in found for b in known):
		return {"status": "ok", "message": _("The account number on the statement matches this bank account.")}
	return {
		"status": "mismatch",
		"message": _("The statement is for account {0}, which is not the account number saved for {1}.").format(
			header.get("iban") or header.get("account_number"), doc.bank_account
		),
	}


def save_layout(bank_account, result):
	if not result.get("layout"):
		return
	values = {"layout": json.dumps(result["layout"], indent=1), "file_type": result.get("file_type")}
	if frappe.db.exists("Bank Statement Layout", bank_account):
		frappe.db.set_value("Bank Statement Layout", bank_account, values)
	else:
		frappe.get_doc({"doctype": "Bank Statement Layout", "bank_account": bank_account, **values}).insert(
			ignore_permissions=True
		)


# ---------------------------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def close_reconciliation(name: str):
	doc = get_doc_for_change(name)
	summary = get_summary(doc)
	if summary["lines_to_check"]:
		frappe.throw(_("{0} statement lines are still to check").format(summary["lines_to_check"]))
	if summary["difference"]:
		frappe.throw(
			_("There is still a difference of {0} between the statement and the books").format(
				frappe.format_value(summary["difference"], {"fieldtype": "Currency"})
			)
		)
	doc.db_set(
		{
			"status": "Closed",
			"book_balance": summary["book_balance"],
			"payments_not_presented": summary["payments_not_presented"],
			"receipts_not_credited": summary["receipts_not_credited"],
			"difference": summary["difference"],
		}
	)
	return summary


@frappe.whitelist(methods=["POST"])
def reopen_reconciliation(name: str):
	doc = frappe.get_doc("Bank Reconciliation", name)
	doc.check_permission("write")
	doc.db_set("status", "Open")
