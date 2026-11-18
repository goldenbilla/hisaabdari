# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json
import math
from collections import defaultdict

import frappe
from frappe import _, bold
from frappe.core.doctype.user_permission.user_permission import get_user_permissions
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.permissions import get_allowed_docs_for_doctype
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import (
	cint,
	comma_or,
	cstr,
	escape_html,
	flt,
	format_time,
	formatdate,
	get_link_to_form,
	getdate,
	nowdate,
)

import hisaabdari
from hisaabdari.accounts.general_ledger import process_gl_map
from hisaabdari.controllers.taxes_and_totals import init_landed_taxes_and_totals
from hisaabdari.setup.doctype.item_group.item_group import get_item_group_defaults
from hisaabdari.stock.doctype.batch.batch import get_batch_qty
from hisaabdari.stock.doctype.stock_reconciliation.stock_reconciliation import (
	OpeningEntryAccountError,
)
from hisaabdari.stock.get_item_details import (
	ItemDetailsCtx,
	_get_bin_details,
	get_barcode_data,
	get_conversion_factor,
	get_default_cost_center,
)
from hisaabdari.stock.serial_batch_bundle import (
	SerialBatchCreation,
	get_serial_or_batch_items,
)
from hisaabdari.stock.stock_ledger import (
	NegativeStockError,
	get_previous_sle,
	get_valuation_rate,
	make_sl_entries,
	run_pending_dimension_checks,
)
from hisaabdari.stock.utils import (
	_get_incoming_rate,
	get_combine_datetime,
	validate_warehouse_company,
)


class FinishedGoodError(frappe.ValidationError):
	pass


class IncorrectValuationRateError(frappe.ValidationError):
	pass


class DuplicateEntryForWorkOrderError(frappe.ValidationError):
	pass


class OperationsNotCompleteError(frappe.ValidationError):
	pass


class MaxSampleAlreadyRetainedError(frappe.ValidationError):
	pass


from hisaabdari.controllers.stock_controller import StockController

form_grid_templates = {"items": "templates/form_grid/stock_entry_grid.html"}


def is_costed_out_of_finished_item(row) -> bool:
	"""Whether the row takes its value out of the finished good instead of adding to it.

	A secondary item that is not linked to a BOM has no cost allocation of its own, so it is
	valued the way the legacy scrap item was: its cost is deducted from the finished good.
	"""
	return bool(
		row.valuation_type in ("Valuation Rate", "Manual")
		or (row.secondary_item_type and not row.bom_secondary_item)
	)


