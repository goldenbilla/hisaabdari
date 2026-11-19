# Copyright (c) 2026, HisaabDari contributors
# See license.txt

"""Tests for the bank statement reader. No site data is needed.

The fixture files are in test_files/bank_statements/ and are written by make_fixtures.py there;
every name and number in them is invented.
"""

import json
import os
import unittest
from unittest.mock import patch

from hisaabdari.accounts import bank_statement_reader as reader
from hisaabdari.accounts.bank_statement_reader import StatementReadError, parse_amount, read_statement

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_files", "bank_statements")
PDF_PASSWORD = "sitara-1947"  # set by make_fixtures.py on encrypted.pdf


def fixture(name: str) -> bytes:
	with open(os.path.join(FIXTURES, name), "rb") as f:
		return f.read()


def read(name: str, **kwargs) -> dict:
	return read_statement(name, fixture(name), **kwargs)


def money(result: dict):
	"""(date, withdrawal, deposit, balance) per line: the part that must never be wrong."""
	return [(line["date"], line["withdrawal"], line["deposit"], line["balance"]) for line in result["lines"]]


class StatementCase(unittest.TestCase):
	maxDiff = None

	def assert_contract(self, result: dict):
		self.assertEqual(
			set(result),
			{"file_type", "header", "columns", "layout", "preview_rows", "lines", "warnings", "skipped_rows"},
		)
		self.assertEqual(
			set(result["header"]),
			{
				"bank_name",
				"account_title",
				"account_number",
				"iban",
				"period_from",
				"period_to",
				"opening_balance",
				"closing_balance",
				"currency",
			},
		)
		for key in (
			"header_row",
			"date",
			"description",
			"reference",
			"withdrawal",
			"deposit",
			"amount",
			"balance",
			"date_format",
			"day_first",
		):
			self.assertIn(key, result["layout"])
		self.assertIsInstance(result["layout"]["description"], list)
		self.assertIsInstance(result["layout"]["day_first"], bool)
		self.assertLessEqual(len(result["preview_rows"]), 15)
		for row in result["preview_rows"]:
			self.assertTrue(all(isinstance(c, str) for c in row))
		for line in result["lines"]:
			self.assertEqual(
				set(line), {"date", "description", "reference_no", "withdrawal", "deposit", "balance"}
			)
			self.assertRegex(line["date"], r"^\d{4}-\d{2}-\d{2}$")
			self.assertGreaterEqual(line["withdrawal"], 0)
			self.assertGreaterEqual(line["deposit"], 0)
			self.assertEqual((line["withdrawal"] > 0) + (line["deposit"] > 0), 1, line)
		json.dumps(result)  # must be JSON-serialisable


