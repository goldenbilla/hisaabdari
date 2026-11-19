# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import cstr, getdate


# nosemgrep
def set_default_settings(args):
	# enable default currency
	frappe.db.set_value("Currency", args.get("currency"), "enabled", 1)

	global_defaults = frappe.get_doc("Global Defaults", "Global Defaults")
	global_defaults.update(
		{
			"current_fiscal_year": get_fy_details(args.get("fy_start_date"), args.get("fy_end_date")),
			"default_currency": args.get("currency"),
			"default_company": args.get("company_name"),
			"country": args.get("country"),
		}
	)

	global_defaults.save()

	system_settings = frappe.get_doc("System Settings")
	system_settings.email_footer_address = args.get("company_name")
	system_settings.save()

	stock_settings = frappe.get_doc("Stock Settings")
	stock_settings.item_naming_by = "Item Code"
	stock_settings.valuation_method = "Moving Average"
	stock_settings.stock_uom = "Nos"
	stock_settings.auto_indent = 1
	stock_settings.auto_insert_price_list_rate_if_missing = 1
	stock_settings.update_price_list_based_on = "Rate"
	stock_settings.save()

	selling_settings = frappe.get_doc("Selling Settings")
	selling_settings.cust_master_name = "Customer Name"
	selling_settings.so_required = "No"
	selling_settings.dn_required = "No"
	selling_settings.allow_multiple_items = 1
	selling_settings.sales_update_frequency = "Daily"
	selling_settings.save()

	buying_settings = frappe.get_doc("Buying Settings")
	buying_settings.supp_master_name = "Supplier Name"
	buying_settings.po_required = "No"
	buying_settings.pr_required = "No"
	buying_settings.maintain_same_rate = 1
	buying_settings.allow_multiple_items = 1
	buying_settings.save()


def create_price_lists(args):
	for pl_type, pl_name in (("Selling", _("Standard Selling")), ("Buying", _("Standard Buying"))):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": pl_name,
				"enabled": 1,
				"buying": 1 if pl_type == "Buying" else 0,
				"selling": 1 if pl_type == "Selling" else 0,
				"currency": args["currency"],
			}
		).insert()


def create_feed_and_todo():
	"""update Activity feed and create todo for creation of item, customer, vendor"""
	return


def get_fy_details(fy_start_date, fy_end_date):
	start_year = getdate(fy_start_date).year
	if start_year == getdate(fy_end_date).year:
		fy = cstr(start_year)
	else:
		fy = cstr(start_year) + "-" + cstr(start_year + 1)
	return fy
