# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import unittest
from contextlib import contextmanager
from typing import Any, NewType

import frappe
from frappe import _
from frappe.core.doctype.report.report import get_report_module_dotted_path
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.tests.utils import load_test_records_for
from frappe.utils import now_datetime, today

ReportFilters = dict[str, Any]
ReportName = NewType("ReportName", str)


def execute_script_report(
	report_name: ReportName,
	module: str,
	filters: ReportFilters,
	default_filters: ReportFilters | None = None,
	optional_filters: ReportFilters | None = None,
):
	"""Util for testing execution of a report with specified filters.

	Tests the execution of report with default_filters + filters.
	Tests the execution using optional_filters one at a time.

	Args:
	        report_name: Human readable name of report (unscrubbed)
	        module: module to which report belongs to
	        filters: specific values for filters
	        default_filters: default values for filters such as company name.
	        optional_filters: filters which should be tested one at a time in addition to default filters.
	"""

	if default_filters is None:
		default_filters = {}

	test_filters = []
	report_execute_fn = frappe.get_attr(get_report_module_dotted_path(module, report_name) + ".execute")
	report_filters = frappe._dict(default_filters).copy().update(filters)

	test_filters.append(report_filters)

	if optional_filters:
		for key, value in optional_filters.items():
			test_filters.append(report_filters.copy().update({key: value}))

	for test_filter in test_filters:
		try:
			report_execute_fn(test_filter)
		except Exception:
			print(f"Report failed to execute with filters: {test_filter}")
			raise


def if_lending_app_installed(function):
	"""Decorator to check if lending app is installed"""

	def wrapper(*args, **kwargs):
		if "lending" in frappe.get_installed_apps():
			return function(*args, **kwargs)
		return

	return wrapper


def if_lending_app_not_installed(function):
	"""Decorator to check if lending app is not installed"""

	def wrapper(*args, **kwargs):
		if "lending" not in frappe.get_installed_apps():
			return function(*args, **kwargs)
		return

	return wrapper


