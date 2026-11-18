# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.model.document import Document
from frappe.query_builder import Order
from frappe.query_builder.functions import Coalesce
from frappe.utils import flt, now
from pypika.terms import ValueWrapper

PROJECTED_QTY_ADDITIONS = ("actual_qty", "ordered_qty", "indented_qty", "planned_qty")
PROJECTED_QTY_DEDUCTIONS = (
	"reserved_qty",
	"reserved_qty_for_production",
	"reserved_qty_for_sub_contract",
	"reserved_qty_for_production_plan",
)
RECALCULATED_FIELDS = ("valuation_rate", "stock_value", *PROJECTED_QTY_ADDITIONS, *PROJECTED_QTY_DEDUCTIONS)


class Bin(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_qty: DF.Float
		company: DF.Link | None
		indented_qty: DF.Float
		item_code: DF.Link
		ordered_qty: DF.Float
		planned_qty: DF.Float
		projected_qty: DF.Float
		reserved_qty: DF.Float
		reserved_qty_for_production: DF.Float
		reserved_qty_for_production_plan: DF.Float
		reserved_qty_for_sub_contract: DF.Float
		reserved_stock: DF.Float
		stock_uom: DF.Link | None
		stock_value: DF.Float
		valuation_rate: DF.Float
		warehouse: DF.Link
	# end: auto-generated types

	@frappe.whitelist(methods=["POST"])
	def recalculate_values(self):
		frappe.has_permission("Repost Item Valuation", "write", throw=True)

		self.reload()
		self.set_stock_values_from_ledger()
		self.set_pending_and_reserved_qty()
		self.set_projected_qty()
		update_bin_columns(
			self.name, {fieldname: flt(self.get(fieldname)) for fieldname in RECALCULATED_FIELDS}
		)

	def set_stock_values_from_ledger(self):
		last_sle = get_last_sle_values(self.item_code, self.warehouse)
		self.actual_qty = last_sle.qty_after_transaction
		self.valuation_rate = last_sle.valuation_rate
		self.stock_value = last_sle.stock_value

	def set_pending_and_reserved_qty(self):
		from hisaabdari.stock.stock_balance import (
			get_ordered_qty,
			get_reserved_qty,
		)

		self.ordered_qty = get_ordered_qty(self.item_code, self.warehouse)
		self.reserved_qty = get_reserved_qty(self.item_code, self.warehouse)

	def before_save(self):
		if self.get("__islocal") or not self.stock_uom:
			self.stock_uom = frappe.get_cached_value("Item", self.item_code, "stock_uom")
		self.set_projected_qty()

	def set_projected_qty(self):
		self.projected_qty = (
			flt(self.actual_qty)
			+ flt(self.ordered_qty)
			+ flt(self.indented_qty)
			+ flt(self.planned_qty)
			- flt(self.reserved_qty)
			- flt(self.reserved_qty_for_production)
			- flt(self.reserved_qty_for_sub_contract)
			- flt(self.reserved_qty_for_production_plan)
		)


def on_doctype_update():
	frappe.db.add_unique("Bin", ["item_code", "warehouse"], constraint_name="unique_item_warehouse")


def get_bin_details(bin_name):
	return frappe.db.get_value(
		"Bin",
		bin_name,
		[
			"actual_qty",
			"ordered_qty",
			"reserved_qty",
			"indented_qty",
			"planned_qty",
			"reserved_qty_for_production",
			"reserved_qty_for_sub_contract",
			"reserved_qty_for_production_plan",
		],
		as_dict=1,
	)


def update_bin_columns(bin_name, values):
	table = frappe.qb.DocType("Bin")
	query = frappe.qb.update(table).set(table.modified, now()).where(table.name == bin_name)

	for fieldname, value in values.items():
		query = query.set(table[fieldname], value)

	query.set(table.projected_qty, get_projected_qty_term(table, values)).run()
	frappe.clear_document_cache("Bin", bin_name)


def get_projected_qty_term(table, values):
	def qty(fieldname):
		return flt(values[fieldname]) if fieldname in values else Coalesce(table[fieldname], 0)

	projected_qty = ValueWrapper(0)
	for fieldname in PROJECTED_QTY_ADDITIONS:
		projected_qty = projected_qty + qty(fieldname)

	for fieldname in PROJECTED_QTY_DEDUCTIONS:
		projected_qty = projected_qty - qty(fieldname)

	return projected_qty


def update_qty(bin_name, args):
	from hisaabdari.controllers.stock_controller import future_sle_exists

	bin_details = get_bin_details(bin_name)
	# actual qty is already updated by processing current voucher
	actual_qty = bin_details.actual_qty or 0.0

	# actual qty is not up to date in case of backdated transactions
	# or when cancellations are the most recent SLE
	if future_sle_exists(args) or args.get("is_cancelled"):
		actual_qty = get_actual_qty(args.get("item_code"), args.get("warehouse"))

	ordered_qty = flt(bin_details.ordered_qty) + flt(args.get("ordered_qty"))
	reserved_qty = flt(bin_details.reserved_qty) + flt(args.get("reserved_qty"))
	indented_qty = flt(bin_details.indented_qty) + flt(args.get("indented_qty"))
	planned_qty = flt(bin_details.planned_qty) + flt(args.get("planned_qty"))

	# compute projected qty
	projected_qty = (
		flt(actual_qty)
		+ flt(ordered_qty)
		+ flt(indented_qty)
		+ flt(planned_qty)
		- flt(reserved_qty)
		- flt(bin_details.reserved_qty_for_production)
		- flt(bin_details.reserved_qty_for_sub_contract)
		- flt(bin_details.reserved_qty_for_production_plan)
	)

	frappe.db.set_value(
		"Bin",
		bin_name,
		{
			"actual_qty": actual_qty,
			"ordered_qty": ordered_qty,
			"reserved_qty": reserved_qty,
			"indented_qty": indented_qty,
			"planned_qty": planned_qty,
			"projected_qty": projected_qty,
		},
		update_modified=True,
	)


def get_actual_qty(item_code, warehouse):
	return get_last_sle_values(item_code, warehouse).qty_after_transaction


def get_last_sle_values(item_code, warehouse):
	sle = frappe.qb.DocType("Stock Ledger Entry")

	last_sle = (
		frappe.qb.from_(sle)
		.select(sle.qty_after_transaction, sle.valuation_rate, sle.stock_value)
		.where((sle.item_code == item_code) & (sle.warehouse == warehouse) & (sle.is_cancelled == 0))
		.orderby(sle.posting_datetime, order=Order.desc)
		.orderby(sle.creation, order=Order.desc)
		.limit(1)
		.run(as_dict=True)
	)

	if last_sle:
		return last_sle[0]

	return frappe._dict(qty_after_transaction=0.0, valuation_rate=0.0, stock_value=0.0)