class TestCSV(StatementCase):
	def test_separate_debit_and_credit_columns(self):
		result = read("separate_columns.csv")
		self.assert_contract(result)
		self.assertEqual(result["file_type"], "csv")
		self.assertEqual(
			result["header"],
			{
				"bank_name": "Sample Bank Limited",
				"account_title": "Sitara Hardware Store",
				"account_number": "0123-4567890-01",
				"iban": "PK36SMPL0000111122223333",
				"period_from": "2026-10-01",
				"period_to": "2026-10-31",
				"opening_balance": 100000.0,
				"closing_balance": 114595.25,
				"currency": "PKR",
			},
		)
		self.assertEqual(
			result["columns"],
			["Date", "Value Date", "Particulars", "Cheque No", "Debit", "Credit", "Balance"],
		)
		layout = result["layout"]
		self.assertEqual(layout["header_row"], 6)
		self.assertEqual(layout["date"], 0)
		self.assertEqual(layout["description"], [2])
		self.assertEqual(layout["reference"], 3)
		self.assertEqual((layout["withdrawal"], layout["deposit"], layout["amount"]), (4, 5, None))
		self.assertEqual(layout["balance"], 6)
		self.assertTrue(layout["day_first"])
		self.assertEqual(
			result["lines"],
			[
				{
					"date": "2026-10-01",
					"description": "Cheque paid Karim Packaging",
					"reference_no": "00451201",
					"withdrawal": 1250.0,
					"deposit": 0.0,
					"balance": 98750.0,
				},
				{
					"date": "2026-10-05",
					# the row below it has no date: it continues the description
					"description": "IBFT from Noor Textiles, Faisalabad Invoice 1045 settlement",
					"reference_no": "",
					"withdrawal": 0.0,
					"deposit": 25000.0,
					"balance": 123750.0,
				},
				{
					"date": "2026-10-12",
					"description": "ATM withdrawal",
					"reference_no": "",
					"withdrawal": 10000.0,
					"deposit": 0.0,
					"balance": 113750.0,
				},
				{
					"date": "2026-10-31",
					"description": "Profit credited",
					"reference_no": "",
					"withdrawal": 0.0,
					"deposit": 845.25,
					"balance": 114595.25,
				},
			],
		)
		# opening balance, closing balance and total rows are not transactions and not "skipped"
		self.assertEqual(result["skipped_rows"], 0)
		self.assertEqual(result["warnings"], [])
		self.assertEqual(len(result["preview_rows"]), 15)
		self.assertEqual(result["preview_rows"][0][0], "Sample Bank Limited")
		self.assertEqual(result["preview_rows"][8][4], "1,250.00")

	def test_single_signed_amount_column(self):
		result = read("signed_amount.csv")
		self.assert_contract(result)
		layout = result["layout"]
		self.assertEqual((layout["withdrawal"], layout["deposit"], layout["amount"]), (None, None, 2))
		self.assertEqual(layout["balance"], 3)
		# 17/10, 23/10 and 31/10 settle that the day comes first
		self.assertTrue(layout["day_first"])
		self.assertEqual(layout["date_format"], "%d/%m/%Y")
		self.assertEqual(
			money(result),
			[
				("2026-10-05", 1250.0, 0.0, 48750.0),  # -1,250.00
				("2026-10-09", 0.0, 15000.0, 63750.0),  # Rs. 15,000.00
				("2026-10-17", 500.0, 0.0, 63250.0),  # (500.00)
				("2026-10-23", 2000.0, 0.0, 61250.0),  # 2,000.00-
				("2026-10-31", 0.0, 120.5, 61370.5),  # PKR 120.50
			],
		)
		self.assertEqual(result["lines"][0]["description"], "Card payment Metro Store")
		self.assertEqual(result["warnings"], [])

	def test_dr_cr_marker_column(self):
		result = read("drcr_marker.csv")  # semicolon separated, dates like 05-Oct-26
		self.assert_contract(result)
		layout = result["layout"]
		self.assertEqual(layout["header_row"], 1)
		self.assertEqual(layout["amount"], 3)
		self.assertEqual(layout["dr_cr"], 4)
		self.assertEqual(layout["reference"], 2)
		self.assertEqual(result["header"]["bank_name"], "Crescent Demo Bank")
		self.assertEqual(
			money(result),
			[
				("2026-10-05", 7500.0, 0.0, 42500.0),
				("2026-10-06", 0.0, 12000.0, 54500.0),
				("2026-10-20", 35.0, 0.0, 54465.0),
			],
		)
		self.assertEqual([line["reference_no"] for line in result["lines"]], ["TR-5501", "TR-5502", ""])
		self.assertEqual(result["lines"][1]["description"], "Customer receipt Sana Boutique")

	def test_month_first_dates_decided_from_data(self):
		result = read("month_first.csv")  # 10/13/2026 can only be month/day
		self.assertFalse(result["layout"]["day_first"])
		self.assertEqual(result["layout"]["date_format"], "%m/%d/%Y")
		self.assertEqual(
			money(result),
			[
				("2026-10-05", 25.0, 0.0, None),
				("2026-10-13", 0.0, 4300.0, None),
				("2026-11-02", 60.0, 0.0, None),
			],
		)
		# "Money Out" / "Money In" headings
		self.assertEqual((result["layout"]["withdrawal"], result["layout"]["deposit"]), (2, 3))

	def test_ambiguous_dates_default_to_day_first(self):
		content = b"Date,Description,Debit,Credit\n03/04/2026,Fee,10.00,\n05/06/2026,Sale,,90.00\n"
		result = read_statement("s.csv", content)
		self.assertTrue(result["layout"]["day_first"])
		self.assertEqual([line["date"] for line in result["lines"]], ["2026-04-03", "2026-06-05"])

	def test_day_first_decided_by_a_day_above_twelve(self):
		content = b"Date,Description,Debit,Credit\n03/04/26,Fee,10.00,\n25/04/26,Sale,,90.00\n"
		result = read_statement("s.csv", content)
		self.assertTrue(result["layout"]["day_first"])
		self.assertEqual(result["layout"]["date_format"], "%d/%m/%y")
		self.assertEqual([line["date"] for line in result["lines"]], ["2026-04-03", "2026-04-25"])

	def test_many_date_formats(self):
		rows = [
			("31/10/2026", "2026-10-31"),
			("31-Oct-26", "2026-10-31"),
			("2026-10-31", "2026-10-31"),
			("31 OCT 2026", "2026-10-31"),
			("31-OCT-2026", "2026-10-31"),
			("31.10.2026", "2026-10-31"),
			("31/10/2026 14:22:05", "2026-10-31"),
			("2026-10-31T09:15:00", "2026-10-31"),
			("October 31 2026", "2026-10-31"),
			("1 November 2026", "2026-11-01"),
			("01Nov2026", "2026-11-01"),
			("46327", "2026-11-01"),  # Excel serial number left in a CSV
		]
		content = "Date,Description,Amount\n" + "".join(f"{raw},Row,-5.00\n" for raw, _ in rows)
		result = read_statement("dates.csv", content.encode())
		self.assertEqual([line["date"] for line in result["lines"]], [iso for _, iso in rows])
		self.assertEqual(result["skipped_rows"], 0)

	def test_passed_layout_overrides_detection(self):
		# headings the reader does not know ("Tarikh, Tafseel, Jama, Nikasi"): money in comes first
		guessed = read("no_headings.csv")
		self.assertIsNone(guessed["layout"]["header_row"])
		self.assertIn("No column headings were found", guessed["warnings"][0])
		self.assertEqual(guessed["layout"]["date"], 0)
		self.assertEqual(guessed["layout"]["description"], [1])
		# the guess puts the first amount column as money out, which is wrong for this file
		self.assertEqual(guessed["lines"][0]["withdrawal"], 5000.0)

		layout = {
			"header_row": 0,
			"date": 0,
			"description": [1],
			"reference": None,
			"withdrawal": 3,
			"deposit": 2,
			"amount": None,
			"balance": None,
			"date_format": None,
			"day_first": True,
		}
		result = read("no_headings.csv", layout=layout)
		self.assert_contract(result)
		self.assertEqual(result["columns"], ["Tarikh", "Tafseel", "Jama", "Nikasi"])
		self.assertEqual(result["layout"]["header_row"], 0)
		self.assertEqual((result["layout"]["withdrawal"], result["layout"]["deposit"]), (3, 2))
		self.assertEqual(
			[(line["date"], line["description"], line["withdrawal"], line["deposit"]) for line in result["lines"]],
			[
				("2026-10-03", "Cash jama", 0.0, 5000.0),
				("2026-10-04", "Bijli bill", 1800.0, 0.0),
				("2026-10-06", "Dukaan kiraya", 12000.0, 0.0),
			],
		)
		self.assertEqual(result["skipped_rows"], 0)

		# the user can also turn the dates round
		layout["day_first"] = False
		swapped = read("no_headings.csv", layout=layout)
		self.assertEqual([line["date"] for line in swapped["lines"]], ["2026-03-10", "2026-04-10", "2026-06-10"])
		self.assertFalse(swapped["layout"]["day_first"])
		self.assertEqual(swapped["layout"]["date_format"], "%m/%d/%Y")

	def test_passed_layout_overrides_recognised_headings(self):
		# the user says the value date (column 1) is the date to use and the cheque number is not wanted
		detected = read("separate_columns.csv")["layout"]
		layout = dict(detected, date=1, reference=None)
		result = read("separate_columns.csv", layout=layout)
		self.assertEqual([line["date"] for line in result["lines"]][2], "2026-10-13")
		self.assertEqual(result["lines"][0]["reference_no"], "")
		self.assertEqual(result["layout"]["date"], 1)

	def test_detected_layout_can_be_saved_and_passed_back(self):
		for name in ("separate_columns.csv", "signed_amount.csv", "drcr_marker.csv", "month_first.csv"):
			first = read(name)
			again = read(name, layout=json.loads(json.dumps(first["layout"])))
			self.assertEqual(again["lines"], first["lines"], name)
			self.assertEqual(again["layout"], first["layout"], name)
			self.assertEqual(again["header"], first["header"], name)

	def test_unsigned_amounts_newest_first_decided_by_balance(self):
		content = (
			b"Date,Details,Amount,Balance\n"
			b"20/10/2026,Rent,\"30,000.00\",\"45,000.00\"\n"
			b"15/10/2026,Sale,\"25,000.00\",\"75,000.00\"\n"
			b"14/10/2026,Fuel,\"5,000.00\",\"50,000.00\"\n"
			b"13/10/2026,Opening Balance,,\"55,000.00\"\n"
		)
		result = read_statement("s.csv", content)
		self.assertEqual(
			money(result),
			[
				("2026-10-20", 30000.0, 0.0, 45000.0),
				("2026-10-15", 0.0, 25000.0, 75000.0),
				("2026-10-14", 5000.0, 0.0, 50000.0),
			],
		)
		self.assertEqual(result["header"]["opening_balance"], 55000.0)
		self.assertEqual(result["warnings"], [])

	def test_unsigned_amounts_without_balance_warn(self):
		result = read_statement("s.csv", b"Date,Details,Amount\n01/10/2026,A,100.00\n02/10/2026,B,50.00\n")
		self.assertEqual([(line["withdrawal"], line["deposit"]) for line in result["lines"]], [(0.0, 100.0), (0.0, 50.0)])
		self.assertTrue(any("no running balance" in w for w in result["warnings"]))

	def test_balance_that_does_not_add_up_is_reported(self):
		content = (
			b"Date,Description,Debit,Credit,Balance\n"
			b"01/10/2026,A,100.00,,900.00\n"
			b"02/10/2026,B,,50.00,950.00\n"
			b"04/10/2026,D,10.00,,640.00\n"  # a row is missing before this one
		)
		result = read_statement("s.csv", content)
		self.assertEqual(len(result["lines"]), 3)
		self.assertEqual(result["lines"][2]["withdrawal"], 10.0)
		self.assertTrue(any("does not match" in w and "1 line" in w for w in result["warnings"]))

	def test_rows_without_amount_are_skipped_and_counted(self):
		content = (
			b"Date,Description,Debit,Credit\n"
			b"01/10/2026,Fee,10.00,\n"
			b"02/10/2026,Cheque returned,,\n"
			b"03/10/2026,Zero,0.00,0.00\n"
			b"End of report,,,\n"
		)
		result = read_statement("s.csv", content)
		self.assertEqual(len(result["lines"]), 1)
		self.assertEqual(result["lines"][0]["description"], "Fee")
		self.assertEqual(result["skipped_rows"], 3)
		self.assertTrue(any("3 row(s) were left out" in w for w in result["warnings"]))

	def test_amount_parsing(self):
		cases = {
			"1,250.00": 1250.0,
			"(1,250.00)": -1250.0,
			"1,250.00-": -1250.0,
			"-1,250.00": -1250.0,
			"1,250.00 DR": -1250.0,
			"1,250.00Cr": 1250.0,
			"Rs. 1,250.00": 1250.0,
			"Rs 1,250/-": 1250.0,
			"PKR 12,34,567.50": 1234567.5,
			"$45.10": 45.1,
			"1250": 1250.0,
			"1.250,75": 1250.75,
			"": None,
			"-": None,
			"Cheque": None,
			"31/10/2026": None,
		}
		for text, expected in cases.items():
			self.assertEqual(parse_amount(text), expected, text)
		self.assertEqual(parse_amount(1250), 1250.0)
		self.assertIsNone(parse_amount(None))