class StockEntry(StockController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from hisaabdari.stock.doctype.landed_cost_taxes_and_charges.landed_cost_taxes_and_charges import (
			LandedCostTaxesandCharges,
		)
		from hisaabdari.stock.doctype.stock_entry_detail.stock_entry_detail import StockEntryDetail

		add_to_transit: DF.Check
		additional_costs: DF.Table[LandedCostTaxesandCharges]
		amended_from: DF.Link | None
		company: DF.Link
		cost_center: DF.Link | None
		credit_note: DF.Link | None
		delivery_note_no: DF.Link | None
		from_warehouse: DF.Link | None
		is_opening: DF.Literal["No", "Yes"]
		is_return: DF.Check
		items: DF.Table[StockEntryDetail]
		letter_head: DF.Link | None
		naming_series: DF.Literal["MAT-STE-.YYYY.-"]
		outgoing_stock_entry: DF.Link | None
		per_transferred: DF.Percent
		posting_date: DF.Date | None
		posting_time: DF.Time | None
		purchase_receipt_no: DF.Link | None
		purpose: DF.Literal[
			"Material Issue",
			"Material Receipt",
			"Material Transfer",
			"Repack",
		]
		remarks: DF.Text | None
		sales_invoice_no: DF.Link | None
		scan_barcode: DF.Data | None
		select_print_heading: DF.Link | None
		set_posting_time: DF.Check
		source_address_display: DF.TextEditor | None
		source_warehouse_address: DF.Link | None
		stock_entry_type: DF.Link
		target_address_display: DF.TextEditor | None
		target_warehouse_address: DF.Link | None
		to_warehouse: DF.Link | None
		total_additional_costs: DF.Currency
		total_amount: DF.Currency
		total_incoming_value: DF.Currency
		total_outgoing_value: DF.Currency
		value_difference: DF.Currency
	# end: auto-generated types

	book_expenses_added_to_stock = True

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.status_updater = []

	def onload(self):
		self.update_items_from_bin_details()

	def before_print(self, settings=None):
		super().before_print(settings)
		self.update_items_from_bin_details()

	def update_items_from_bin_details(self):
		for item in self.get("items"):
			item.update(_get_bin_details(item.item_code, item.s_warehouse or item.t_warehouse))

	def validate(self):
		self.validate_reference_companies()

		self.validate_warehouses_company()
		self.validate_duplicate_serial_and_batch_bundle("items")
		self.validate_posting_time()
		self.validate_purpose()
		self.validate_item()
		self.validate_customer_provided_item()
		self.set_transfer_qty()
		self.validate_warehouse_of_sabb()
		self.validate_company_in_accounting_dimension()

		if self.purpose == "Repack":
			self.mark_finished_and_secondary_items()
			self.set_bomless_secondary_valuation_types()
			self.validate_finished_goods()

		self.validate_warehouse()
		self.validate_warehouses_company()

		self.validate_batch()
		self.validate_uom_is_integer("uom", "qty")
		self.validate_uom_is_integer("stock_uom", "transfer_qty")
		self.validate_difference_account()
		self.set_purpose_for_stock_entry()
		self.clean_serial_nos()
		self.validate_repack_entry()

		self.make_serial_and_batch_bundle_for_outward()
		self.validate_serialized_batch()
		self.calculate_rate_and_amount()
		# Stock Entry overrides validate() without calling super(), so the shared mandatory
		# inventory dimension check must be invoked explicitly here.
		self.validate_inventory_dimension_mandatory()

		self.reset_default_field_value("from_warehouse", "items", "s_warehouse")
		self.reset_default_field_value("to_warehouse", "items", "t_warehouse")

		self.validate_same_source_target_warehouse_during_material_transfer()

		self.validate_raw_materials_exists()

	def validate_reference_companies(self):
		for doctype, names in self.get_referenced_documents().items():
			if other_company_document := frappe.get_all(
				doctype,
				filters={"name": ("in", list(names)), "company": ("!=", self.company)},
				pluck="name",
				limit=1,
			):
				frappe.throw(
					_("{0} {1} does not belong to Company {2}").format(
						_(doctype), other_company_document[0], self.company
					)
				)

	def get_referenced_documents(self):
		references = defaultdict(set)
		for fieldname in ("outgoing_stock_entry",):
			if name := self.get(fieldname):
				references[self.meta.get_options(fieldname)].add(name)

		for row in self.get("items"):
			if row.against_stock_entry:
				references["Stock Entry"].add(row.against_stock_entry)

		return references

	def validate_repack_entry(self):
		if self.purpose != "Repack":
			return

		fg_items = {row.item_code: row for row in self.items if row.is_finished_item}

		if len(fg_items) > 1 and not all(row.set_basic_rate_manually for row in fg_items.values()):
			frappe.throw(
				_(
					"When there are multiple finished goods ({0}) in a Repack stock entry, the basic rate for all finished goods must be set manually. To set rate manually, enable the checkbox 'Set Basic Rate Manually' in the respective finished good row."
				).format(", ".join(fg_items)),
				title=_("Set Basic Rate Manually"),
			)

	def validate_raw_materials_exists(self):
		if self.purpose not in ["Repack"]:
			return

		raw_materials = []
		for row in self.items:
			if row.s_warehouse:
				raw_materials.append(row.item_code)

		if not raw_materials:
			frappe.throw(
				_(
					"At least one raw material item must be present in the stock entry for the type {0}"
				).format(bold(self.purpose)),
				title=_("Raw Materials Missing"),
			)

	def on_submit(self):
		self.make_bundle_using_old_serial_batch_fields()
		self.update_stock_ledger()
		# finished good serial / batch nos exist only after the stock ledger is posted
		set_fg_mapping_on_submit(self)

		self.make_gl_entries()

		self.repost_future_sle_and_gle()
		self.update_transferred_qty()

	def on_cancel(self):
		self.update_stock_ledger()

		self.ignore_linked_doctypes = (
			"GL Entry",
			"Stock Ledger Entry",
			"Repost Item Valuation",
			"Serial and Batch Bundle",
		)

		self.make_gl_entries_on_cancel()
		self.repost_future_sle_and_gle()
		self.update_transferred_qty()
		self.delete_auto_created_batches()
		self.delete_linked_stock_entry()

	def on_update(self):
		super().on_update()
		self.set_serial_and_batch_bundle()

	def validate_purpose(self):
		valid_purposes = [
			"Material Issue",
			"Material Receipt",
			"Material Transfer",
			"Repack",
		]

		if self.purpose not in valid_purposes:
			frappe.throw(_("Purpose must be one of {0}").format(comma_or(valid_purposes)))

	def delete_linked_stock_entry(self):
		if self.purpose == "Send to Warehouse":
			for d in frappe.get_all(
				"Stock Entry",
				filters={
					"docstatus": 0,
					"outgoing_stock_entry": self.name,
					"purpose": "Receive at Warehouse",
				},
			):
				frappe.delete_doc("Stock Entry", d.name)

	def set_transfer_qty(self):
		self.validate_qty_is_not_zero()
		for item in self.get("items"):
			if not flt(item.conversion_factor):
				frappe.throw(_("Row {0}: UOM Conversion Factor is mandatory").format(item.idx))
			item.transfer_qty = flt(
				flt(item.qty) * flt(item.conversion_factor), self.precision("transfer_qty", item)
			)
			if not flt(item.transfer_qty):
				frappe.throw(
					_("Row {0}: Qty in Stock UOM can not be zero.").format(item.idx), title=_("Zero quantity")
				)

	def validate_item(self):
		stock_items = self.get_stock_items()
		for item in self.get("items"):
			if flt(item.qty) and flt(item.qty) < 0:
				frappe.throw(
					_("Row {0}: The item {1}, quantity must be positive number").format(
						item.idx, frappe.bold(item.item_code)
					)
				)

			if item.item_code not in stock_items:
				frappe.throw(_("{0} is not a stock Item").format(item.item_code))

			item_details = self.get_item_details(
				frappe._dict(
					{
						"item_code": item.item_code,
						"company": self.company,
						"uom": item.uom,
						"s_warehouse": item.s_warehouse,
						"is_finished_item": item.is_finished_item,
					}
				),
				for_update=True,
			)

			reset_fields = ("stock_uom", "item_name")
			for field in reset_fields:
				item.set(field, item_details.get(field))

			update_fields = (
				"uom",
				"description",
				"expense_account",
				"cost_center",
				"conversion_factor",
				"barcode",
			)

			for field in update_fields:
				if not item.get(field):
					item.set(field, item_details.get(field))
				if field == "conversion_factor" and item.uom == item_details.get("stock_uom"):
					item.set(field, item_details.get(field))

			if not item.transfer_qty and item.qty:
				item.transfer_qty = flt(
					flt(item.qty) * flt(item.conversion_factor), self.precision("transfer_qty", item)
				)

	def validate_difference_account(self):
		if not cint(hisaabdari.is_perpetual_inventory_enabled(self.company)):
			return

		for d in self.get("items"):
			if not d.expense_account:
				frappe.throw(
					_(
						"Please enter <b>Difference Account</b> or set default <b>Stock Adjustment Account</b> for company {0}"
					).format(frappe.bold(self.company))
				)

			acc_details = frappe.get_cached_value(
				"Account",
				d.expense_account,
				["account_type", "report_type"],
				as_dict=True,
			)

			if self.is_opening == "Yes" and acc_details.report_type == "Profit and Loss":
				frappe.throw(
					_(
						"Difference Account must be a Asset/Liability type account (Temporary Opening), since this Stock Entry is an Opening Entry"
					),
					OpeningEntryAccountError,
				)

			if acc_details.account_type == "Stock":
				frappe.throw(
					_(
						"At row #{0}: the Difference Account must not be a Stock type account, please change the Account Type for the account {1} or select a different account"
					).format(d.idx, get_link_to_form("Account", d.expense_account)),
					title=_("Difference Account in Items Table"),
				)

			if (
				self.purpose not in ["Material Issue"]
				and acc_details.account_type == "Cost of Goods Sold"
			):
				frappe.msgprint(
					_(
						"At row #{0}: you have selected the Difference Account {1}, which is a Cost of Goods Sold type account. Please select a different account"
					).format(d.idx, bold(get_link_to_form("Account", d.expense_account))),
					title=_("Cost of Goods Sold Account in Items Table"),
					indicator="orange",
					alert=1,
				)

	def validate_warehouse(self):
		"""perform various (sometimes conditional) validations on warehouse"""

		source_mandatory = [
			"Material Issue",
			"Material Transfer",
		]

		target_mandatory = [
			"Material Receipt",
			"Material Transfer",
		]

		if self.purpose in source_mandatory and self.purpose not in target_mandatory:
			self.to_warehouse = None
			for d in self.get("items"):
				d.t_warehouse = None
		elif self.purpose in target_mandatory and self.purpose not in source_mandatory:
			self.from_warehouse = None
			for d in self.get("items"):
				d.s_warehouse = None

		for d in self.get("items"):
			if not d.s_warehouse and not d.t_warehouse:
				d.s_warehouse = self.from_warehouse
				d.t_warehouse = self.to_warehouse

			if self.purpose in source_mandatory and not d.s_warehouse:
				if self.from_warehouse:
					d.s_warehouse = self.from_warehouse
				else:
					frappe.throw(_("Source warehouse is mandatory for row {0}").format(d.idx))

			if self.purpose in target_mandatory and not d.t_warehouse:
				if self.to_warehouse:
					d.t_warehouse = self.to_warehouse
				else:
					frappe.throw(_("Target warehouse is mandatory for row {0}").format(d.idx))

			if self.purpose in ["Repack"]:
				if d.is_finished_item or d.secondary_item_type or d.valuation_type:
					d.s_warehouse = None
					if not d.t_warehouse:
						frappe.throw(_("Target warehouse is mandatory for row {0}").format(d.idx))
				else:
					d.t_warehouse = None
					if not d.s_warehouse:
						frappe.throw(_("Source warehouse is mandatory for row {0}").format(d.idx))

			if cstr(d.s_warehouse) == cstr(d.t_warehouse) and self.purpose not in [
				"Material Transfer",
			]:
				frappe.throw(_("Source and target warehouse cannot be same for row {0}").format(d.idx))

			if not (d.s_warehouse or d.t_warehouse):
				frappe.throw(_("At least one warehouse is mandatory"))

		self.validate_stock_in_rows()

	def validate_stock_in_rows(self):
		rows = [item for item in self.items if item.against_stock_entry and item.ste_detail]
		if not rows:
			return

		outward_rows = get_outward_rows([item.ste_detail for item in rows])
		for item in rows:
			outward_row = outward_rows.get(item.ste_detail)
			if not outward_row:
				continue

			if item.item_code != outward_row.item_code:
				frappe.throw(
					_("Row #{0}: Item {1} does not match item {2} sent by {3}.").format(
						item.idx,
						frappe.bold(item.item_code),
						frappe.bold(outward_row.item_code),
						item.against_stock_entry,
					)
				)

			if item.s_warehouse != outward_row.t_warehouse:
				frappe.throw(
					_("Row #{0}: Item {1} must be taken from {2}, where {3} sent it.").format(
						item.idx,
						frappe.bold(item.item_code),
						frappe.bold(outward_row.t_warehouse),
						item.against_stock_entry,
					)
				)

	def validate_warehouses_company(self):
		warehouses = {d.s_warehouse for d in self.get("items")} | {d.t_warehouse for d in self.get("items")}
		for warehouse in warehouses - {None, ""}:
			validate_warehouse_company(warehouse, self.company)

	def set_actual_qty(self):
		from hisaabdari.stock.stock_ledger import is_negative_stock_allowed

		self.validate_warehouses_company()
		for d in self.get("items"):
			allow_negative_stock = is_negative_stock_allowed(item_code=d.item_code)
			previous_sle = get_previous_sle(
				{
					"item_code": d.item_code,
					"warehouse": d.s_warehouse or d.t_warehouse,
					"posting_date": self.posting_date,
					"posting_time": self.posting_time,
				}
			)

			# get actual stock at source warehouse
			d.actual_qty = previous_sle.get("qty_after_transaction") or 0

			# validate qty during submit
			if (
				d.docstatus == 1
				and d.s_warehouse
				and not allow_negative_stock
				and flt(d.actual_qty, d.precision("actual_qty"))
				< flt(d.transfer_qty, d.precision("actual_qty"))
			):
				frappe.throw(
					_(
						"Row {0}: Quantity not available for {4} in warehouse {1} at posting time of the entry ({2} {3})"
					).format(
						d.idx,
						frappe.bold(d.s_warehouse),
						formatdate(self.posting_date),
						format_time(self.posting_time),
						frappe.bold(d.item_code),
					)
					+ "<br><br>"
					+ _("Available quantity is {0}, you need {1}").format(
						frappe.bold(flt(d.actual_qty, d.precision("actual_qty"))), frappe.bold(d.transfer_qty)
					),
					NegativeStockError,
					title=_("Insufficient Stock"),
				)

	def validate_same_source_target_warehouse_during_material_transfer(self):
		"""
		Validate Material Transfer entries where source and target warehouses are identical.

		For Material Transfer purpose, if an item has the same source and target warehouse,
		require that at least one inventory dimension (if configured) differs between source
		and target to ensure a meaningful transfer is occurring.

		Raises:
		frappe.ValidationError: If warehouses are same and no inventory dimensions differ
		"""

		if frappe.get_single_value("Stock Settings", "validate_material_transfer_warehouses"):
			from hisaabdari.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions

			inventory_dimensions = get_inventory_dimensions()
			if self.purpose == "Material Transfer":
				for item in self.items:
					if cstr(item.s_warehouse) == cstr(item.t_warehouse):
						if not inventory_dimensions:
							frappe.throw(
								_(
									"Row #{0}: Source and Target Warehouse cannot be the same for Material Transfer"
								).format(item.idx),
								title=_("Invalid Source and Target Warehouse"),
							)
						else:
							difference_found = False
							for dimension in inventory_dimensions:
								fieldname = (
									dimension.source_fieldname
									if dimension.source_fieldname.startswith("to_")
									else f"to_{dimension.source_fieldname}"
								)
								if (
									item.get(dimension.source_fieldname)
									and item.get(fieldname)
									and item.get(dimension.source_fieldname) != item.get(fieldname)
								):
									difference_found = True
									break
							if not difference_found:
								frappe.throw(
									_(
										"Row #{0}: Source, Target Warehouse and Inventory Dimensions cannot be the exact same for Material Transfer"
									).format(item.idx),
									title=_("Invalid Source and Target Warehouse"),
								)

	@frappe.whitelist()
	def get_stock_and_rate(self):
		"""
		Updates rate and availability of all the items.
		Called from Update Rate and Availability button.
		"""
		self.set_transfer_qty()
		self.set_actual_qty()
		self.calculate_rate_and_amount()

	def calculate_rate_and_amount(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		self.set_basic_rate(reset_outgoing_rate, raise_error_if_no_rate)
		init_landed_taxes_and_totals(self)
		self.distribute_additional_costs()
		self.update_valuation_rate()
		self.set_total_incoming_outgoing_value()
		self.set_total_amount()

	def set_basic_rate(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		"""
		Set rate for outgoing, secondary and finished items
		"""
		# Set rate for outgoing items
		outgoing_items_cost = self.set_rate_for_outgoing_items(reset_outgoing_rate, raise_error_if_no_rate)

		items = []
		# Set basic rate for incoming items
		# Own-cost rows first: their value is deducted from the basis the percentage
		# allocated rows and the finished good split, so it must be known before those.
		finished_items_last = sorted(
			self.get("items"),
			key=lambda row: (cint(row.is_finished_item), cint(not is_costed_out_of_finished_item(row))),
		)
		for d in finished_items_last:
			if d.s_warehouse or d.set_basic_rate_manually:
				if d.set_basic_rate_manually:
					d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))
				continue

			# Zero-qty secondary items carry no inventory value; skip rate calculation
			if d.secondary_item_type and flt(d.transfer_qty) == 0:
				d.basic_rate = 0.0
				d.basic_amount = 0.0
				continue

			has_derived_rate = False

			# a zero valued finished good takes no share of the cost, even before it has a rate
			if d.allow_zero_valuation_rate and (d.basic_rate or d.is_finished_item):
				if d.basic_rate:
					items.append(d.item_code)
				d.basic_rate = 0.0
			elif d.is_finished_item:
				if self.purpose == "Repack":
					d.basic_rate = self.get_basic_rate_for_repacked_items(
						self.get_finished_items_qty(), outgoing_items_cost
					)
					# Repack rate comes from consumed source-warehouse rows, not consumption entries
					has_derived_rate = any(item.s_warehouse for item in self.get("items"))
			elif is_costed_out_of_finished_item(d):
				# Recomputed every time: a rate fetched before the target warehouse was set
				# must not stick to the row.
				d.basic_rate = self.get_row_valuation_rate(d, raise_error_if_no_rate)
				has_derived_rate = True

			# A rate of zero that was derived rather than left unset is a real cost. Falling back to
			# the item's valuation here would value free inputs, or an unallocated row, as output.
			if not d.basic_rate and not d.allow_zero_valuation_rate and not has_derived_rate:
				if self.is_new():
					raise_error_if_no_rate = False

				d.basic_rate = self.get_row_valuation_rate(d, raise_error_if_no_rate)

			# do not round off basic rate to avoid precision loss
			d.basic_rate = flt(d.basic_rate)
			d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))

		if items:
			message = ""

			if len(items) > 1:
				message = _(
					"Items rate has been updated to zero as Allow Zero Valuation Rate is checked for the following items: {0}"
				).format(", ".join(frappe.bold(item) for item in items))
			else:
				message = _(
					"Item rate has been updated to zero as Allow Zero Valuation Rate is checked for item {0}"
				).format(frappe.bold(items[0]))

			frappe.msgprint(message, alert=True)

	def get_row_valuation_rate(self, d, raise_error_if_no_rate):
		return get_valuation_rate(
			d.item_code,
			d.t_warehouse,
			self.doctype,
			self.name,
			d.allow_zero_valuation_rate,
			currency=hisaabdari.get_company_currency(self.company),
			company=self.company,
			raise_error_if_no_rate=raise_error_if_no_rate,
			batch_no=d.batch_no,
			serial_and_batch_bundle=d.serial_and_batch_bundle,
			posting_datetime=get_combine_datetime(self.posting_date, self.posting_time),
			creation=self.first_sle_creation,
		)

	@property
	def first_sle_creation(self):
		"""Creation of this entry's earliest ledger entry, if it has posted any yet."""
		return frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": self.name, "voucher_type": self.doctype, "is_cancelled": 0},
			"creation",
			order_by="creation asc",
		)

	def set_rate_for_outgoing_items(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		outgoing_items_cost = 0.0
		for d in self.get("items"):
			if d.s_warehouse:
				if reset_outgoing_rate:
					args = self.get_args_for_incoming_rate(d)
					rate = _get_incoming_rate(args, raise_error_if_no_rate)
					if rate >= 0:
						d.basic_rate = rate

				d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))
				if not d.t_warehouse:
					outgoing_items_cost += flt(d.basic_amount)

		return outgoing_items_cost

	def get_args_for_incoming_rate(self, item):
		return frappe._dict(
			{
				"item_code": item.item_code,
				"warehouse": item.s_warehouse or item.t_warehouse,
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"qty": item.s_warehouse and -1 * flt(item.transfer_qty) or flt(item.transfer_qty),
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"company": self.company,
				"allow_zero_valuation": item.allow_zero_valuation_rate,
				"serial_and_batch_bundle": item.serial_and_batch_bundle,
				"voucher_detail_no": item.name,
				"batch_no": item.batch_no,
				"serial_no": item.serial_no,
			}
		)

	def get_finished_items_qty(self) -> float:
		"""Qty of the received finished good rows whose rate is derived from the consumed cost.
		Manual and zero valued rows take no share, so the others carry the whole cost."""
		return sum(
			flt(d.transfer_qty)
			for d in self.get("items")
			if d.is_finished_item
			and d.t_warehouse
			and not d.s_warehouse
			and not d.set_basic_rate_manually
			and not d.allow_zero_valuation_rate
		)

	def has_manually_rated_finished_items(self) -> bool:
		"""Whether hand rated finished goods took part of the cost, so a zero left for the rest is real."""
		return self.get_manually_rated_finished_items()[1] > 0

	def get_manually_rated_finished_items(self) -> tuple[float, float]:
		"""Qty and value of the received finished good rows whose rate was set by hand."""
		rows = [
			d
			for d in self.get("items")
			if d.is_finished_item and d.t_warehouse and not d.s_warehouse and d.set_basic_rate_manually
		]
		return (
			sum(flt(d.transfer_qty) for d in rows),
			sum(flt(d.transfer_qty) * flt(d.basic_rate) for d in rows),
		)

	def get_basic_rate_for_repacked_items(self, finished_item_qty, outgoing_items_cost):
		manual_cost = self.get_manually_rated_finished_items()[1]
		cost_left = outgoing_items_cost - self.get_costed_out_items_cost() - manual_cost
		if self.flags.via_repost:
			cost_left = max(cost_left, 0)

		return flt(cost_left / finished_item_qty) if finished_item_qty else 0.0

	def set_bomless_secondary_valuation_types(self):
		"""Secondary rows without a BOM link choose their own costing: valuation rate or manual.

		There is no percentage to allocate without a BOM row, so % of Component Cost is rejected."""
		for d in self.get("items"):
			if d.bom_secondary_item:
				continue

			if not d.secondary_item_type:
				if d.valuation_type:
					d.valuation_type = ""
					d.set_basic_rate_manually = 0
				continue

			if d.valuation_type == "% of Component Cost":
				frappe.throw(
					_(
						"Row #{0}: % of Component Cost needs a BOM secondary item. Choose Valuation Rate or Manual for {1}."
					).format(d.idx, frappe.bold(d.item_code))
				)

			if not d.valuation_type:
				d.valuation_type = "Valuation Rate"

			d.set_basic_rate_manually = cint(d.valuation_type == "Manual")

	def get_costed_out_items_cost(self) -> float:
		"""Total value of the rows that are deducted from the cost the other incoming rows split."""
		return sum(flt(d.basic_amount) for d in self.get("items") if is_costed_out_of_finished_item(d))

	def distribute_additional_costs(self):
		# If no incoming items, set additional costs blank
		if not any(d.item_code for d in self.items if d.t_warehouse):
			self.additional_costs = []

		self.total_additional_costs = sum(flt(t.base_amount) for t in self.get("additional_costs"))

		incoming_items, basis, total_basis = self.get_additional_cost_allocation()

		for d in self.get("items"):
			d.additional_cost = 0

		if not total_basis:
			return

		for d in incoming_items:
			d.additional_cost = (flt(d.get(basis)) / total_basis) * self.total_additional_costs

	def get_additional_cost_allocation(self):
		if self.purpose in ("Repack",):
			incoming_items = [d for d in self.get("items") if d.is_finished_item]
		else:
			incoming_items = [d for d in self.get("items") if d.t_warehouse]

		total_basic_amount = sum(flt(d.basic_amount) for d in incoming_items)
		if total_basic_amount:
			return incoming_items, "basic_amount", total_basic_amount

		return incoming_items, "transfer_qty", sum(flt(d.transfer_qty) for d in incoming_items)

	def update_valuation_rate(self, reset_outgoing_rate=True):
		for d in self.get("items"):
			if not reset_outgoing_rate and d.s_warehouse:
				continue

			if d.transfer_qty:
				d.amount = flt(
					flt(flt(d.basic_amount) + flt(d.additional_cost) + flt(d.landed_cost_voucher_amount)),
					d.precision("amount"),
				)
				# Do not round off valuation rate to avoid precision loss
				d.valuation_rate = flt(d.basic_rate) + (
					flt(flt(d.additional_cost) + flt(d.landed_cost_voucher_amount)) / flt(d.transfer_qty)
				)

	def set_total_incoming_outgoing_value(self):
		self.total_incoming_value = self.total_outgoing_value = 0.0
		for d in self.get("items"):
			if d.t_warehouse:
				self.total_incoming_value += flt(d.amount)
			if d.s_warehouse:
				self.total_outgoing_value += flt(d.amount)

		self.value_difference = self.total_incoming_value - self.total_outgoing_value

	def set_total_amount(self):
		self.total_amount = None
		if self.purpose not in ["Repack"]:
			self.total_amount = sum([flt(item.amount) for item in self.get("items")])

	def set_stock_entry_type(self):
		if self.purpose:
			self.stock_entry_type = frappe.get_cached_value(
				"Stock Entry Type", {"purpose": self.purpose, "is_standard": 1}, "name"
			)

	def set_purpose_for_stock_entry(self):
		if self.stock_entry_type and not self.purpose:
			self.purpose = frappe.get_cached_value("Stock Entry Type", self.stock_entry_type, "purpose")

	def make_serial_and_batch_bundle_for_outward(self):
		serial_or_batch_items = get_serial_or_batch_items(self.items)
		if not serial_or_batch_items:
			return

		serial_nos, batch_nos = frappe._dict(), frappe._dict()

		if self.docstatus == 0:
			return

		already_picked_serial_nos = []
		already_picked_batches = frappe._dict()

		for row in self.items:
			if row.use_serial_batch_fields:
				continue

			if not row.s_warehouse:
				continue

			if row.item_code not in serial_or_batch_items:
				continue

			bundle_doc = None
			if row.serial_and_batch_bundle and abs(row.transfer_qty) != abs(
				frappe.get_cached_value("Serial and Batch Bundle", row.serial_and_batch_bundle, "total_qty")
			):
				bundle_doc = SerialBatchCreation(
					{
						"item_code": row.item_code,
						"warehouse": row.s_warehouse,
						"serial_and_batch_bundle": row.serial_and_batch_bundle,
						"type_of_transaction": "Outward",
						"ignore_serial_nos": already_picked_serial_nos,
						"already_picked_batches": already_picked_batches,
						"qty": row.transfer_qty * -1,
					}
				).update_serial_and_batch_entries(
					serial_nos=serial_nos.get(row.name), batch_nos=batch_nos.get(row.name)
				)
			elif not row.serial_and_batch_bundle and frappe.get_single_value(
				"Stock Settings", "auto_create_serial_and_batch_bundle_for_outward"
			):
				bundle_doc = SerialBatchCreation(
					{
						"item_code": row.item_code,
						"warehouse": row.s_warehouse,
						"posting_datetime": get_combine_datetime(self.posting_date, self.posting_time),
						"voucher_type": self.doctype,
						"voucher_detail_no": row.name,
						"qty": row.transfer_qty * -1,
						"ignore_serial_nos": already_picked_serial_nos,
						"already_picked_batches": already_picked_batches,
						"type_of_transaction": "Outward",
						"company": self.company,
						"do_not_submit": True,
					}
				).make_serial_and_batch_bundle(
					serial_nos=serial_nos.get(row.name), batch_nos=batch_nos.get(row.name)
				)

			if not bundle_doc:
				continue

			for entry in bundle_doc.entries:
				if entry.serial_no:
					already_picked_serial_nos.append(entry.serial_no)
				if entry.batch_no:
					key = (entry.batch_no, bundle_doc.warehouse)
					picked = already_picked_batches.setdefault(
						key, frappe._dict(batch_no=entry.batch_no, warehouse=bundle_doc.warehouse, qty=0)
					)
					picked.qty += entry.qty

			row.serial_and_batch_bundle = bundle_doc.name

	def mark_finished_and_secondary_items(self):
		for d in self.items:
			if d.t_warehouse and not d.s_warehouse:
				if d.secondary_item_type or d.valuation_type:
					d.is_finished_item = 0
				elif self.purpose == "Repack":
					d.is_finished_item = 1
			else:
				d.is_finished_item = 0
				d.secondary_item_type = ""

	def validate_finished_goods(self):
		"""
		1. Check if FG exists (mfg, repack)
		2. Check if Multiple FG Items are present (mfg)
		3. Check FG Item and Qty against WO if present (mfg)
		"""
		finished_items = []

		for d in self.get("items"):
			if d.is_finished_item:
				finished_items.append(d.item_code)

		if not finished_items:
			frappe.throw(
				msg=_("There must be atleast 1 Finished Good in this Stock Entry").format(self.name),
				title=_("Missing Finished Good"),
				exc=FinishedGoodError,
			)

	def update_stock_ledger(self, allow_negative_stock=False, via_landed_cost_voucher=False):
		"""On submit, post the source legs, recalculate once for bundles picked while posting them,
		then post the target legs. Only the second call updates batch qty, for the whole voucher."""
		source_entries, target_entries = [], []
		finished_item_row = self.get_finished_item_row()
		self.get_sle_for_source_warehouse(source_entries, finished_item_row)
		self.get_sle_for_target_warehouse(target_entries, finished_item_row)

		if self.docstatus == 2:
			self.make_sl_entries(
				(source_entries + target_entries)[::-1],
				allow_negative_stock=allow_negative_stock,
				via_landed_cost_voucher=via_landed_cost_voucher,
			)
			return

		make_sl_entries(
			source_entries, allow_negative_stock, via_landed_cost_voucher, defer_dimension_checks=True
		)
		if self.recalculate_for_bundles_picked_while_posting():
			valuation_rates = {d.name: flt(d.valuation_rate) for d in self.items}
			for sle in target_entries:
				sle.incoming_rate = valuation_rates[sle.voucher_detail_no]

		self.make_sl_entries(
			target_entries,
			allow_negative_stock=allow_negative_stock,
			via_landed_cost_voucher=via_landed_cost_voucher,
		)
		run_pending_dimension_checks(self.doctype, self.name)

	def recalculate_for_bundles_picked_while_posting(self) -> bool:
		"""Reload first: posting wrote the picked bundles and their outgoing rates to the rows."""
		if not frappe.db.exists(
			"Stock Ledger Entry",
			{
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"actual_qty": ("<", 0),
				"auto_created_serial_and_batch_bundle": 1,
				"is_cancelled": 0,
			},
		):
			return False

		self.reload()
		self.calculate_rate_and_amount(reset_outgoing_rate=False, raise_error_if_no_rate=False)
		self.db_update_all()
		return True

	def get_finished_item_row(self):
		finished_item_row = None
		if self.purpose in ("Repack",):
			for d in self.get("items"):
				if d.is_finished_item:
					finished_item_row = d

		return finished_item_row

	def validate_serial_batch_bundle_type(self, serial_and_batch_bundle):
		if (
			frappe.db.get_value("Serial and Batch Bundle", serial_and_batch_bundle, "type_of_transaction")
			!= "Outward"
		):
			frappe.throw(
				_(
					"The Serial and Batch Bundle {0} is not valid for this transaction. The 'Type of Transaction' should be 'Outward' instead of 'Inward' in Serial and Batch Bundle {0}"
				).format(get_link_to_form("Serial and Batch Bundle", serial_and_batch_bundle)),
				title=_("Invalid Serial and Batch Bundle"),
			)

	def get_sle_for_source_warehouse(self, sl_entries, finished_item_row):
		for d in self.get("items"):
			if cstr(d.s_warehouse):
				if d.serial_and_batch_bundle and self.docstatus == 1:
					self.validate_serial_batch_bundle_type(d.serial_and_batch_bundle)

				sle = self.get_sl_entries(
					d,
					{
						"warehouse": cstr(d.s_warehouse),
						"actual_qty": -flt(d.transfer_qty),
						"incoming_rate": 0,
					},
				)
				if cstr(d.t_warehouse):
					sle.dependant_sle_voucher_detail_no = d.name
				elif finished_item_row and (
					finished_item_row.item_code != d.item_code
					or finished_item_row.t_warehouse != d.s_warehouse
				):
					sle.dependant_sle_voucher_detail_no = finished_item_row.name

				if sle.serial_and_batch_bundle and self.docstatus == 2:
					bundle_id = frappe.get_cached_value(
						"Serial and Batch Bundle",
						{
							"voucher_detail_no": d.name,
							"voucher_no": self.name,
							"is_cancelled": 0,
							"type_of_transaction": "Outward",
						},
						"name",
					)

					if bundle_id:
						sle.serial_and_batch_bundle = bundle_id

				sl_entries.append(sle)

	def make_serial_and_batch_bundle_for_transfer(self):
		ids = frappe._dict(
			frappe.get_all(
				"Stock Entry Detail",
				fields=["name", "serial_and_batch_bundle"],
				filters={"parent": self.outgoing_stock_entry, "serial_and_batch_bundle": ("is", "set")},
				as_list=1,
			)
		)

		if not ids:
			return

		for d in self.get("items"):
			serial_and_batch_bundle = ids.get(d.ste_detail)
			if not serial_and_batch_bundle:
				continue

			d.serial_and_batch_bundle = self.make_package_for_transfer(
				serial_and_batch_bundle, d.s_warehouse, "Outward", do_not_submit=True
			)

	def get_sle_for_target_warehouse(self, sl_entries, finished_item_row):
		for d in self.get("items"):
			if cstr(d.t_warehouse):
				sle = self.get_sl_entries(
					d,
					{
						"warehouse": cstr(d.t_warehouse),
						"actual_qty": flt(d.transfer_qty),
						"incoming_rate": flt(d.valuation_rate),
					},
				)

				# every finished good row takes its rate from the consumed cost, not only the last one
				if cstr(d.s_warehouse) or (finished_item_row and d.is_finished_item):
					sle.recalculate_rate = 1

				allowed_types = [
					"Material Transfer",
				]

				if self.purpose in allowed_types and d.serial_and_batch_bundle and self.docstatus == 1:
					sle.serial_and_batch_bundle = self.make_package_for_transfer(
						d.serial_and_batch_bundle, d.t_warehouse
					)

				if sle.serial_and_batch_bundle and self.docstatus == 2:
					bundle_id = frappe.get_cached_value(
						"Serial and Batch Bundle",
						{
							"voucher_detail_no": d.name,
							"voucher_no": self.name,
							"is_cancelled": 0,
							"type_of_transaction": "Inward",
						},
						"name",
					)

					if sle.serial_and_batch_bundle != bundle_id:
						sle.serial_and_batch_bundle = bundle_id

				sl_entries.append(sle)

	def get_gl_entries(self, inventory_account_map):
		gl_entries = super().get_gl_entries(inventory_account_map)

		incoming_items, basis, divide_based_on = self.get_additional_cost_allocation()

		item_account_wise_additional_cost = {}

		for t in self.get("additional_costs"):
			if not divide_based_on:
				continue
			for d in incoming_items:
				item_account_wise_additional_cost.setdefault((d.item_code, d.name), {})
				item_account_wise_additional_cost[(d.item_code, d.name)].setdefault(
					t.expense_account, {"amount": 0.0, "base_amount": 0.0}
				)

				multiply_based_on = flt(d.get(basis))

				item_account_wise_additional_cost[(d.item_code, d.name)][t.expense_account]["amount"] += (
					flt(t.amount * multiply_based_on) / divide_based_on
				)

				item_account_wise_additional_cost[(d.item_code, d.name)][t.expense_account][
					"base_amount"
				] += flt(t.base_amount * multiply_based_on) / divide_based_on

		if item_account_wise_additional_cost:
			precision = self.get_debit_field_precision()

			for d in self.get("items"):
				for account, amount in item_account_wise_additional_cost.get(
					(d.item_code, d.name), {}
				).items():
					if not amount:
						continue

					amount["amount"] = flt(amount["amount"], precision)
					amount["base_amount"] = flt(amount["base_amount"], precision)

					gl_entries.append(
						self.get_gl_dict(
							{
								"account": account,
								"against": d.expense_account,
								"cost_center": d.cost_center,
								"remarks": self.get("remarks") or _("Accounting Entry for Stock"),
								"credit_in_account_currency": flt(amount["amount"]),
								"credit": flt(amount["base_amount"]),
							},
							item=d,
						)
					)

					gl_entries.append(
						self.get_gl_dict(
							{
								"account": d.expense_account,
								"against": account,
								"cost_center": d.cost_center,
								"remarks": self.get("remarks") or _("Accounting Entry for Stock"),
								"credit": -1
								* amount[
									"base_amount"
								],  # put it as negative credit instead of debit purposefully
							},
							item=d,
						)
					)

		return process_gl_map(gl_entries, from_repost=frappe.flags.through_repost_item_valuation)

	@frappe.whitelist()
	def get_item_details(self, args: ItemDetailsCtx = None, for_update: bool = False):
		item = frappe.qb.DocType("Item")
		item_default = frappe.qb.DocType("Item Default")

		query = (
			frappe.qb.from_(item)
			.left_join(item_default)
			.on((item.name == item_default.parent) & (item_default.company == self.company))
			.select(
				item.name,
				item.stock_uom,
				item.description,
				item.image,
				item.item_name,
				item.item_group,
				item.has_batch_no,
				item.sample_quantity,
				item.has_serial_no,
				item_default.expense_account,
				item_default.buying_cost_center,
			)
			.where(
				(item.name == args.get("item_code"))
				& (item.disabled == 0)
				& (
					(item.end_of_life.isnull())
					| (item.end_of_life < "1900-01-01")
					| (item.end_of_life > nowdate())
				)
			)
		)
		item = query.run(as_dict=True)

		if not item:
			frappe.throw(
				_("Item {0} is not active or end of life has been reached").format(args.get("item_code"))
			)

		item = item[0]
		item_group_defaults = get_item_group_defaults(item.name, self.company)

		ret = frappe._dict(
			{
				"uom": item.stock_uom,
				"stock_uom": item.stock_uom,
				"description": item.description,
				"image": item.image,
				"item_name": item.item_name,
				"cost_center": get_default_cost_center(
					args, item, item_group_defaults, company=self.company
				),
				"qty": args.get("qty"),
				"transfer_qty": args.get("qty"),
				"conversion_factor": 1,
				"actual_qty": 0,
				"basic_rate": 0,
				"has_serial_no": item.has_serial_no,
				"has_batch_no": item.has_batch_no,
				"sample_quantity": item.sample_quantity,
				"expense_account": item.expense_account or item_group_defaults.get("expense_account"),
			}
		)

		# update uom
		if args.get("uom") and for_update:
			ret.update(get_uom_details(args.get("item_code"), args.get("uom"), args.get("qty")))

		if self.purpose == "Material Issue":
			ret["expense_account"] = item.get("expense_account") or item_group_defaults.get("expense_account")

		if not ret.get("expense_account"):
			ret["expense_account"] = frappe.get_cached_value(
				"Company", self.company, "stock_adjustment_account"
			)

		for company_field, field in {
			"stock_adjustment_account": "expense_account",
			"cost_center": "cost_center",
		}.items():
			if not ret.get(field):
				ret[field] = frappe.get_cached_value("Company", self.company, company_field)

		args["posting_date"] = self.posting_date
		args["posting_time"] = self.posting_time

		stock_and_rate = get_warehouse_details(args) if args.get("warehouse") else {}
		ret.update(stock_and_rate)

		barcode_data = get_barcode_data(item_code=item.name)
		if barcode_data and len(barcode_data.get(item.name)) == 1:
			ret["barcode"] = barcode_data.get(item.name)[0]

		return ret

	@frappe.whitelist()
	def set_items_for_stock_in(self):
		self.items = []

		if self.outgoing_stock_entry and self.purpose == "Material Transfer":
			hisaabdari.require_permission("Stock Entry", self.outgoing_stock_entry)
			doc = frappe.get_doc("Stock Entry", self.outgoing_stock_entry)

			if doc.per_transferred == 100:
				frappe.throw(_("Goods are already received against the outward entry {0}").format(doc.name))

			for d in doc.items:
				self.append(
					"items",
					{
						"s_warehouse": d.t_warehouse,
						"item_code": d.item_code,
						"qty": d.qty,
						"uom": d.uom,
						"against_stock_entry": d.parent,
						"ste_detail": d.name,
						"stock_uom": d.stock_uom,
						"conversion_factor": d.conversion_factor,
					},
				)

	def validate_batch(self):
		if self.purpose in [
			"Repack",
		]:
			for item in self.get("items"):
				if item.batch_no:
					disabled = frappe.db.get_value("Batch", item.batch_no, "disabled")
					if disabled == 0:
						expiry_date = frappe.db.get_value("Batch", item.batch_no, "expiry_date")
						if expiry_date:
							if getdate(self.posting_date) > getdate(expiry_date):
								frappe.throw(
									_("Batch {0} of Item {1} has expired.").format(
										item.batch_no, item.item_code
									)
								)
					else:
						frappe.throw(
							_("Batch {0} of Item {1} is disabled.").format(item.batch_no, item.item_code)
						)

	def get_stock_in_transferred_qty(self):
		rows = [d for d in self.items if d.against_stock_entry and d.ste_detail]
		if not rows:
			return {}, []

		ste_details = [d.ste_detail for d in rows]
		outward_rows = get_outward_rows(ste_details)
		transferred_qty_map = get_transferred_qty_map(ste_details)
		stock_entries = {}
		for d in rows:
			transferred_qty = flt(transferred_qty_map.get(d.ste_detail))
			outward_row = outward_rows.get(d.ste_detail, frappe._dict())
			if d.docstatus == 1 and transferred_qty > flt(outward_row.transfer_qty):
				frappe.throw(
					_("Row {0}: Transferred quantity cannot be greater than the requested quantity.").format(
						d.idx
					)
				)

			stock_entries[(d.against_stock_entry, d.ste_detail)] = transferred_qty

		return stock_entries, ste_details

	def update_transferred_qty(self):
		if self.purpose == "Material Transfer" and self.outgoing_stock_entry:
			stock_entries, stock_entries_child_list = self.get_stock_in_transferred_qty()
			if not stock_entries:
				return None

			cond = ""
			for data, transferred_qty in stock_entries.items():
				cond += """ WHEN (parent = {} and name = {}) THEN {}
					""".format(
					frappe.db.escape(data[0]),
					frappe.db.escape(data[1]),
					transferred_qty,
				)

			if stock_entries_child_list:
				frappe.db.sql(
					""" UPDATE `tabStock Entry Detail`
					SET
						transferred_qty = CASE {cond} END
					WHERE
						name in ({ste_details}) """.format(
						cond=cond, ste_details=",".join(["%s"] * len(stock_entries_child_list))
					),
					tuple(stock_entries_child_list),
				)

			args = {
				"source_dt": "Stock Entry Detail",
				"target_field": "transferred_qty",
				"target_ref_field": "transfer_qty",
				"target_dt": "Stock Entry Detail",
				"join_field": "ste_detail",
				"target_parent_dt": "Stock Entry",
				"target_parent_field": "per_transferred",
				"source_field": "transfer_qty",
				"percent_join_field": "against_stock_entry",
			}

			self._update_percent_field_in_targets(args, update_modified=True)

	def set_missing_values(self):
		"Updates rate and availability of all the items of mapped doc."
		self.set_transfer_qty()
		self.set_actual_qty()
		self.calculate_rate_and_amount()


