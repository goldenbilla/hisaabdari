# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import unittest

import frappe
from frappe.utils import cint, flt

from hisaabdari.setup.utils import get_exchange_rate
from hisaabdari.tests.utils import ERPNextTestSuite


def save_new_records(test_records):
	for record in test_records:
		# If both selling and buying enabled
		purpose = "Selling-Buying"

		if cint(record.get("for_buying")) == 0 and cint(record.get("for_selling")) == 1:
			purpose = "Selling"
		if cint(record.get("for_buying")) == 1 and cint(record.get("for_selling")) == 0:
			purpose = "Buying"
		kwargs = dict(
			doctype=record.get("doctype"),
			docname=record.get("date")
			+ "-"
			+ record.get("from_currency")
			+ "-"
			+ record.get("to_currency")
			+ "-"
			+ purpose,
			fieldname="exchange_rate",
			value=record.get("exchange_rate"),
		)

		try:
			frappe.set_value(**kwargs)
		except frappe.DoesNotExistError:
			curr_exchange = frappe.new_doc(record.get("doctype"))
			curr_exchange.date = record["date"]
			curr_exchange.from_currency = record["from_currency"]
			curr_exchange.to_currency = record["to_currency"]
			curr_exchange.exchange_rate = record["exchange_rate"]
			curr_exchange.for_buying = record["for_buying"]
			curr_exchange.for_selling = record["for_selling"]
			curr_exchange.insert()


class TestCurrencyExchange(ERPNextTestSuite):
	def setUp(self):
		self.load_test_records("Currency Exchange")
		save_new_records(self.globalTestRecords["Currency Exchange"])

	def test_exchange_rate(self):
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)

		# Start with allow_stale is True
		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-01", "for_buying")
		self.assertEqual(flt(exchange_rate, 3), 60.0)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-15", "for_buying")
		self.assertEqual(exchange_rate, 65.1)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-30", "for_selling")
		self.assertEqual(exchange_rate, 62.9)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-20", "for_buying")
		self.assertFalse(exchange_rate == 60)
		self.assertEqual(flt(exchange_rate, 3), 65.1)

	def test_exchange_rate_strict(self):
		# strict currency settings
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 0)
		frappe.db.set_single_value("Accounts Settings", "stale_days", 1)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-01", "for_buying")
		self.assertEqual(exchange_rate, 60.0)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-30", "for_selling")
		self.assertEqual(exchange_rate, 62.9)

	def test_exchange_rate_strict_switched(self):
		# Start with allow_stale is True
		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-15", "for_buying")
		self.assertEqual(exchange_rate, 65.1)

		frappe.db.set_single_value("Accounts Settings", "allow_stale", 0)
		frappe.db.set_single_value("Accounts Settings", "stale_days", 1)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-30", "for_buying")
		self.assertFalse(exchange_rate == 65)
		self.assertEqual(flt(exchange_rate, 3), 62.9)

	def test_side_specific_record_wins_on_same_date(self):
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)
		for for_buying, for_selling, rate in ((1, 1, 100), (0, 1, 101), (1, 0, 99)):
			frappe.get_doc(
				doctype="Currency Exchange",
				date="2031-03-10",
				from_currency="GBP",
				to_currency="INR",
				exchange_rate=rate,
				for_buying=for_buying,
				for_selling=for_selling,
			).insert()

		self.assertEqual(get_exchange_rate("GBP", "INR", "2031-03-10", "for_selling"), 101)
		self.assertEqual(get_exchange_rate("GBP", "INR", "2031-03-10", "for_buying"), 99)
		self.assertEqual(get_exchange_rate("GBP", "INR", "2031-03-11", "for_selling"), 101)

	def test_fields_in_name_cannot_change(self):
		doc = frappe.get_doc(
			doctype="Currency Exchange",
			date="2031-03-01",
			from_currency="CHF",
			to_currency="INR",
			exchange_rate=70,
			for_selling=1,
		).insert()

		doc.exchange_rate = 71
		doc.save()

		doc.date = "2031-03-10"
		self.assertRaises(frappe.CannotChangeConstantError, doc.save)

		doc.reload()
		doc.for_buying = 0
		self.assertRaises(frappe.CannotChangeConstantError, doc.save)

	def test_reverse_record_is_used_when_no_direct_record(self):
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)
		frappe.get_doc(
			doctype="Currency Exchange",
			date="2031-03-10",
			from_currency="CHF",
			to_currency="INR",
			exchange_rate=82,
			for_buying=1,
			for_selling=0,
		).insert()

		self.assertAlmostEqual(get_exchange_rate("INR", "CHF", "2031-03-10"), 1 / 82)

	def test_reverse_record_flips_buying_selling_side(self):
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)
		for from_currency, for_buying, for_selling, rate, args in (
			("CHF", 0, 1, 82, "for_buying"),
			("JPY", 1, 0, 90, "for_selling"),
		):
			frappe.get_doc(
				doctype="Currency Exchange",
				date="2031-03-10",
				from_currency=from_currency,
				to_currency="INR",
				exchange_rate=rate,
				for_buying=for_buying,
				for_selling=for_selling,
			).insert()

			self.assertAlmostEqual(get_exchange_rate("INR", from_currency, "2031-03-10", args), 1 / rate)

	def test_direct_record_wins_over_reverse_record(self):
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)
		for from_currency, to_currency, rate, date in (
			("USD", "INR", 82, "2031-03-10"),
			("INR", "USD", 0.0125, "2031-03-09"),
		):
			frappe.get_doc(
				doctype="Currency Exchange",
				date=date,
				from_currency=from_currency,
				to_currency=to_currency,
				exchange_rate=rate,
				for_buying=1,
				for_selling=0,
			).insert()

		self.assertEqual(get_exchange_rate("INR", "USD", "2031-03-10"), 0.0125)

	def test_no_record_in_either_direction(self):
		self.assertEqual(get_exchange_rate("CHF", "JPY", "2031-03-10"), 0.0)