class TestExcel(StatementCase):
	def test_xlsx_with_header_rows_above_and_closing_row_below(self):
		result = read("excel_export.xlsx")
		self.assert_contract(result)
		self.assertEqual(result["file_type"], "xlsx")
		self.assertEqual(
			result["header"],
			{
				"bank_name": "Sample Bank Limited",
				"account_title": "Sitara Hardware Store",
				"account_number": "1234567890123",
				"iban": "PK36SMPL0000111122223333",
				"period_from": "2026-10-01",
				"period_to": "2026-10-31",
				"opening_balance": 150000.0,
				"closing_balance": 172500.0,
				"currency": "PKR",
			},
		)
		layout = result["layout"]
		self.assertEqual(layout["header_row"], 8)
		self.assertEqual(layout["date"], 0)  # "Transaction Date", not "Value Date"
		self.assertEqual(layout["description"], [2, 3])  # Description + Remarks
		self.assertEqual(layout["reference"], 4)
		self.assertEqual((layout["withdrawal"], layout["deposit"], layout["balance"]), (5, 6, 7))
		self.assertEqual(
			result["lines"],
			[
				{
					"date": "2026-10-02",  # real date cell
					"description": "Cheque paid Karim Packaging",
					"reference_no": "451201",  # number cell
					"withdrawal": 45000.0,
					"deposit": 0.0,
					"balance": 105000.0,
				},
				{
					"date": "2026-10-07",  # text "07-Oct-2026"
					"description": "IBFT Noor Textiles",
					"reference_no": "FT26280AB",
					"withdrawal": 0.0,
					"deposit": 80000.5,
					"balance": 185000.5,
				},
				{
					"date": "2026-10-12",  # Excel serial number
					"description": "ATM withdrawal Saddar",
					"reference_no": "",
					"withdrawal": 10000.0,  # the deposit cell holds 0
					"deposit": 0.0,
					"balance": 175000.5,
				},
				{
					"date": "2026-10-25",
					"description": "Utility bill",
					"reference_no": "",
					"withdrawal": 2500.5,  # text "2,500.50"
					"deposit": 0.0,
					"balance": 172500.0,
				},
			],
		)
		# only the "*** End of statement ***" row is unexplained; closing balance and total rows are not
		self.assertEqual(result["skipped_rows"], 1)
		self.assertEqual(len(result["warnings"]), 1)
		self.assertEqual(result["preview_rows"][3], ["Account Number", "1234567890123", "", "", "", "", "", ""])
		self.assertEqual(result["preview_rows"][9][0], "2026-10-02")

	def test_xlsx_layout_override(self):
		# header_row given by the user, description limited to the Remarks column
		layout = dict(read("excel_export.xlsx")["layout"], description=[3], reference=None)
		result = read("excel_export.xlsx", layout=layout)
		self.assertEqual([line["description"] for line in result["lines"]], ["Karim Packaging", "", "Saddar", ""])
		self.assertEqual([line["reference_no"] for line in result["lines"]], ["", "", "", ""])
		self.assertEqual(money(result)[1], ("2026-10-07", 0.0, 80000.5, 185000.5))

	def test_xls(self):
		result = read("excel_legacy.xls")
		self.assert_contract(result)
		self.assertEqual(result["file_type"], "xls")
		self.assertEqual(result["header"]["bank_name"], "Allied Sample Bank")
		self.assertEqual(result["header"]["account_number"], "0044-112233-7")
		self.assertEqual(result["layout"]["header_row"], 2)
		self.assertEqual(result["columns"], ["Date", "Narration", "Chq No", "Debit", "Credit", "Balance"])
		self.assertEqual(
			money(result),
			[
				("2026-10-03", 0.0, 30000.0, 130000.0),
				("2026-10-10", 12500.75, 0.0, 117499.25),
				("2026-10-11", 100.0, 0.0, 117399.25),
			],
		)
		self.assertEqual(result["lines"][1]["description"], "Cheque paid Usman Glass")
		self.assertEqual(result["lines"][1]["reference_no"], "9001")
		self.assertEqual(result["warnings"], [])

	def test_html_table_saved_as_xls(self):
		content = (
			b"<html><body><table>"
			b"<tr><td colspan='4'>Sample Bank Limited</td></tr>"
			b"<tr><th>Date</th><th>Description</th><th>Withdrawal</th><th>Deposit</th></tr>"
			b"<tr><td>05/10/2026</td><td>Cash<br>deposit</td><td></td><td>2,000.00</td></tr>"
			b"<tr><td>16/10/2026</td><td>Fee</td><td>15.00</td><td></td></tr>"
			b"</table></body></html>"
		)
		result = read_statement("export.xls", content)
		self.assertEqual(result["file_type"], "xls")
		self.assertEqual(result["header"]["bank_name"], "Sample Bank Limited")
		self.assertEqual(
			[(line["date"], line["description"], line["withdrawal"], line["deposit"]) for line in result["lines"]],
			[("2026-10-05", "Cash deposit", 0.0, 2000.0), ("2026-10-16", "Fee", 15.0, 0.0)],
		)