@frappe.whitelist()
def move_sample_to_retention_warehouse(company, items):
	from hisaabdari.stock.serial_batch_bundle import (
		SerialBatchCreation,
		get_batch_nos,
	)

	if isinstance(items, str):
		items = json.loads(items)

	retention_warehouse = get_sample_retention_warehouse(company)
	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.company = company
	stock_entry.purpose = "Material Transfer"
	stock_entry.set_stock_entry_type()
	for item in items:
		if item.get("sample_quantity") and item.get("serial_and_batch_bundle"):
			warehouse = item.get("t_warehouse") or item.get("warehouse")
			total_qty = 0
			cls_obj = SerialBatchCreation(
				{
					"type_of_transaction": "Outward",
					"serial_and_batch_bundle": item.get("serial_and_batch_bundle"),
					"item_code": item.get("item_code"),
					"warehouse": warehouse,
					"do_not_save": True,
				}
			)
			sabb = cls_obj.duplicate_package()
			batches = get_batch_nos(item.get("serial_and_batch_bundle"))
			sabe_list = []
			for batch_no in batches.keys():
				sample_quantity = validate_sample_quantity(
					item.get("item_code"),
					item.get("sample_quantity"),
					item.get("transfer_qty") or item.get("qty"),
					company,
					batch_no,
				)

				sabe = next(item for item in sabb.entries if item.batch_no == batch_no)
				if sample_quantity:
					if sabb.has_serial_no:
						new_sabe = [
							entry
							for entry in sabb.entries
							if entry.batch_no == batch_no
							and frappe.db.exists(
								"Serial No", {"name": entry.serial_no, "warehouse": warehouse}
							)
						][: int(sample_quantity)]
						sabe_list.extend(new_sabe)
						total_qty += len(new_sabe)
					else:
						total_qty += sample_quantity
						sabe.qty = sample_quantity
				else:
					sabb.entries.remove(sabe)

			if total_qty:
				if sabe_list:
					sabb.entries = sabe_list
				sabb.save()

				stock_entry.append(
					"items",
					{
						"item_code": item.get("item_code"),
						"s_warehouse": warehouse,
						"t_warehouse": retention_warehouse,
						"qty": total_qty,
						"basic_rate": item.get("valuation_rate"),
						"uom": item.get("uom"),
						"stock_uom": item.get("stock_uom"),
						"conversion_factor": item.get("conversion_factor") or 1.0,
						"serial_and_batch_bundle": sabb.name,
					},
				)
	if stock_entry.get("items"):
		return stock_entry.as_dict()


