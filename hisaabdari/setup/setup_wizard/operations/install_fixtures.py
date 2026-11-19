# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json
from pathlib import Path

import frappe
from frappe.desk.doctype.global_search_settings.global_search_settings import (
	update_global_search_doctypes,
)
from frappe.desk.page.setup_wizard.setup_wizard import make_records
from frappe.utils import cstr, getdate
from frappe.utils.nestedset import get_root_of

from hisaabdari.accounts.doctype.account.account import RootNotEditable
from hisaabdari.setup.utils import identity as _


def read_lines(filename: str) -> list[str]:
	"""Return a list of lines from a file in the data directory."""
	return (Path(__file__).parent.parent / "data" / filename).read_text().splitlines()


def get_preset_records(country=None):
	root_item_group = get_root_of("Item Group") or _("All Item Groups")
	records = [
		# ensure at least an empty Address Template exists for this Country
		{"doctype": "Address Template", "country": country},
		# item group
		{
			"doctype": "Item Group",
			"item_group_name": root_item_group,
			"is_group": 1,
			"parent_item_group": "",
			"__condition": lambda: not frappe.db.exists("Item Group", root_item_group),
		},
		{
			"doctype": "Item Group",
			"item_group_name": _("Products"),
			"is_group": 0,
			"parent_item_group": root_item_group,
		},
		{
			"doctype": "Item Group",
			"item_group_name": _("Raw Material"),
			"is_group": 0,
			"parent_item_group": root_item_group,
		},
		{
			"doctype": "Item Group",
			"item_group_name": _("Services"),
			"is_group": 0,
			"parent_item_group": root_item_group,
		},
		{
			"doctype": "Item Group",
			"item_group_name": _("Sub Assemblies"),
			"is_group": 0,
			"parent_item_group": root_item_group,
		},
		{
			"doctype": "Item Group",
			"item_group_name": _("Consumable"),
			"is_group": 0,
			"parent_item_group": root_item_group,
		},
		# Stock Entry Type
		{
			"doctype": "Stock Entry Type",
			"name": _("Material Issue"),
			"purpose": "Material Issue",
			"is_standard": 1,
		},
		{
			"doctype": "Stock Entry Type",
			"name": _("Material Receipt"),
			"purpose": "Material Receipt",
			"is_standard": 1,
		},
		{
			"doctype": "Stock Entry Type",
			"name": _("Material Transfer"),
			"purpose": "Material Transfer",
			"is_standard": 1,
		},
		{
			"doctype": "Stock Entry Type",
			"name": _("Repack"),
			"purpose": "Repack",
			"is_standard": 1,
		},
		# customer group
		{
			"doctype": "Customer Group",
			"customer_group_name": _("All Customer Groups"),
			"is_group": 1,
			"name": _("All Customer Groups"),
			"parent_customer_group": "",
		},
		{
			"doctype": "Customer Group",
			"customer_group_name": _("Individual"),
			"is_group": 0,
			"parent_customer_group": _("All Customer Groups"),
		},
		{
			"doctype": "Customer Group",
			"customer_group_name": _("Commercial"),
			"is_group": 0,
			"parent_customer_group": _("All Customer Groups"),
		},
		{
			"doctype": "Customer Group",
			"customer_group_name": _("Non Profit"),
			"is_group": 0,
			"parent_customer_group": _("All Customer Groups"),
		},
		{
			"doctype": "Customer Group",
			"customer_group_name": _("Government"),
			"is_group": 0,
			"parent_customer_group": _("All Customer Groups"),
		},
		# supplier group
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("All Supplier Groups"),
			"is_group": 1,
			"name": _("All Supplier Groups"),
			"parent_supplier_group": "",
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Services"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Local"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Raw Material"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Electrical"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Hardware"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Pharmaceutical"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		{
			"doctype": "Supplier Group",
			"supplier_group_name": _("Distributor"),
			"is_group": 0,
			"parent_supplier_group": _("All Supplier Groups"),
		},
		# Mode of Payment
		{
			"doctype": "Mode of Payment",
			"mode_of_payment": "Check" if country == "United States" else _("Cheque"),
			"type": "Bank",
		},
		{"doctype": "Mode of Payment", "mode_of_payment": _("Cash"), "type": "Cash"},
		{"doctype": "Mode of Payment", "mode_of_payment": _("Credit Card"), "type": "Bank"},
		{"doctype": "Mode of Payment", "mode_of_payment": _("Wire Transfer"), "type": "Bank"},
		{"doctype": "Mode of Payment", "mode_of_payment": _("Bank Draft"), "type": "Bank"},
		{"doctype": "Party Type", "party_type": "Customer", "account_type": "Receivable"},
		{"doctype": "Party Type", "party_type": "Supplier", "account_type": "Payable"},
		{"doctype": "Print Heading", "print_heading": _("Credit Note")},
		{"doctype": "Print Heading", "print_heading": _("Debit Note")},
	]
	return records