MULTI_PAGE_LINES = [
	("2026-10-02", "Cheque paid Karim Packaging Works", "00451201", 45000.0, 0.0, 205000.0),
	("2026-10-03", "IBFT from Noor Textiles Ref FT26276XK91 Inv 1045", "", 0.0, 120500.0, 325500.0),
	("2026-10-05", "ATM cash withdrawal Saddar Karachi", "", 20000.0, 0.0, 305500.0),
	("2026-10-07", "Online bill payment K-Electric Consumer 0400012345678", "", 18340.5, 0.0, 287159.5),
	("2026-10-09", "Cash deposit", "", 0.0, 60000.0, 347159.5),
	("2026-10-12", "Cheque paid Zafar Transport Services against bilty 7781", "00451202", 32750.0, 0.0, 314409.5),
	("2026-10-15", "Withholding tax on cash withdrawal", "", 120.0, 0.0, 314289.5),
	("2026-10-20", "Inward clearing Rehman Traders", "77120045", 0.0, 85000.0, 399289.5),
	("2026-10-26", "Salary transfer batch October staff payroll", "", 150000.0, 0.0, 249289.5),
	("2026-10-30", "Profit credited", "", 0.0, 1845.25, 251134.75),
	("2026-10-31", "SMS alert charges incl. FED", "", 150.0, 0.0, 250984.75),
]
SINGLE_AMOUNT_LINES = [
	("2026-10-05", "POS purchase Metro Cash & Carry", "448812", 12500.0, 0.0, 187500.0),
	("2026-10-08", "Funds transfer from Hamza Electronics", "FT8821", 0.0, 40000.0, 227500.0),
	("2026-10-13", "Cheque 10023 paid Faisal Paint House", "10023", 27300.0, 0.0, 200200.0),
	("2026-10-21", "Cash deposit by Imran", "", 0.0, 15000.0, 215200.0),
	("2026-10-28", "Bank charges", "", 250.0, 0.0, 214950.0),
]
BALANCE_ONLY_LINES = [
	("2026-10-03", "Cash deposit counter", "", 0.0, 25000.0, 105000.0),
	("2026-10-06", "Cheque 000187 Madina Steel", "", 30000.0, 0.0, 75000.0),
	("2026-10-14", "Mobile top-up", "", 1000.0, 0.0, 74000.0),
	("2026-10-19", "Raast transfer from Sana Boutique", "", 0.0, 46500.0, 120500.0),
	("2026-10-27", "Rent paid to Gulshan Plaza", "", 60000.0, 0.0, 60500.0),
]


