# Copyright (c) 2026, HisaabDari contributors
# License: GNU General Public License v3. See license.txt

"""Figures for the custom number cards on the Home workspace."""

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt


def _get_company(filters):
	filters = frappe.parse_json(filters) or {}
	return filters.get("company") or frappe.defaults.get_user_default("Company")


@frappe.whitelist()
def get_cash_and_bank_balance(filters: str | dict | None = None):
	"""Balance of every cash and bank account of the company, in company currency."""
	frappe.has_permission("GL Entry", "read", throw=True)
	company = _get_company(filters)
	if not company:
		return {"value": 0, "fieldtype": "Currency"}

	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
		pluck="name",
	)
	balance = 0
	if accounts:
		gle = frappe.qb.DocType("GL Entry")
		balance = (
			frappe.qb.from_(gle)
			.select(Sum(gle.debit) - Sum(gle.credit))
			.where((gle.company == company) & (gle.is_cancelled == 0) & gle.account.isin(accounts))
		).run()[0][0]

	return {
		"value": flt(balance),
		"fieldtype": "Currency",
		"options": frappe.get_cached_value("Company", company, "default_currency"),
		"route": ["query-report", "Trial Balance"],
	}


@frappe.whitelist()
def get_low_stock_items(filters: str | dict | None = None):
	"""Count of stock items that are out of stock, or below the reorder level set on the item."""
	frappe.has_permission("Bin", "read", throw=True)
	company = _get_company(filters)

	bin = frappe.qb.DocType("Bin")
	item = frappe.qb.DocType("Item")
	warehouse = frappe.qb.DocType("Warehouse")
	reorder = frappe.qb.DocType("Item Reorder")

	query = (
		frappe.qb.from_(bin)
		.join(item)
		.on(item.name == bin.item_code)
		.join(warehouse)
		.on(warehouse.name == bin.warehouse)
		.left_join(reorder)
		.on((reorder.parent == bin.item_code) & (reorder.warehouse == bin.warehouse))
		.select(bin.item_code)
		.distinct()
		.where((item.is_stock_item == 1) & (item.disabled == 0))
		.where((bin.actual_qty <= 0) | (bin.actual_qty < reorder.warehouse_reorder_level))
	)
	if company:
		query = query.where(warehouse.company == company)

	return {
		"value": len(query.run()),
		"fieldtype": "Int",
		"route": ["query-report", "Stock Projected Qty"],
	}