def install(country=None):
	records = get_preset_records(country)

	for doctype, title_field, filename in (("UTM Source", "name", "marketing_source.txt"),):
		records += [{"doctype": doctype, title_field: title} for title in read_lines(filename)]

	make_records(records)
	update_selling_defaults()
	update_buying_defaults()
	add_uom_data()
	update_global_search_doctypes()


def update_selling_defaults():
	selling_settings = frappe.get_doc("Selling Settings")
	selling_settings.cust_master_name = "Customer Name"
	selling_settings.so_required = "No"
	selling_settings.dn_required = "No"
	selling_settings.allow_multiple_items = 1
	selling_settings.sales_update_frequency = "Daily"
	selling_settings.save()


def update_buying_defaults():
	buying_settings = frappe.get_doc("Buying Settings")
	buying_settings.supp_master_name = "Supplier Name"
	buying_settings.po_required = "No"
	buying_settings.pr_required = "No"
	buying_settings.maintain_same_rate = 1
	buying_settings.allow_multiple_items = 1
	buying_settings.save()


def add_uom_data():
	# add UOMs
	uoms = json.loads(
		# nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal -- path is inside the app
		open(frappe.get_app_path("hisaabdari", "setup", "setup_wizard", "data", "uom_data.json")).read()
	)
	for d in uoms:
		if not frappe.db.exists("UOM", d.get("uom_name")):
			doc = frappe.new_doc("UOM")
			doc.update(d)
			doc.insert(ignore_permissions=True)


def install_company(args):
	records = [
		# Fiscal Year
		{
			"doctype": "Fiscal Year",
			"year": get_fy_details(args.fy_start_date, args.fy_end_date),
			"year_start_date": args.fy_start_date,
			"year_end_date": args.fy_end_date,
		},
		# Company
		{
			"doctype": "Company",
			"company_name": args.company_name,
			"enable_perpetual_inventory": 1,
			"abbr": args.company_abbr,
			"default_currency": args.currency,
			"country": args.country,
			"create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": args.chart_of_accounts,
		},
	]

	make_records(records)


def install_defaults(args=None):  # nosemgrep
	records = [
		# Price Lists
		{
			"doctype": "Price List",
			"price_list_name": _("Standard Buying"),
			"enabled": 1,
			"buying": 1,
			"selling": 0,
			"currency": args.currency,
		},
		{
			"doctype": "Price List",
			"price_list_name": _("Standard Selling"),
			"enabled": 1,
			"buying": 0,
			"selling": 1,
			"currency": args.currency,
		},
	]

	make_records(records)

	# enable default currency
	frappe.db.set_value("Currency", args.get("currency"), "enabled", 1)
	frappe.db.set_single_value("Stock Settings", "email_footer_address", args.get("company_name"))

	set_global_defaults(args)
	update_stock_settings()

	args.update({"set_default": 1})
	create_bank_account(args)


def set_global_defaults(kwargs):
	global_defaults = frappe.get_doc("Global Defaults", "Global Defaults")
	company = frappe.db.get_value(
		"Company",
		{"company_name": kwargs.get("company_name")},
		"name",
	)

	global_defaults.update(
		{
			"default_currency": kwargs.get("currency"),
			"default_company": company,
			"country": kwargs.get("country"),
		}
	)

	global_defaults.save()


def update_stock_settings():
	stock_settings = frappe.get_doc("Stock Settings")
	stock_settings.item_naming_by = "Item Code"
	stock_settings.valuation_method = "Moving Average"
	stock_settings.stock_uom = "Nos"
	stock_settings.auto_indent = 1
	stock_settings.auto_insert_price_list_rate_if_missing = 1
	stock_settings.update_price_list_based_on = "Rate"
	stock_settings.flags.ignore_permissions = True
	stock_settings.save()


def create_bank_account(args):
	if not args.get("bank_account"):
		return

	company_name = args.get("company_name")
	bank_account_group = frappe.db.get_value(
		"Account",
		{"account_type": "Bank", "is_group": 1, "root_type": "Asset", "company": company_name},
	)
	if bank_account_group:
		bank_account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": args.get("bank_account"),
				"parent_account": bank_account_group,
				"is_group": 0,
				"company": company_name,
				"account_type": "Bank",
			}
		)
		try:
			doc = bank_account.insert()

			if args.get("set_default"):
				frappe.db.set_value(
					"Company",
					args.get("company_name"),
					"default_bank_account",
					bank_account.name,
					update_modified=False,
				)

			return doc

		except RootNotEditable:
			frappe.throw(frappe._("Bank account cannot be named as {0}").format(args.get("bank_account")))
		except frappe.DuplicateEntryError:
			# bank account same as a CoA entry
			pass


def get_fy_details(fy_start_date, fy_end_date):
	start_year = getdate(fy_start_date).year
	if start_year == getdate(fy_end_date).year:
		fy = cstr(start_year)
	else:
		fy = cstr(start_year) + "-" + cstr(start_year + 1)
	return fy