def flat(result: dict):
	return [
		(
			line["date"],
			line["description"],
			line["reference_no"],
			line["withdrawal"],
			line["deposit"],
			line["balance"],
		)
		for line in result["lines"]
	]


class TestPDF(StatementCase):
	def test_multi_page_with_header_repeated_on_each_page(self):
		result = read("multi_page.pdf")
		self.assert_contract(result)
		self.assertEqual(result["file_type"], "pdf")
		self.assertEqual(
			result["header"],
			{
				"bank_name": "Sample Bank Limited",
				"account_title": "Sitara Hardware Store",
				"account_number": "0123-4567890-01",
				"iban": "PK36SMPL0000111122223333",
				"period_from": "2026-10-01",
				"period_to": "2026-10-31",
				"opening_balance": 250000.0,
				"closing_balance": 250984.75,
				"currency": "PKR",
			},
		)
		self.assertEqual(
			result["columns"],
			["Date", "Value Date", "Particulars", "Cheque No", "Debit", "Credit", "Balance"],
		)
		layout = result["layout"]
		self.assertIsNone(layout["header_row"])
		self.assertEqual(layout["date"], 0)
		self.assertEqual(layout["description"], [2])
		self.assertEqual(layout["reference"], 3)
		self.assertEqual((layout["withdrawal"], layout["deposit"], layout["balance"]), (4, 5, 6))
		# 11 transactions over 3 pages; multi-line descriptions joined; "BALANCE B/F", "Closing
		# Balance" and "Total" rows left out
		self.assertEqual(flat(result), MULTI_PAGE_LINES)
		# nothing from the header block, repeated on pages 2 and 3, leaks into the lines
		everything = " ".join(line["description"] + " " + line["reference_no"] for line in result["lines"])
		for leaked in ("Sample Bank", "Sitara", "IBAN", "PK36", "Page", "computer generated", "Opening", "Lahore"):
			self.assertNotIn(leaked, everything)
		# the one-off note under the table on the last page is the only unexplained row
		self.assertEqual(result["skipped_rows"], 1)
		self.assertEqual(len(result["warnings"]), 1)
		self.assertEqual(
			result["preview_rows"][1],
			["02-OCT-2026", "02-OCT-2026", "Cheque paid", "00451201", "45,000.00", "", "205,000.00"],
		)
		self.assertEqual(result["preview_rows"][2], ["", "", "Karim Packaging Works", "", "", "", ""])

	def test_single_amount_column_with_wrapped_headings(self):
		result = read("single_amount.pdf")
		self.assert_contract(result)
		# the headings "Transaction / Date" and "Ref / No" are printed on two lines
		self.assertEqual(result["columns"], ["Transaction Date", "Description", "Ref No", "Amount", "Balance"])
		layout = result["layout"]
		self.assertEqual((layout["date"], layout["description"], layout["reference"]), (0, [1], 2))
		self.assertEqual((layout["withdrawal"], layout["deposit"], layout["amount"], layout["balance"]), (None, None, 3, 4))
		self.assertEqual(layout["date_format"], "%d/%m/%Y")
		self.assertEqual(flat(result), SINGLE_AMOUNT_LINES)  # "12,500.00 Dr" / "40,000.00 Cr"
		header = result["header"]
		self.assertEqual(header["bank_name"], "Crescent Demo Bank")
		# title and account number are printed on one line; the title must stop before "Account No"
		self.assertEqual(header["account_title"], "Sitara Hardware Store")
		self.assertEqual(header["account_number"], "0101-55667788")
		self.assertEqual(header["iban"], "PK24CDBK0000010155667788")  # printed with spaces
		self.assertEqual((header["period_from"], header["period_to"]), ("2026-10-01", "2026-10-31"))
		self.assertEqual(header["opening_balance"], 200000.0)
		self.assertIsNone(header["closing_balance"])
		self.assertEqual(result["warnings"], [])
		self.assertEqual(result["skipped_rows"], 0)

	def test_side_decided_only_by_running_balance(self):
		# one unsigned "Amount" column: only the balance change tells money in from money out
		result = read("balance_only.pdf")
		self.assert_contract(result)
		self.assertEqual(result["columns"], ["Date", "Particulars", "Amount", "Balance"])
		self.assertEqual(flat(result), BALANCE_ONLY_LINES)
		self.assertEqual(result["header"]["bank_name"], "Indus Sample Bank")
		self.assertEqual(result["header"]["account_title"], "Sitara Hardware Store")  # "Customer Name:"
		self.assertEqual(result["header"]["account_number"], "55501234567")  # "A/C #:"
		self.assertEqual(result["header"]["opening_balance"], 80000.0)
		self.assertIsNone(result["header"]["iban"])
		self.assertEqual(result["warnings"], [])

	def test_wrong_columns_are_corrected_by_running_balance(self):
		# debit and credit swapped on purpose: the balance still shows the true side, with a warning
		layout = dict(read("multi_page.pdf")["layout"], withdrawal=5, deposit=4)
		result = read("multi_page.pdf", layout=layout)
		self.assertEqual(flat(result), MULTI_PAGE_LINES)
		self.assertTrue(any("11 line(s) were moved" in w for w in result["warnings"]))

	def test_pdf_layout_override(self):
		# the user picks the value date column as the date
		layout = dict(read("multi_page.pdf")["layout"], date=1)
		result = read("multi_page.pdf", layout=layout)
		self.assertEqual(result["layout"]["date"], 1)
		dates = [line["date"] for line in result["lines"]]
		self.assertEqual(dates[3], "2026-10-08")
		self.assertEqual(dates[7], "2026-10-21")
		self.assertEqual(len(dates), 11)

	def test_pypdf_fallback_when_pdfplumber_fails(self):
		with patch.object(reader, "_pdf_word_pages", side_effect=RuntimeError("boom")):
			multi = read("multi_page.pdf")
			single = read("single_amount.pdf")
		self.assertEqual(flat(multi), MULTI_PAGE_LINES)
		self.assertEqual(multi["header"]["iban"], "PK36SMPL0000111122223333")
		self.assertEqual(flat(single), SINGLE_AMOUNT_LINES)
		self.assertTrue(any("simpler method" in w for w in multi["warnings"]))

	def test_plain_text_fallback(self):
		# neither word positions nor laid-out text: a date at the start, amounts at the end of a line
		with (
			patch.object(reader, "_pdf_word_pages", side_effect=RuntimeError("boom")),
			patch.object(reader, "_pdf_layout_word_pages", side_effect=RuntimeError("boom")),
		):
			result = read("balance_only.pdf")
		self.assert_contract(result)
		self.assertEqual(flat(result), BALANCE_ONLY_LINES)
		self.assertEqual(result["header"]["opening_balance"], 80000.0)

	def test_password_protected_pdf(self):
		with self.assertRaises(StatementReadError) as raised:
			read("encrypted.pdf")
		self.assertIn("password-protected", str(raised.exception))
		with self.assertRaises(StatementReadError) as raised:
			read("encrypted.pdf", password="not-the-password")
		self.assertIn("not correct", str(raised.exception))
		result = read("encrypted.pdf", password=PDF_PASSWORD)
		self.assertEqual(flat(result), BALANCE_ONLY_LINES)

	def test_scanned_pdf_without_text(self):
		with self.assertRaises(StatementReadError) as raised:
			read("scanned.pdf")
		self.assertIn("scanned image", str(raised.exception))


class TestErrors(StatementCase):
	def test_no_date_column(self):
		with self.assertRaises(StatementReadError) as raised:
			read_statement("stock.csv", b"Item,Qty,Rate\nCement,10,1250.00\nSteel,4,96000.00\n")
		self.assertIn("No date column", str(raised.exception))

	def test_layout_pointing_at_a_column_without_dates(self):
		layout = dict(read("signed_amount.csv")["layout"], date=1)
		with self.assertRaises(StatementReadError) as raised:
			read("signed_amount.csv", layout=layout)
		self.assertIn("No dates were found", str(raised.exception))

	def test_empty_file(self):
		with self.assertRaises(StatementReadError):
			read_statement("empty.csv", b"")

	def test_error_is_a_plain_exception(self):
		self.assertTrue(issubclass(StatementReadError, Exception))