class BootStrapTestData:
	def __init__(self):
		self.make_presets()
		self.make_master_data()

	def make_presets(self):
		from frappe.desk.page.setup_wizard.install_fixtures import update_genders, update_salutations

		from hisaabdari.setup.setup_wizard.operations.install_fixtures import (
			add_uom_data,
			get_preset_records,
		)

		update_genders()
		update_salutations()

		records = get_preset_records("India")

		from hisaabdari.setup.setup_wizard.operations.install_fixtures import read_lines

		for doctype, title_field, filename in (("UTM Source", "name", "marketing_source.txt"),):
			records += [{"doctype": doctype, title_field: title} for title in read_lines(filename)]

		presets_primary_key_map = {
			"Address Template": "country",
			"Item Group": "item_group_name",
			"Customer Group": "customer_group_name",
			"Supplier Group": "supplier_group_name",
			"Mode of Payment": "mode_of_payment",
			"Party Type": "party_type",
			"Print Heading": "print_heading",
		}
		for x in records:
			dt = x.get("doctype")
			dn = x.get("name") or x.get(presets_primary_key_map.get(dt))

			if not frappe.db.exists(dt, dn):
				doc = frappe.get_doc(x)
				doc.insert()

		add_uom_data()

		frappe.db.commit()  # nosemgrep

	def make_master_data(self):
		self.update_system_settings()
		self.make_fiscal_year()
		self.make_company()
		self.make_test_account()
		self.make_supplier_group()
		self.make_currency_exchange()
		self.make_payment_term()
		self.make_payment_terms_template()
		self.make_account()
		self.make_supplier()
		self.make_role()
		self.make_customer_group()
		self.make_customer()
		self.make_user()
		self.make_cost_center()
		self.make_warehouse()
		self.make_uom()
		self.make_item_tax_template()
		self.make_item_group()
		self.update_stock_settings()
		self.make_item()
		self.make_price_list()
		self.make_item_price()
		self.make_sales_taxes_template()
		self.make_purchase_taxes_template()
		self.make_address()
		self.make_contact()
		self.update_selling_settings()

		frappe.db.commit()  # nosemgrep

		# custom field
		self.make_custom_field()

	def update_system_settings(self):
		system_settings = frappe.get_doc("System Settings")
		system_settings.time_zone = "Asia/Kolkata"
		system_settings.language = "en"
		system_settings.currency_precision = system_settings.float_precision = 2
		system_settings.rounding_method = "Banker's Rounding"
		system_settings.save()

	def update_selling_settings(self):
		selling_settings = frappe.get_doc("Selling Settings")
		selling_settings.selling_price_list = "Standard Selling"
		selling_settings.save()

	def update_stock_settings(self):
		stock_settings = frappe.get_doc("Stock Settings")
		stock_settings.item_naming_by = "Item Code"
		stock_settings.valuation_method = "FIFO"
		stock_settings.stock_uom = "Nos"
		stock_settings.auto_insert_price_list_rate_if_missing = 1
		stock_settings.update_price_list_based_on = "Rate"
		stock_settings.enable_serial_and_batch_no_for_item = 1
		stock_settings.save()

	def make_records(self, key, records):
		doctype = records[0].get("doctype")

		def get_filters(record):
			filters = {}
			for x in key:
				filters[x] = record.get(x)
			return filters

		for x in records:
			filters = get_filters(x)
			if not frappe.db.exists(doctype, filters):
				frappe.get_doc(x).insert()

	def make_price_list(self):
		records = [
			{
				"doctype": "Price List",
				"price_list_name": _("Standard Buying"),
				"enabled": 1,
				"buying": 1,
				"selling": 0,
				"currency": "INR",
			},
			{
				"doctype": "Price List",
				"price_list_name": _("Standard Selling"),
				"enabled": 1,
				"buying": 0,
				"selling": 1,
				"currency": "INR",
			},
			{
				"buying": 1,
				"currency": "INR",
				"doctype": "Price List",
				"enabled": 1,
				"price_not_uom_dependant": 1,
				"price_list_name": "_Test Price List",
				"selling": 1,
			},
			{
				"buying": 1,
				"currency": "INR",
				"doctype": "Price List",
				"enabled": 1,
				"price_list_name": "_Test Price List 2",
				"selling": 1,
			},
			{
				"buying": 1,
				"currency": "INR",
				"doctype": "Price List",
				"enabled": 1,
				"price_list_name": "_Test Price List India",
				"selling": 1,
			},
			{
				"buying": 1,
				"currency": "USD",
				"doctype": "Price List",
				"enabled": 1,
				"price_list_name": "_Test Price List Rest of the World",
				"selling": 1,
			},
			{
				"buying": 0,
				"currency": "USD",
				"doctype": "Price List",
				"enabled": 1,
				"price_list_name": "_Test Selling Price List",
				"selling": 1,
			},
			{
				"buying": 1,
				"currency": "USD",
				"doctype": "Price List",
				"enabled": 1,
				"price_list_name": "_Test Buying Price List",
				"selling": 0,
			},
		]
		self.make_records(["price_list_name", "enabled", "selling", "buying", "currency"], records)

	def make_customer_group(self):
		records = [
			{
				"customer_group_name": "_Test Customer Group",
				"doctype": "Customer Group",
				"is_group": 0,
				"parent_customer_group": "All Customer Groups",
			},
			{
				"customer_group_name": "_Test Customer Group 1",
				"doctype": "Customer Group",
				"is_group": 0,
				"parent_customer_group": "All Customer Groups",
			},
		]
		self.make_records(["customer_group_name"], records)

	def make_role(self):
		records = [
			{"doctype": "Role", "role_name": "_Test Role", "desk_access": 1},
			{"doctype": "Role", "role_name": "_Test Role 2", "desk_access": 1},
			{"doctype": "Role", "role_name": "_Test Role 3", "desk_access": 1},
			{"doctype": "Role", "role_name": "_Test Role 4", "desk_access": 0},
			{"doctype": "Role", "role_name": "Technician"},
		]
		self.make_records(["role_name"], records)

	def make_user(self):
		records = [
			{
				"doctype": "User",
				"email": "test@example.com",
				"enabled": 1,
				"first_name": "_Test",
				"new_password": "Eastern_43A1W",
				"roles": [
					{"doctype": "Has Role", "parentfield": "roles", "role": "_Test Role"},
					{"doctype": "Has Role", "parentfield": "roles", "role": "Accounts User"},
					{"doctype": "Has Role", "parentfield": "roles", "role": "System Manager"},
				],
			},
			{
				"doctype": "User",
				"email": "test1@example.com",
				"first_name": "_Test1",
				"new_password": "Eastern_43A1W",
			},
			{
				"doctype": "User",
				"email": "test2@example.com",
				"first_name": "_Test2",
				"new_password": "Eastern_43A1W",
				"enabled": 1,
			},
			{
				"doctype": "User",
				"email": "test3@example.com",
				"first_name": "_Test3",
				"new_password": "Eastern_43A1W",
				"enabled": 1,
			},
			{
				"doctype": "User",
				"email": "test4@example.com",
				"first_name": "_Test4",
				"new_password": "Eastern_43A1W",
				"enabled": 1,
			},
			{
				"doctype": "User",
				"email": "test'5@example.com",
				"first_name": "_Test'5",
				"new_password": "Eastern_43A1W",
				"enabled": 1,
			},
			{
				"doctype": "User",
				"email": "testperm@example.com",
				"first_name": "_Test Perm",
				"new_password": "Eastern_43A1W",
				"enabled": 1,
			},
			{
				"doctype": "User",
				"email": "testdelete@example.com",
				"enabled": 1,
				"first_name": "_Test",
				"new_password": "Eastern_43A1W",
				"roles": [
					{"doctype": "Has Role", "parentfield": "roles", "role": "_Test Role 2"},
					{"doctype": "Has Role", "parentfield": "roles", "role": "System Manager"},
				],
			},
			{
				"doctype": "User",
				"email": "testpassword@example.com",
				"enabled": 1,
				"first_name": "_Test",
				"new_password": "Eastern_43A1W",
				"roles": [{"doctype": "Has Role", "parentfield": "roles", "role": "System Manager"}],
			},
			{
				"doctype": "User",
				"email": "marcus@abc.com",
				"first_name": "marcus@abc.com",
				"new_password": "password",
				"roles": [{"doctype": "Has Role", "role": "Technician"}],
			},
			{
				"doctype": "User",
				"email": "thalia@abc.com",
				"first_name": "thalia@abc.com",
				"new_password": "password",
				"roles": [{"doctype": "Has Role", "role": "Technician"}],
			},
			{
				"doctype": "User",
				"email": "mathias@abc.com",
				"first_name": "mathias@abc.com",
				"new_password": "password",
				"roles": [{"doctype": "Has Role", "role": "Technician"}],
			},
		]
		self.make_records(["email"], records)

	def make_company(self):
		records = load_test_records_for("Company")["Company"]
		self.make_records(["company_name"], records)

	def make_fiscal_year(self):
		records = [
			{
				"doctype": "Fiscal Year",
				"year": "_Test Short Fiscal Year 2011",
				"is_short_year": 1,
				"year_start_date": "2011-04-01",
				"year_end_date": "2011-12-31",
			}
		]

		start = 2012
		end = now_datetime().year + 25
		for year in range(start, end):
			records.append(
				{
					"doctype": "Fiscal Year",
					"year": f"_Test Fiscal Year {year}",
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
				}
			)

		key = ["year_start_date", "year_end_date"]
		self.make_records(key, records)

	def make_currency_exchange(self):
		# Upstream tests got missing rates from a public rates service. That fetch is not part of
		# HisaabDari, so old-dated baseline rates stand in; any newer record a test creates wins.
		inr_value = {"USD": 80.0, "EUR": 90.0, "GBP": 100.0, "INR": 1.0}
		records = []
		for from_currency, from_value in inr_value.items():
			for to_currency, to_value in inr_value.items():
				if from_currency == to_currency:
					continue
				records.append(
					{
						"doctype": "Currency Exchange",
						"date": "2000-01-01",
						"from_currency": from_currency,
						"to_currency": to_currency,
						"exchange_rate": from_value / to_value,
						"for_buying": 1,
						"for_selling": 1,
					}
				)
		self.make_records(["date", "from_currency", "to_currency"], records)

	def make_payment_term(self):
		records = [
			{
				"doctype": "Payment Term",
				"due_date_based_on": "Day(s) after invoice date",
				"payment_term_name": "_Test N30",
				"description": "_Test Net 30 Days",
				"invoice_portion": 50,
				"credit_days": 30,
			},
			{
				"doctype": "Payment Term",
				"due_date_based_on": "Day(s) after invoice date",
				"payment_term_name": "_Test COD",
				"description": "_Test Cash on Delivery",
				"invoice_portion": 50,
				"credit_days": 0,
			},
			{
				"doctype": "Payment Term",
				"due_date_based_on": "Month(s) after the end of the invoice month",
				"payment_term_name": "_Test EONM",
				"description": "_Test End of Next Month",
				"invoice_portion": 100,
				"credit_months": 1,
			},
			{
				"doctype": "Payment Term",
				"due_date_based_on": "Day(s) after invoice date",
				"payment_term_name": "_Test N30 1",
				"description": "_Test Net 30 Days",
				"invoice_portion": 100,
				"credit_days": 30,
			},
		]
		self.make_records(["payment_term_name"], records)

	def make_payment_terms_template(self):
		records = [
			{
				"doctype": "Payment Terms Template",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"due_date_based_on": "Day(s) after invoice date",
						"idx": 1,
						"description": "Cash on Delivery",
						"invoice_portion": 50,
						"credit_days": 0,
						"credit_months": 0,
						"payment_term": "_Test COD",
					},
					{
						"doctype": "Payment Terms Template Detail",
						"due_date_based_on": "Day(s) after invoice date",
						"idx": 2,
						"description": "Net 30 Days ",
						"invoice_portion": 50,
						"credit_days": 30,
						"credit_months": 0,
						"payment_term": "_Test N30",
					},
				],
				"template_name": "_Test Payment Term Template",
			},
			{
				"doctype": "Payment Terms Template",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"due_date_based_on": "Month(s) after the end of the invoice month",
						"idx": 1,
						"description": "_Test End of Next Months",
						"invoice_portion": 100,
						"credit_days": 0,
						"credit_months": 1,
						"payment_term": "_Test EONM",
					}
				],
				"template_name": "_Test Payment Term Template 1",
			},
			{
				"doctype": "Payment Terms Template",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"due_date_based_on": "Day(s) after invoice date",
						"idx": 1,
						"description": "_Test Net Within 30 days",
						"invoice_portion": 100,
						"credit_days": 30,
						"credit_months": 0,
						"payment_term": "_Test N30 1",
					}
				],
				"template_name": "_Test Payment Term Template 3",
			},
		]
		self.make_records(["template_name"], records)

	def make_account(self):
		records = [
			{
				"doctype": "Account",
				"account_name": "_Test Payable USD",
				"parent_account": "Accounts Receivable - _TC",
				"company": "_Test Company",
				"account_currency": "USD",
			},
			{
				"doctype": "Account",
				"account_name": "_Test Bank",
				"parent_account": "Bank Accounts - _TC",
				"company": "_Test Company",
			},
			{
				"doctype": "Account",
				"account_name": "_Test Bank",
				"parent_account": "Bank Accounts - TCP1",
				"company": "_Test Company with perpetual inventory",
			},
		]
		self.make_records(["account_name", "company"], records)

	def make_supplier(self):
		records = [
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier With Template 1",
				"supplier_group": "_Test Supplier Group",
				"payment_terms": "_Test Payment Term Template 3",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier P",
				"supplier_group": "_Test Supplier Group",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier with Country",
				"supplier_group": "_Test Supplier Group",
				"country": "Greece",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "_Test Supplier Group",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier 1",
				"supplier_group": "_Test Supplier Group",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier 2",
				"supplier_group": "_Test Supplier Group",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier USD",
				"supplier_group": "_Test Supplier Group",
				"default_currency": "USD",
				"accounts": [{"company": "_Test Company", "account": "_Test Payable USD - _TC"}],
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Another Supplier USD",
				"supplier_group": "_Test Supplier Group",
				"default_currency": "USD",
				"accounts": [{"company": "_Test Company", "account": "_Test Payable USD - _TC"}],
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier With Tax Category",
				"supplier_group": "_Test Supplier Group",
			},
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Internal Supplier 2",
				"supplier_group": "_Test Supplier Group",
				"is_internal_supplier": 1,
				"territory": "_Test Territory",
				"represents_company": "_Test Company with perpetual inventory",
				"companies": [{"company": "_Test Company with perpetual inventory"}],
			},
		]
		self.make_records(["supplier_name"], records)

	def make_supplier_group(self):
		records = [
			{
				"doctype": "Supplier Group",
				"supplier_group_name": "_Test Supplier Group",
				"parent_supplier_group": "All Supplier Groups",
			}
		]
		self.make_records(["supplier_group_name"], records)

	def make_cost_center(self):
		records = [
			{
				"company": "_Test Company",
				"cost_center_name": "_Test Cost Center",
				"doctype": "Cost Center",
				"is_group": 0,
				"parent_cost_center": "_Test Company - _TC",
			},
			{
				"company": "_Test Company",
				"cost_center_name": "_Test Cost Center 2",
				"doctype": "Cost Center",
				"is_group": 0,
				"parent_cost_center": "_Test Company - _TC",
			},
			{
				"company": "_Test Company",
				"cost_center_name": "_Test Write Off Cost Center",
				"doctype": "Cost Center",
				"is_group": 0,
				"parent_cost_center": "_Test Company - _TC",
			},
			{
				"company": "_Test Company",
				"cost_center_name": "Sub",
				"doctype": "Cost Center",
				"is_group": 0,
				"parent_cost_center": "_Test Company - _TC",
			},
		]
		self.make_records(["cost_center_name", "company"], records)

	def make_warehouse(self):
		records = [
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Scrap Warehouse",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse 1",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse 2",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Rejected Warehouse",
				"is_group": 0,
			},
			{
				"company": "_Test Company 1",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse 2",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse No Account",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse Group",
				"is_group": 1,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse Group-C1",
				"is_group": 0,
				"parent_warehouse": "_Test Warehouse Group - _TC",
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse Group-C2",
				"is_group": 0,
				"parent_warehouse": "_Test Warehouse Group - _TC",
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse for Stock Reco1",
				"is_group": 0,
			},
			{
				"company": "_Test Company",
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse for Stock Reco2",
				"is_group": 0,
			},
		]
		self.make_records(["warehouse_name", "company"], records)

	def make_uom(self):
		records = [
			{"doctype": "UOM", "must_be_whole_number": 1, "uom_name": "_Test UOM"},
			{"doctype": "UOM", "uom_name": "_Test UOM 1"},
		]
		self.make_records(["uom_name"], records)

	def make_item_tax_template(self):
		records = [
			{
				"doctype": "Item Tax Template",
				"title": "_Test Account Excise Duty @ 10",
				"company": "_Test Company",
				"taxes": [
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 10,
						"tax_type": "_Test Account Excise Duty - _TC",
					}
				],
			},
			{
				"doctype": "Item Tax Template",
				"title": "_Test Account Excise Duty @ 12",
				"company": "_Test Company",
				"taxes": [
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 12,
						"tax_type": "_Test Account Excise Duty - _TC",
					}
				],
			},
			{
				"doctype": "Item Tax Template",
				"title": "_Test Account Excise Duty @ 15",
				"company": "_Test Company",
				"taxes": [
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 15,
						"tax_type": "_Test Account Excise Duty - _TC",
					}
				],
			},
			{
				"doctype": "Item Tax Template",
				"title": "_Test Account Excise Duty @ 20",
				"company": "_Test Company",
				"taxes": [
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 20,
						"tax_type": "_Test Account Excise Duty - _TC",
					}
				],
			},
			{
				"doctype": "Item Tax Template",
				"title": "_Test Item Tax Template 1",
				"company": "_Test Company",
				"taxes": [
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 5,
						"tax_type": "_Test Account Excise Duty - _TC",
					},
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 10,
						"tax_type": "_Test Account Education Cess - _TC",
					},
					{
						"doctype": "Item Tax Template Detail",
						"parentfield": "taxes",
						"tax_rate": 15,
						"tax_type": "_Test Account S&H Education Cess - _TC",
					},
				],
			},
		]
		self.make_records(["title", "company"], records)

	def make_item_group(self):
		records = [
			{
				"doctype": "Item Group",
				"is_group": 0,
				"item_group_name": "_Test Item Group",
				"parent_item_group": "All Item Groups",
				"item_group_defaults": [
					{
						"company": "_Test Company",
						"buying_cost_center": "_Test Cost Center 2 - _TC",
						"selling_cost_center": "_Test Cost Center 2 - _TC",
						"default_warehouse": "_Test Warehouse - _TC",
					}
				],
			},
			{
				"doctype": "Item Group",
				"is_group": 0,
				"item_group_name": "_Test Item Group Desktops",
				"parent_item_group": "All Item Groups",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group A",
				"parent_item_group": "All Item Groups",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group B",
				"parent_item_group": "All Item Groups",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group B - 1",
				"parent_item_group": "_Test Item Group B",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group B - 2",
				"parent_item_group": "_Test Item Group B",
			},
			{
				"doctype": "Item Group",
				"is_group": 0,
				"item_group_name": "_Test Item Group B - 3",
				"parent_item_group": "_Test Item Group B",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group C",
				"parent_item_group": "All Item Groups",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group C - 1",
				"parent_item_group": "_Test Item Group C",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group C - 2",
				"parent_item_group": "_Test Item Group C",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group D",
				"parent_item_group": "All Item Groups",
			},
			{
				"doctype": "Item Group",
				"is_group": 1,
				"item_group_name": "_Test Item Group Tax Parent",
				"parent_item_group": "All Item Groups",
				"taxes": [
					{
						"doctype": "Item Tax",
						"parentfield": "taxes",
						"item_tax_template": "_Test Account Excise Duty @ 10 - _TC",
					},
				],
			},
			{
				"doctype": "Item Group",
				"is_group": 0,
				"item_group_name": "_Test Item Group Tax Child Override",
				"parent_item_group": "_Test Item Group Tax Parent",
				"taxes": [
					{
						"doctype": "Item Tax",
						"parentfield": "taxes",
						"item_tax_template": "_Test Account Excise Duty @ 15 - _TC",
					}
				],
			},
		]
		self.make_records(["item_group_name"], records)

	def make_item(self):
		records = [
			{
				"description": "_Test Item 1",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item",
				"item_group": "_Test Item Group",
				"item_name": "_Test Item",
				"apply_warehouse_wise_reorder_level": 1,
				"opening_stock": 10,
				"valuation_rate": 100,
				"allow_negative_stock": True,
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
				"reorder_levels": [
					{
						"material_request_type": "Purchase",
						"warehouse": "_Test Warehouse - _TC",
						"warehouse_reorder_level": 20,
						"warehouse_reorder_qty": 20,
					}
				],
				"uoms": [
					{"uom": "_Test UOM", "conversion_factor": 1.0},
					{"uom": "_Test UOM 1", "conversion_factor": 10.0},
				],
				"stock_uom": "_Test UOM",
			},
			{
				"description": "_Test Item 2",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item 2",
				"item_group": "_Test Item Group",
				"item_name": "_Test Item 2",
				"stock_uom": "_Test UOM",
				"opening_stock": 10,
				"valuation_rate": 100,
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Item Home Desktop 100 3",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item Home Desktop 100",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Item Home Desktop 100",
				"valuation_rate": 100,
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
				"taxes": [
					{
						"doctype": "Item Tax",
						"parentfield": "taxes",
						"item_tax_template": "_Test Account Excise Duty @ 10 - _TC",
					}
				],
				"stock_uom": "_Test UOM 1",
			},
			{
				"description": "_Test Item Home Desktop 200 4",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"item_code": "_Test Item Home Desktop 200",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Item Home Desktop 200",
				"stock_uom": "_Test UOM 1",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Product Bundle Item 5",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 0,
				"item_code": "_Test Product Bundle Item",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Product Bundle Item",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test FG Item 6",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test FG Item",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test FG Item",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Non Stock Item 7",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 0,
				"item_code": "_Test Non Stock Item",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Non Stock Item",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Serialized Item 8",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 1,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Serialized Item",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Serialized Item",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Serialized Item 9",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 1,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Serialized Item With Series",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Serialized Item With Series",
				"serial_no_series": "ABCD.#####",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Item Home Desktop Manufactured 10",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item Home Desktop Manufactured",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Item Home Desktop Manufactured",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test FG Item 2 11",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test FG Item 2",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test FG Item 2",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Variant Item 12",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Variant Item",
				"item_group": "_Test Item Group Desktops",
				"item_name": "_Test Variant Item",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
				"apply_warehouse_wise_reorder_level": 1,
				"reorder_levels": [
					{
						"material_request_type": "Purchase",
						"warehouse": "_Test Warehouse - _TC",
						"warehouse_reorder_level": 20,
						"warehouse_reorder_qty": 20,
					}
				],
			},
			{
				"description": "_Test Item 1",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item Warehouse Group Wise Reorder",
				"item_group": "_Test Item Group",
				"item_name": "_Test Item Warehouse Group Wise Reorder",
				"apply_warehouse_wise_reorder_level": 1,
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse Group-C1 - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
				"reorder_levels": [
					{
						"warehouse_group": "_Test Warehouse Group - _TC",
						"material_request_type": "Purchase",
						"warehouse": "_Test Warehouse Group-C1 - _TC",
						"warehouse_reorder_level": 20,
						"warehouse_reorder_qty": 20,
					}
				],
				"stock_uom": "_Test UOM",
			},
			{
				"description": "_Test Item With Item Tax Template",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item With Item Tax Template",
				"item_group": "_Test Item Group",
				"item_name": "_Test Item With Item Tax Template",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
				"taxes": [
					{
						"doctype": "Item Tax",
						"parentfield": "taxes",
						"item_tax_template": "_Test Account Excise Duty @ 10 - _TC",
					},
				],
			},
			{
				"description": "_Test Item Inherit Group Item Tax Template 1",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item Inherit Group Item Tax Template 1",
				"item_group": "_Test Item Group Tax Parent",
				"item_name": "_Test Item Inherit Group Item Tax Template 1",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Item Inherit Group Item Tax Template 2",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item Inherit Group Item Tax Template 2",
				"item_group": "_Test Item Group Tax Child Override",
				"item_name": "_Test Item Inherit Group Item Tax Template 2",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
			},
			{
				"description": "_Test Item Override Group Item Tax Template",
				"doctype": "Item",
				"has_batch_no": 0,
				"has_serial_no": 0,
				"inspection_required": 0,
				"is_stock_item": 1,
				"item_code": "_Test Item Override Group Item Tax Template",
				"item_group": "_Test Item Group Tax Child Override",
				"item_name": "_Test Item Override Group Item Tax Template",
				"stock_uom": "_Test UOM",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse - _TC",
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"buying_cost_center": "_Test Cost Center - _TC",
						"selling_cost_center": "_Test Cost Center - _TC",
						"income_account": "Sales - _TC",
					}
				],
				"taxes": [
					{
						"doctype": "Item Tax",
						"parentfield": "taxes",
						"item_tax_template": "_Test Account Excise Duty @ 20 - _TC",
					},
				],
			},
			{
				"description": "_Test",
				"doctype": "Item",
				"is_stock_item": 1,
				"item_code": "138-CMS Shoe",
				"item_group": "_Test Item Group",
				"item_name": "138-CMS Shoe",
				"stock_uom": "_Test UOM",
			},
			{
				"doctype": "Item",
				"item_code": "Loyal Item",
				"item_name": "Loyal Item",
				"item_group": "All Item Groups",
				"company": "_Test Company",
				"is_stock_item": 1,
				"opening_stock": 100,
				"valuation_rate": 10000,
				"stock_uom": "_Test UOM",
			},
			{
				"doctype": "Item",
				"item_code": "_Test Extra Item 1",
				"item_name": "_Test Extra Item 1",
				"item_group": "All Item Groups",
				"company": "_Test Company",
				"is_stock_item": 1,
				"stock_uom": "_Test UOM",
			},
			{
				"doctype": "Item",
				"item_code": "_Test Extra Item 2",
				"item_name": "_Test Extra Item 2",
				"item_group": "All Item Groups",
				"company": "_Test Company",
				"is_stock_item": 1,
				"stock_uom": "_Test UOM",
			},
			{
				"doctype": "Item",
				"item_code": "Stock-Reco-Serial-Item-1",
				"item_name": "Stock-Reco-Serial-Item-1",
				"is_stock_item": 1,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"has_serial_no": 1,
				"serial_no_series": "SRSI.#####",
			},
			{
				"doctype": "Item",
				"item_code": "Stock-Reco-Serial-Item-2",
				"item_name": "Stock-Reco-Serial-Item-2",
				"is_stock_item": 1,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"has_serial_no": 1,
				"serial_no_series": "SRSII.#####",
			},
			{
				"doctype": "Item",
				"item_code": "Stock-Reco-batch-Item-1",
				"item_name": "Stock-Reco-batch-Item-1",
				"is_stock_item": 1,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"has_batch_no": 1,
				"batch_number_series": "BASR.#####",
				"create_new_batch": 1,
			},
			{
				"doctype": "Item",
				"item_code": "_Test Stock Item",
				"item_name": "Test Stock Item",
				"is_stock_item": 1,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			},
			{
				"doctype": "Item",
				"item_code": "Consulting",
				"item_name": "Consulting",
				"is_stock_item": 0,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"company": "_Test Company",
			},
		]
		self.make_records(["item_code", "item_name"], records)

	def make_test_account(self):
		records = [
			# [account_name, parent_account, is_group]
			["_Test Bank", "Bank Accounts", 0, "Bank", None],
			["_Test Bank USD", "Bank Accounts", 0, "Bank", "USD"],
			["_Test Bank EUR", "Bank Accounts", 0, "Bank", "EUR"],
			["_Test Cash", "Cash In Hand", 0, "Cash", None],
			["_Test Account Stock Expenses", "Direct Expenses", 1, None, None],
			["_Test Account Shipping Charges", "_Test Account Stock Expenses", 0, "Chargeable", None],
			["_Test Account Customs Duty", "_Test Account Stock Expenses", 0, "Tax", None],
			["_Test Account Insurance Charges", "_Test Account Stock Expenses", 0, "Chargeable", None],
			["_Test Account Stock Adjustment", "_Test Account Stock Expenses", 0, "Stock Adjustment", None],
			["_Test Employee Advance", "Current Liabilities", 0, None, None],
			["_Test Account Tax Assets", "Current Assets", 1, None, None],
			["_Test Account VAT", "_Test Account Tax Assets", 0, "Tax", None],
			["_Test Account Service Tax", "_Test Account Tax Assets", 0, "Tax", None],
			["_Test Account Reserves and Surplus", "Current Liabilities", 0, None, None],
			["_Test Account Cost for Goods Sold", "Expenses", 0, None, None],
			["_Test Account Excise Duty", "_Test Account Tax Assets", 0, "Tax", None],
			["_Test Account Education Cess", "_Test Account Tax Assets", 0, "Tax", None],
			["_Test Account S&H Education Cess", "_Test Account Tax Assets", 0, "Tax", None],
			["_Test Account CST", "Direct Expenses", 0, "Tax", None],
			["_Test Account Discount", "Direct Expenses", 0, None, None],
			["_Test Write Off", "Indirect Expenses", 0, None, None],
			["_Test Exchange Gain/Loss", "Indirect Expenses", 0, None, None],
			["_Test Account Sales", "Direct Income", 0, None, None],
			# related to Account Inventory Integration
			["_Test Account Stock In Hand", "Current Assets", 0, None, None],
			# fixed asset depreciation
			["_Test Fixed Asset", "Current Assets", 0, "Fixed Asset", None],
			["_Test Accumulated Depreciations", "Current Assets", 0, "Accumulated Depreciation", None],
			["_Test Depreciations", "Expenses", 0, "Depreciation", None],
			["_Test Gain/Loss on Asset Disposal", "Expenses", 0, None, None],
			# Receivable / Payable Account
			["_Test Receivable", "Current Assets", 0, "Receivable", None],
			["_Test Payable", "Current Liabilities", 0, "Payable", None],
			["_Test Receivable USD", "Current Assets", 0, "Receivable", "USD"],
			["_Test Payable USD", "Current Liabilities", 0, "Payable", "USD"],
			# Deferred Account
			["Deferred Revenue", "Current Liabilities", 0, None, None],
			["Deferred Expense", "Current Assets", 0, None, None],
			# Bank
			["HDFC", "Bank Accounts", 0, "Bank", None],
			# Advance Account
			["Advance Received", "Current Liabilities", 0, "Receivable", None],
			["Advance Paid", "Current Assets", 0, "Payable", None],
			# Loyalty Account
			["Loyalty", "Direct Expenses", 0, "Expense Account", None],
		]

		self.test_accounts = []
		for company, abbr in [
			["_Test Company", "_TC"],
			["_Test Company 1", "_TC1"],
			["_Test Company with perpetual inventory", "TCP1"],
		]:
			for account_name, parent_account, is_group, account_type, currency in records:
				if not frappe.db.exists("Account", {"account_name": account_name, "company": company}):
					self.test_accounts.append(
						frappe.get_doc(
							{
								"doctype": "Account",
								"account_name": account_name,
								"parent_account": parent_account + " - " + abbr,
								"company": company,
								"is_group": is_group,
								"account_type": account_type,
								"account_currency": currency,
							}
						).insert()
					)
				else:
					self.test_accounts.append(
						frappe.get_doc("Account", {"account_name": account_name, "company": company})
					)

	def make_customer(self):
		records = [
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer With Template",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer P",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer 1",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer 2",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer 3",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer USD",
				"customer_type": "Individual",
				"doctype": "Customer",
				"default_currency": "USD",
				"accounts": [{"company": "_Test Company", "account": "_Test Receivable USD - _TC"}],
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Customer With Tax Category",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "Test Loyalty Customer",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test Internal Customer 2",
				"customer_type": "Individual",
				"doctype": "Customer",
				"is_internal_customer": 1,
				"represents_company": "_Test Company with perpetual inventory",
				"companies": [{"company": "_Test Company with perpetual inventory"}],
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "Prestiga-Biz",
				"customer_type": "Company",
				"doctype": "Customer",
			},
			{
				"customer_group": "_Test Customer Group",
				"customer_name": "_Test NC",
				"customer_type": "Individual",
				"doctype": "Customer",
			},
		]
		self.make_records(["customer_name"], records)

	def make_sales_taxes_template(self):
		records = [
			{
				"company": "_Test Company",
				"doctype": "Sales Taxes and Charges Template",
				"taxes": [
					{
						"account_head": "_Test Account VAT - _TC",
						"charge_type": "On Net Total",
						"description": "VAT",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 6,
					},
					{
						"account_head": "_Test Account Service Tax - _TC",
						"charge_type": "On Net Total",
						"description": "Service Tax",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 6.36,
					},
				],
				"title": "_Test Sales Taxes and Charges Template",
			},
			{
				"company": "_Test Company",
				"doctype": "Sales Taxes and Charges Template",
				"taxes": [
					{
						"account_head": "_Test Account Shipping Charges - _TC",
						"charge_type": "Actual",
						"cost_center": "_Test Cost Center - _TC",
						"description": "Shipping Charges",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"tax_amount": 100,
					},
					{
						"account_head": "_Test Account Customs Duty - _TC",
						"charge_type": "On Net Total",
						"cost_center": "_Test Cost Center - _TC",
						"description": "Customs Duty",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": 10,
					},
					{
						"account_head": "_Test Account Excise Duty - _TC",
						"charge_type": "On Net Total",
						"cost_center": "_Test Cost Center - _TC",
						"description": "Excise Duty",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": 12,
					},
					{
						"account_head": "_Test Account Education Cess - _TC",
						"charge_type": "On Previous Row Amount",
						"cost_center": "_Test Cost Center - _TC",
						"description": "Education Cess",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": 2,
						"row_id": 3,
					},
					{
						"account_head": "_Test Account S&H Education Cess - _TC",
						"charge_type": "On Previous Row Amount",
						"cost_center": "_Test Cost Center - _TC",
						"description": "S&H Education Cess",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": 1,
						"row_id": 3,
					},
					{
						"account_head": "_Test Account CST - _TC",
						"charge_type": "On Previous Row Total",
						"cost_center": "_Test Cost Center - _TC",
						"description": "CST",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": 2,
						"row_id": 5,
					},
					{
						"account_head": "_Test Account VAT - _TC",
						"charge_type": "On Net Total",
						"cost_center": "_Test Cost Center - _TC",
						"description": "VAT",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": 12.5,
					},
					{
						"account_head": "_Test Account Discount - _TC",
						"charge_type": "On Previous Row Total",
						"cost_center": "_Test Cost Center - _TC",
						"description": "Discount",
						"doctype": "Sales Taxes and Charges",
						"parentfield": "taxes",
						"rate": -10,
						"row_id": 7,
					},
				],
				"title": "_Test India Tax Master",
			},
			{
				"company": "_Test Company",
				"doctype": "Sales Taxes and Charges Template",
				"taxes": [
					{
						"account_head": "_Test Account VAT - _TC",
						"charge_type": "On Net Total",
						"description": "VAT",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 12,
					},
					{
						"account_head": "_Test Account Service Tax - _TC",
						"charge_type": "On Net Total",
						"description": "Service Tax",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 4,
					},
				],
				"title": "_Test Sales Taxes and Charges Template - Rest of the World",
			},
			{
				"company": "_Test Company",
				"doctype": "Sales Taxes and Charges Template",
				"taxes": [
					{
						"account_head": "_Test Account VAT - _TC",
						"charge_type": "On Net Total",
						"description": "VAT",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 12,
					},
					{
						"account_head": "_Test Account Service Tax - _TC",
						"charge_type": "On Net Total",
						"description": "Service Tax",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 4,
					},
				],
				"title": "_Test Sales Taxes and Charges Template 1",
			},
			{
				"company": "_Test Company",
				"doctype": "Sales Taxes and Charges Template",
				"taxes": [
					{
						"account_head": "_Test Account VAT - _TC",
						"charge_type": "On Net Total",
						"description": "VAT",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 12,
					},
					{
						"account_head": "_Test Account Service Tax - _TC",
						"charge_type": "On Net Total",
						"description": "Service Tax",
						"doctype": "Sales Taxes and Charges",
						"cost_center": "Main - _TC",
						"parentfield": "taxes",
						"rate": 4,
					},
				],
				"title": "_Test Sales Taxes and Charges Template 2",
			},
			{
				"doctype": "Sales Taxes and Charges Template",
				"title": "_Test Tax 1",
				"company": "_Test Company",
				"taxes": [
					{
						"charge_type": "Actual",
						"account_head": "Sales Expenses - _TC",
						"cost_center": "Main - _TC",
						"description": "Test Shopping cart taxes with Tax Rule",
						"tax_amount": 1000,
					}
				],
			},
			{
				"doctype": "Sales Taxes and Charges Template",
				"title": "_Test Tax 2",
				"company": "_Test Company",
				"taxes": [
					{
						"charge_type": "Actual",
						"account_head": "Sales Expenses - _TC",
						"cost_center": "Main - _TC",
						"description": "Test Shopping cart taxes with Tax Rule",
						"tax_amount": 200,
					}
				],
			},
		]
		self.make_records(["title", "company"], records)

	def make_purchase_taxes_template(self):
		records = [
			{
				"company": "_Test Company",
				"doctype": "Purchase Taxes and Charges Template",
				"title": "_Test Purchase Taxes and Charges Template",
				"taxes": [
					{
						"account_head": "_Test Account VAT - _TC",
						"add_deduct_tax": "Add",
						"category": "Total",
						"charge_type": "On Net Total",
						"cost_center": "Main - _TC",
						"description": "VAT",
						"doctype": "Purchase Taxes and Charges",
						"parentfield": "taxes",
						"rate": 6,
					}
				],
			}
		]
		self.make_records(["title", "company"], records)

	def make_item_price(self):
		records = [
			{
				"doctype": "Item Price",
				"item_code": "_Test Item",
				"price_list": "_Test Price List",
				"price_list_rate": 100,
				"valid_from": "2017-04-18",
				"valid_upto": "2017-04-26",
			},
			{
				"doctype": "Item Price",
				"item_code": "_Test Item",
				"price_list": "_Test Price List Rest of the World",
				"price_list_rate": 10,
			},
			{
				"doctype": "Item Price",
				"item_code": "_Test Item 2",
				"price_list": "_Test Price List Rest of the World",
				"price_list_rate": 20,
				"valid_from": "2017-04-18",
				"valid_upto": "2017-04-26",
				"customer": "_Test Customer",
				"uom": "_Test UOM",
			},
			{
				"doctype": "Item Price",
				"item_code": "_Test Item Home Desktop 100",
				"price_list": "_Test Price List",
				"price_list_rate": 1000,
				"valid_from": "2017-04-10",
				"valid_upto": "2017-04-17",
			},
			{
				"doctype": "Item Price",
				"item_code": "_Test Item Home Desktop Manufactured",
				"price_list": "_Test Price List",
				"price_list_rate": 1000,
				"valid_from": "2017-04-10",
				"valid_upto": "2017-04-17",
			},
			{
				"doctype": "Item Price",
				"item_code": "_Test Item",
				"price_list": "_Test Buying Price List",
				"price_list_rate": 100,
				"supplier": "_Test Supplier",
			},
			{
				"doctype": "Item Price",
				"item_code": "_Test Item",
				"price_list": "_Test Selling Price List",
				"price_list_rate": 200,
				"customer": "_Test Customer",
			},
			{
				"doctype": "Item Price",
				"price_list": _("Standard Selling"),
				"item_code": "Loyal Item",
				"price_list_rate": 10000,
			},
			{
				"doctype": "Item Price",
				"item_code": "Consulting",
				"price_list": "Standard Selling",
				"price_list_rate": 10000,
			},
		]
		self.make_records(["item_code", "price_list", "price_list_rate"], records)

	def make_address(self):
		records = [
			{
				"doctype": "Address",
				"address_type": "Billing",
				"address_line1": "Address line 1",
				"address_title": "_Test Billing Address Title",
				"city": "Lagos",
				"country": "Nigeria",
				"links": [
					{"link_doctype": "Customer", "link_name": "_Test Customer 2", "doctype": "Dynamic Link"}
				],
			},
			{
				"doctype": "Address",
				"address_type": "Shipping",
				"address_line1": "Address line 2",
				"address_title": "_Test Shipping Address 1 Title",
				"city": "Lagos",
				"country": "Nigeria",
				"links": [
					{"link_doctype": "Customer", "link_name": "_Test Customer 2", "doctype": "Dynamic Link"}
				],
			},
			{
				"doctype": "Address",
				"address_type": "Shipping",
				"address_line1": "Address line 3",
				"address_title": "_Test Shipping Address 2 Title",
				"city": "Lagos",
				"country": "Nigeria",
				"is_shipping_address": "1",
				"links": [
					{"link_doctype": "Customer", "link_name": "_Test Customer 2", "doctype": "Dynamic Link"}
				],
			},
			{
				"doctype": "Address",
				"address_type": "Billing",
				"address_line1": "Address line 4",
				"address_title": "_Test Billing Address 2 Title",
				"city": "Lagos",
				"country": "Nigeria",
				"is_shipping_address": "1",
				"links": [
					{"link_doctype": "Customer", "link_name": "_Test Customer 1", "doctype": "Dynamic Link"}
				],
			},
			{
				"doctype": "Address",
				"address_title": "_Test Address for Customer",
				"address_type": "Office",
				"address_line1": "Station Road",
				"city": "_Test City",
				"state": "Test State",
				"country": "India",
				"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
			},
		]
		self.make_records(["address_title", "address_type"], records)

	def make_contact(self):
		records = [
			{
				"doctype": "Contact",
				"first_name": "_Test Contact for _Test Customer",
				"email_ids": [{"email_id": "test_contact_customer@example.com", "is_primary": True}],
				"phone_nos": [{"phone": "+91 0000000000", "is_primary_phone": True}],
				"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
			},
			{
				"doctype": "Contact",
				"first_name": "_Test Contact 2 for _Test Customer",
				"email_ids": [{"email_id": "test_contact_two_customer@example.com", "is_primary": True}],
				"phone_nos": [{"phone": "+92 0000000000", "is_primary_phone": True}],
				"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
			},
		]
		self.make_records(["first_name"], records)

	def make_custom_field(self):
		pan_field = {
			"Supplier": [
				{
					"fieldname": "pan",
					"label": "PAN",
					"fieldtype": "Data",
					"translatable": 0,
				}
			]
		}

		create_custom_fields(pan_field, update=1)