@frappe.whitelist()
def make_stock_in_entry(source_name: str, target_doc: str | dict | Document | None = None):
	qty_precision = frappe.get_precision("Stock Entry Detail", "transfer_qty")

	def get_remaining_transfer_qty(source_doc):
		remaining_qty = flt(source_doc.transfer_qty) - flt(source_doc.transferred_qty)
		return flt(remaining_qty, qty_precision)

	def set_missing_values(source, target):
		target.stock_entry_type = "Material Transfer"
		target.add_to_transit = 0
		target.set_missing_values()

		if not frappe.get_single_value("Stock Settings", "use_serial_batch_fields"):
			target.make_serial_and_batch_bundle_for_transfer()

	def update_item(source_doc, target_doc, source_parent):
		target_doc.t_warehouse = ""

		target_doc.s_warehouse = source_doc.t_warehouse
		target_doc.qty = get_remaining_qty_in_row_uom(source_doc)
		map_target_dimensions_to_source(source_doc, target_doc)

	def map_target_dimensions_to_source(source_doc, target_doc):
		# the stock sits in transit with the outward entry's target dimensions,
		# so the end transit entry must take it out from there
		from hisaabdari.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions

		for dimension in get_inventory_dimensions():
			fieldname = dimension.source_fieldname
			if fieldname.startswith("to_") or not target_doc.meta.has_field(f"to_{fieldname}"):
				continue

			target_doc.set(fieldname, source_doc.get(f"to_{fieldname}"))
			target_doc.set(f"to_{fieldname}", None)

	def get_remaining_qty_in_row_uom(source_doc):
		remaining_qty = get_remaining_transfer_qty(source_doc)
		conversion_factor = flt(source_doc.conversion_factor)
		qty = flt(
			flt(source_doc.qty) - flt(source_doc.transferred_qty) / conversion_factor,
			source_doc.precision("qty"),
		)
		if flt(qty * conversion_factor, qty_precision) == remaining_qty:
			return qty

		return remaining_qty / conversion_factor

	doclist = get_mapped_doc(
		"Stock Entry",
		source_name,
		{
			"Stock Entry": {
				"doctype": "Stock Entry",
				"field_map": {"name": "outgoing_stock_entry"},
				"validation": {
					"docstatus": ["=", 1],
					"purpose": ["=", "Material Transfer"],
					"add_to_transit": ["=", 1],
				},
			},
			"Stock Entry Detail": {
				"doctype": "Stock Entry Detail",
				"field_map": {
					"name": "ste_detail",
					"parent": "against_stock_entry",
					"serial_no": "serial_no",
					"batch_no": "batch_no",
				},
				"postprocess": update_item,
				"condition": lambda doc: get_remaining_transfer_qty(doc) > 0,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doclist


@frappe.whitelist()
def get_uom_details(item_code, uom, qty):
	"""Returns dict `{"conversion_factor": [value], "transfer_qty": qty * [value]}`
	:param args: dict with `item_code`, `uom` and `qty`"""
	conversion_factor = get_conversion_factor(item_code, uom).get("conversion_factor")

	if not conversion_factor:
		frappe.msgprint(_("UOM conversion factor required for UOM: {0} in Item: {1}").format(uom, item_code))
		ret = {"uom": ""}
	else:
		ret = {
			"conversion_factor": flt(conversion_factor),
			"transfer_qty": flt(qty) * flt(conversion_factor),
		}
	return ret


@frappe.whitelist()
def get_expired_batch_items():
	from hisaabdari.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import get_auto_batch_nos

	frappe.has_permission("Batch", "read", throw=True)
	expired_batches = get_expired_batches()
	if not expired_batches:
		return []

	expired_batches_stock = get_auto_batch_nos(
		frappe._dict(
			{
				"batch_no": list(expired_batches.keys()),
				"for_stock_levels": True,
			}
		)
	)

	for row in expired_batches_stock:
		row.update(expired_batches.get(row.batch_no))

	permitted_warehouses = set(
		frappe.get_list(
			"Warehouse",
			filters={"name": ("in", list({row.warehouse for row in expired_batches_stock}))},
			pluck="name",
		)
	)
	return [row for row in expired_batches_stock if row.warehouse in permitted_warehouses]


def get_outward_rows(ste_details):
	return {
		row.name: row
		for row in frappe.get_all(
			"Stock Entry Detail",
			filters={"name": ("in", ste_details)},
			fields=["name", "item_code", "t_warehouse", "transfer_qty"],
		)
	}


def get_transferred_qty_map(ste_details):
	sed = frappe.qb.DocType("Stock Entry Detail")
	return dict(
		frappe.qb.from_(sed)
		.select(sed.ste_detail, Sum(sed.transfer_qty))
		.where((sed.ste_detail.isin(ste_details)) & (sed.docstatus == 1))
		.groupby(sed.ste_detail)
		.run()
	)


def get_expired_batches():
	data = frappe.get_list(
		"Batch",
		filters=[["expiry_date", "<", nowdate()], ["expiry_date", "is", "set"], ["disabled", "=", 0]],
		fields=["item", "name as batch_no", "stock_uom"],
		limit_page_length=0,
	)

	if not data:
		return []

	expired_batches = frappe._dict()
	for row in data:
		expired_batches[row.batch_no] = row

	return expired_batches


@frappe.whitelist()
def get_warehouse_details(args):
	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)

	frappe.has_permission("Item", ptype="select", throw=True)
	frappe.has_permission("Stock Entry", "read", throw=True)
	if args.warehouse:
		check_stock_entry_warehouse_permission(args.warehouse)

	ret = {}
	if args.warehouse and args.item_code:
		args.update(
			{
				"posting_date": args.posting_date,
				"posting_time": args.posting_time,
			}
		)
		ret = {
			"actual_qty": get_previous_sle(args).get("qty_after_transaction") or 0,
			"basic_rate": _get_incoming_rate(args),
		}
	return ret


def check_stock_entry_warehouse_permission(warehouse: str) -> None:
	user_permissions = get_user_permissions()
	company = frappe.get_cached_value("Warehouse", warehouse, "company")
	for doctype, name in (("Warehouse", warehouse), ("Company", company)):
		allowed_docs = get_allowed_docs_for_doctype(user_permissions.get(doctype, []), "Stock Entry")
		if allowed_docs and name not in allowed_docs:
			frappe.throw(_("Not permitted for {0}").format(name), frappe.PermissionError)


@frappe.whitelist()
def validate_sample_quantity(
	item_code: str, sample_quantity: int, qty: float, company: str, batch_no: str | None = None
):
	if cint(qty) < cint(sample_quantity):
		frappe.throw(
			_("Sample quantity {0} cannot be more than received quantity {1}").format(sample_quantity, qty)
		)
	retention_warehouse = get_sample_retention_warehouse(company)
	retainted_qty = 0
	if batch_no:
		retainted_qty = get_batch_qty(batch_no, retention_warehouse, item_code)
	max_retain_qty = frappe.get_value("Item", item_code, "sample_quantity")
	if retainted_qty >= max_retain_qty:
		frappe.msgprint(
			_(
				"Maximum Samples - {0} have already been retained for Batch {1} and Item {2} in Batch {3}."
			).format(retainted_qty, batch_no, item_code, batch_no),
			alert=True,
		)
		sample_quantity = 0
	qty_diff = max_retain_qty - retainted_qty
	if cint(sample_quantity) > cint(qty_diff):
		if batch_no:
			message = _("Maximum Samples - {0} can be retained for Batch {1} and Item {2}.").format(
				max_retain_qty, batch_no, item_code
			)
		else:
			message = _("Maximum Samples - {0} can be retained for Item {1}.").format(
				max_retain_qty, item_code
			)
		frappe.msgprint(message, alert=True)
		sample_quantity = qty_diff
	return sample_quantity


def get_sample_retention_warehouse(company: str) -> str:
	# `company` arrives from whitelisted callers, so it decides which company's stock gets read.
	frappe.has_permission("Company", "read", company, throw=True)

	warehouse = frappe.get_cached_value("Company", company, "sample_retention_warehouse")
	if not warehouse:
		frappe.throw(
			_("Please set {0} in Company {1} to retain samples.").format(
				bold(_("Sample Retention Warehouse")), bold(company)
			),
			title=_("Sample Retention Warehouse Missing"),
		)
	return warehouse


@frappe.whitelist()
def get_fg_mapping(stock_entry: str):
	doc = get_stock_entry_for_fg_mapping(stock_entry, "read")

	return {
		"fg_values": get_fg_values(doc.name),
		"raw_materials": get_raw_material_entries(doc.name),
	}


@frappe.whitelist()
def set_fg_mapping(stock_entry: str, mapping: str | dict):
	"""Link raw material serial / batch entries to the finished good serial / batch they went into.

	mapping: {raw material Serial and Batch Entry name: target}, where target is
	{"fg_field": "fg_serial_no" / "fg_batch_no", "value": ...}, or just the value when it is unambiguous
	"""
	doc = get_stock_entry_for_fg_mapping(stock_entry, "write")
	mapping = frappe.parse_json(mapping) or {}
	if not isinstance(mapping, dict):
		frappe.throw(_("Mapping must be a dictionary of raw material entries to finished goods"))

	fg_targets = {(row.fg_field, row.value) for row in get_fg_values(doc.name)}
	if not fg_targets:
		frappe.throw(_("{0} has no serial / batch tracked finished good").format(doc.name))

	# only bundle rows that belong to this entry can be changed: draft rows before submit, and after submit
	# only the rows left unmapped, as auto created bundles get their raw material rows on submit
	# rows are locked after submit, so a mapping saved meanwhile by someone else is seen and reported
	is_submitted = doc.docstatus == 1
	raw_materials = {
		row.name: row
		for row in get_raw_material_entries(doc.name, draft_only=not is_submitted, for_update=is_submitted)
	}

	entries_by_fg_target = defaultdict(list)
	for entry_name, target in mapping.items():
		row = raw_materials.get(entry_name)
		if not row:
			frappe.throw(
				_("Row {0} is not a raw material serial / batch entry of {1}").format(
					frappe.bold(escape_html(cstr(entry_name))), doc.name
				)
			)

		fg_target = get_fg_target(target, fg_targets, doc.name)
		if is_submitted:
			if row.fg_serial_no or row.fg_batch_no:
				frappe.throw(
					_(
						"Raw material {0} is already mapped and can't be changed after {1} is submitted"
					).format(frappe.bold(row.serial_no or row.batch_no), doc.name)
				)

			if not fg_target[1]:
				continue

		entries_by_fg_target[fg_target].append(entry_name)

	sabe = frappe.qb.DocType("Serial and Batch Entry")
	for (fg_field, fg_value), entry_names in entries_by_fg_target.items():
		query = (
			frappe.qb.update(sabe)
			.set(sabe.fg_serial_no, fg_value if fg_field == "fg_serial_no" else None)
			.set(sabe.fg_batch_no, fg_value if fg_field == "fg_batch_no" else None)
			.where(sabe.name.isin(entry_names))
		)

		if is_submitted:
			query = query.where(
				(Coalesce(sabe.fg_serial_no, "") == "") & (Coalesce(sabe.fg_batch_no, "") == "")
			)

		query.run()


def set_fg_mapping_on_submit(doc):
	"""Check the draft mapping and map the remaining raw materials to finished goods, in order.

	Serialized raw materials are spread across the finished goods in proportion to their qty. A batch raw
	material is only mapped when there is a single finished good, otherwise it stays linked to all of them.
	The order based mapping can be turned off in Stock Settings; the mapping entered in draft is always kept.
	"""
	if doc.purpose not in ("Repack",):
		return

	fg_values = get_fg_values(doc.name)
	fg_targets = [(row.fg_field, row.value) for row in fg_values]
	raw_materials = get_raw_material_entries(doc.name)
	if not fg_targets or not raw_materials:
		return

	# a finished good batch of 3 takes three times the raw material serials of a single finished good serial
	fg_qty = {(row.fg_field, row.value): row.qty or 1 for row in fg_values}

	rows_by_item = defaultdict(list)
	for row in raw_materials:
		target = ("fg_serial_no", row.fg_serial_no) if row.fg_serial_no else ("fg_batch_no", row.fg_batch_no)
		if target[1] and target not in fg_targets:
			frappe.throw(
				_("Raw material {0} is mapped to {1}, which is not a finished good of this entry").format(
					frappe.bold(row.serial_no or row.batch_no), frappe.bold(target[1])
				)
			)

		row.fg_target = target if target[1] else None
		rows_by_item[row.item_code].append(row)

	if not frappe.get_single_value("Stock Settings", "auto_map_raw_materials_to_finished_goods"):
		return

	entries_by_fg_target = defaultdict(list)
	for rows in rows_by_item.values():
		per_fg = get_fg_quotas(len(rows), fg_targets, fg_qty)
		mapped_count = defaultdict(int)
		for row in rows:
			if row.fg_target:
				mapped_count[row.fg_target] += 1

		for row in rows:
			if row.fg_target or (len(fg_targets) > 1 and not row.serial_no):
				continue

			target = next((t for t in fg_targets if mapped_count[t] < per_fg[t]), None)
			if target:
				mapped_count[target] += 1
				entries_by_fg_target[target].append(row.name)

	sabe = frappe.qb.DocType("Serial and Batch Entry")
	for (fg_field, fg_value), entry_names in entries_by_fg_target.items():
		(frappe.qb.update(sabe).set(sabe[fg_field], fg_value).where(sabe.name.isin(entry_names))).run()


def get_fg_quotas(count, fg_targets, fg_qty):
	"""Split count raw materials across the finished goods by their qty, so the quotas add up to count.

	Each finished good gets its whole share, and what is left goes to the largest remainders, the first
	finished good winning a tie.
	"""
	total_qty = sum(fg_qty[target] for target in fg_targets)
	shares = {target: flt(count * fg_qty[target] / total_qty, 6) for target in fg_targets}
	quotas = {target: math.floor(share) for target, share in shares.items()}

	by_remainder = sorted(fg_targets, key=lambda target: shares[target] - quotas[target], reverse=True)
	for target in by_remainder[: count - sum(quotas.values())]:
		quotas[target] += 1

	return quotas


def get_fg_target(target, fg_targets, stock_entry):
	"""Resolve a mapping target to (fg_field, value); (None, None) clears the mapping."""
	if isinstance(target, dict):
		fg_field, value = target.get("fg_field"), target.get("value")
	else:
		fg_field, value = None, target

	if not value:
		return None, None

	matches = [(field, val) for field, val in fg_targets if val == value and fg_field in (None, field)]
	if not matches:
		frappe.throw(
			_("{0} is not a finished good serial / batch produced by {1}").format(
				frappe.bold(escape_html(cstr(value))), stock_entry
			)
		)

	if len(matches) > 1:
		frappe.throw(
			_("{0} is both a finished good serial no and batch no in {1}, please specify which one").format(
				frappe.bold(escape_html(cstr(value))), stock_entry
			)
		)

	return matches[0]


def get_stock_entry_for_fg_mapping(stock_entry, permission_type):
	doc = frappe.get_doc("Stock Entry", stock_entry)
	doc.check_permission(permission_type)
	# changing a submitted entry also needs submit permission, as for any update after submit
	if permission_type == "write" and doc.docstatus == 1:
		doc.check_permission("submit")

	if doc.purpose not in ("Repack",):
		frappe.throw(_("Finished good mapping is only allowed for Repack entries"))

	# mapped on draft, then fixed on submit; raw materials left unmapped can still be mapped after submit
	if doc.docstatus == 2:
		frappe.throw(_("Finished good mapping can't be changed for a cancelled entry"))

	return doc


def get_fg_values(stock_entry):
	"""Serial nos of serialized finished goods and batch nos of the other batch tracked finished goods."""
	sed = frappe.qb.DocType("Stock Entry Detail")
	sabb = frappe.qb.DocType("Serial and Batch Bundle")
	sabe = frappe.qb.DocType("Serial and Batch Entry")

	fg_entries = (
		frappe.qb.from_(sed)
		.inner_join(sabb)
		.on(sed.serial_and_batch_bundle == sabb.name)
		.inner_join(sabe)
		.on(sabb.name == sabe.parent)
		.select(sed.name.as_("detail_name"), sed.item_code, sabe.serial_no, sabe.batch_no, sabe.qty)
		.where(
			(sed.parent == stock_entry)
			& (sed.is_finished_item == 1)
			& (Coalesce(sed.t_warehouse, "") != "")
			& get_own_bundle_condition(sabb, stock_entry)
		)
		.orderby(sed.idx)
		.orderby(sabe.idx)
	).run(as_dict=True)

	serialized_rows = {row.detail_name for row in fg_entries if row.serial_no}

	fg_values = {}
	for row in fg_entries:
		if row.detail_name in serialized_rows:
			value, fg_field = row.serial_no, "fg_serial_no"
		else:
			value, fg_field = row.batch_no, "fg_batch_no"

		# a serial no and a batch no can share a name, so keep them apart
		if not value:
			continue

		if (fg_field, value) not in fg_values:
			fg_values[(fg_field, value)] = frappe._dict(
				value=value, fg_field=fg_field, item_code=row.item_code, qty=0.0
			)

		fg_values[(fg_field, value)].qty += abs(flt(row.qty))

	return list(fg_values.values())


def get_raw_material_entries(stock_entry, draft_only=False, for_update=False):
	sed = frappe.qb.DocType("Stock Entry Detail")
	sabb = frappe.qb.DocType("Serial and Batch Bundle")
	sabe = frappe.qb.DocType("Serial and Batch Entry")

	query = (
		frappe.qb.from_(sed)
		.inner_join(sabb)
		.on(sed.serial_and_batch_bundle == sabb.name)
		.inner_join(sabe)
		.on(sabb.name == sabe.parent)
		.select(
			sabe.name,
			sed.item_code,
			sed.item_name,
			sabe.serial_no,
			sabe.batch_no,
			sabe.qty,
			sabe.fg_serial_no,
			sabe.fg_batch_no,
		)
		.where(
			(sed.parent == stock_entry)
			& (sed.is_finished_item == 0)
			& (Coalesce(sed.s_warehouse, "") != "")
			& (Coalesce(sed.t_warehouse, "") == "")
			& get_own_bundle_condition(sabb, stock_entry)
		)
		.orderby(sed.idx)
		.orderby(sabe.idx)
	)

	if draft_only:
		query = query.where((sabb.docstatus == 0) & (sabe.docstatus == 0))

	if for_update:
		query = query.for_update()

	return query.run(as_dict=True)


def get_own_bundle_condition(sabb, stock_entry):
	"""Bundles of this stock entry; a draft bundle is linked to its voucher only when the voucher is saved."""
	return (sabb.voucher_type == "Stock Entry") & (Coalesce(sabb.voucher_no, "").isin(["", stock_entry]))