BootStrapTestData()


class ERPNextTestSuite(unittest.TestCase):
	@classmethod
	def registerAs(cls, _as):
		def decorator(cm_func):
			setattr(cls, cm_func.__name__, _as(cm_func))
			return cm_func

		return decorator

	@classmethod
	def setUpClass(cls):
		cls.globalTestRecords = {}

	def tearDown(self):
		frappe.db.rollback()
		frappe.local.request_cache.clear()
		# values cached from rolled-back rows, e.g. a party's GL currency
		frappe.local.cache.clear()
		if hasattr(frappe.local, "future_sle"):
			frappe.local.future_sle.clear()

	def load_test_records(self, doctype):
		if doctype not in self.globalTestRecords:
			records = load_test_records_for(doctype)
			self.globalTestRecords[doctype] = records[doctype]

	@contextmanager
	def set_user(self, user: str):
		try:
			old_user = frappe.session.user
			# nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser -- test helper restores the user
			frappe.set_user(user)
			yield
		finally:
			# nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser -- test helper restores the user
			frappe.set_user(old_user)


@ERPNextTestSuite.registerAs(staticmethod)
@contextmanager
def change_settings(doctype, settings_dict=None, /, **settings) -> None:
	"""Temporarily: change settings in a settings doctype."""
	import copy

	if settings_dict is None:
		settings_dict = settings

	settings = frappe.get_doc(doctype)
	previous_settings = copy.deepcopy(settings_dict)
	for key in previous_settings:
		previous_settings[key] = getattr(settings, key)

	for key, value in settings_dict.items():
		setattr(settings, key, value)
	settings.save(ignore_permissions=True)

	yield

	settings = frappe.get_doc(doctype)
	for key, value in previous_settings.items():
		setattr(settings, key, value)
	settings.save(ignore_permissions=True)


def make_email_template(subject: str, response: str) -> str:
	"""Insert a test Email Template and return its name."""
	template = frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": "_Test Email Template",
			"subject": subject,
			"response": response,
		}
	).insert()
	return template.name
