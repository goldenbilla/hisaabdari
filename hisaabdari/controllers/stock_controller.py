# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from collections import defaultdict

import frappe
from frappe import _, bold
from frappe.model.utils.mask import mask_dict_results
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Count
from frappe.utils import cint, cstr, flt, get_link_to_form, getdate

import hisaabdari
from hisaabdari.accounts.general_ledger import (
	make_gl_entries,
	make_reverse_gl_entries,
	process_gl_map,
)
from hisaabdari.accounts.utils import cancel_exchange_gain_loss_journal, get_fiscal_year
from hisaabdari.controllers.accounts_controller import AccountsController
from hisaabdari.controllers.sales_and_purchase_return import (
	available_serial_batch_for_return,
	filter_serial_batches,
	make_serial_batch_bundle_for_return,
	remove_picked_serial_batches,
)

# Re-exported for backward compatibility; canonical home is hisaabdari.exceptions.
from hisaabdari.exceptions import (
	BatchExpiredError,
)
from hisaabdari.setup.doctype.item_group.item_group import get_item_group_defaults
from hisaabdari.stock import get_warehouse_account, get_warehouse_account_map
from hisaabdari.stock.doctype.inventory_dimension.inventory_dimension import (
	get_evaluated_inventory_dimension,
	get_mandatory_dimension_fields,
	get_mandatory_inventory_dimensions,
)
from hisaabdari.stock.doctype.item.item import get_item_defaults
from hisaabdari.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
	combine_datetime,
	get_type_of_transaction,
)
from hisaabdari.stock.stock_ledger import get_items_to_be_repost


class StockController(AccountsController):
	#: Vouchers whose stock value change should also be booked to the Expenses Added To Stock
	#: account pair (Stock Entry, Stock Reconciliation). Purchase Receipt books its own, against
	#: the landed cost amount rather than the stock value difference.
	book_expenses_added_to_stock = False

	def validate(self):
		super().validate()

		if self.docstatus == 0:
			for table_name in ["items", "packed_items"]:
				self.validate_duplicate_serial_and_batch_bundle(table_name)

		self.validate_warehouse_of_sabb()
		self.validate_serialized_batch()
		self.clean_serial_nos()
		self.validate_customer_provided_item()
		# before the stock UOM rate, which divides by the factor
		self.reset_conversion_factor()
		self.set_rate_of_stock_uom()
		self.validate_internal_transfer()
		self.validate_inventory_dimension_mandatory()

	def on_update(self):
		super().on_update()
		self.check_zero_rate()

	def validate_warehouse_of_sabb(self):
		is_internal_transfer = self.is_internal_transfer()
		doc_before_save = self.get_doc_before_save()
		bundle_details = {}

		for row in self.items:
			for fieldname in ("serial_and_batch_bundle", "rejected_serial_and_batch_bundle"):
				bundle = row.get(fieldname)
				if not bundle:
					continue

				if bundle not in bundle_details:
					bundle_details[bundle] = frappe.db.get_value(
						"Serial and Batch Bundle",
						bundle,
						["company", "type_of_transaction", "warehouse", "has_serial_no"],
						as_dict=True,
					)

				sabb_details = bundle_details[bundle]
				if sabb_details and sabb_details.company != self.company:
					frappe.throw(
						_(
							"Row #{0}: Company {1} does not match with the company {2} in Serial and Batch Bundle {3}."
						).format(row.idx, self.company, sabb_details.company, bundle)
					)

			sabb_details = bundle_details.get(row.get("serial_and_batch_bundle"))
			if not sabb_details:
				continue

			if is_internal_transfer or sabb_details.type_of_transaction != "Outward":
				continue

			warehouse = row.get("warehouse") or row.get("s_warehouse")
			if sabb_details.warehouse != warehouse:
				frappe.throw(
					_(
						"Row #{0}: Warehouse {1} does not match with the warehouse {2} in Serial and Batch Bundle {3}."
					).format(row.idx, warehouse, sabb_details.warehouse, row.serial_and_batch_bundle)
				)

			if self.doctype == "Stock Reconciliation":
				continue

			if sabb_details.has_serial_no and doc_before_save and doc_before_save.get("items"):
				prev_row = doc_before_save.get("items", {"idx": row.idx})
				if prev_row and prev_row[0].serial_and_batch_bundle != row.serial_and_batch_bundle:
					sabb_doc = frappe.get_doc("Serial and Batch Bundle", row.serial_and_batch_bundle)
					sabb_doc.validate_serial_no_status()

	def reset_conversion_factor(self):
		for row in self.get("items"):
			if row.uom != row.stock_uom:
				continue

			if row.conversion_factor != 1.0:
				row.conversion_factor = 1.0
				frappe.msgprint(
					_(
						"Conversion factor for item {0} has been reset to 1.0 as the uom {1} is same as stock uom {2}."
					).format(bold(row.item_code), bold(row.uom), bold(row.stock_uom)),
					alert=True,
				)

	def check_zero_rate(self):
		if self.doctype in [
			"Purchase Invoice",
			"Sales Invoice",
			"Delivery Note",
			"Purchase Receipt",
			"Stock Entry",
			"Stock Reconciliation",
		]:
			for item in self.get("items"):
				if (
					(
						item.get("valuation_rate") == 0
						or (item.get("incoming_rate") == 0 and self.get("update_stock", 1))
					)
					and item.get("allow_zero_valuation_rate") == 0
					and frappe.get_cached_value("Item", item.item_code, "is_stock_item")
				):
					frappe.toast(
						_("Row #{0}: Item {1} has zero rate but '{2}' is not enabled.").format(
							item.idx,
							frappe.bold(item.item_code),
							item.meta.get_label("allow_zero_valuation_rate"),
						),
						indicator="orange",
					)

	def validate_items_exist(self):
		if not self.get("items"):
			return

		items = [d.item_code for d in self.get("items")]

		exists_items = frappe.get_all("Item", filters={"name": ("in", items)}, pluck="name")
		non_exists_items = set(items) - set(exists_items)

		if non_exists_items:
			frappe.throw(_("Items {0} do not exist in the Item master.").format(", ".join(non_exists_items)))

	def validate_duplicate_serial_and_batch_bundle(self, table_name):
		if not self.get(table_name):
			return

		sbb_list = []
		for item in self.get(table_name):
			if item.get("serial_and_batch_bundle"):
				sbb_list.append(item.get("serial_and_batch_bundle"))

			if item.get("rejected_serial_and_batch_bundle"):
				sbb_list.append(item.get("rejected_serial_and_batch_bundle"))

		if sbb_list:
			SLE = frappe.qb.DocType("Stock Ledger Entry")
			data = (
				frappe.qb.from_(SLE)
				.select(SLE.voucher_type, SLE.voucher_no, SLE.serial_and_batch_bundle)
				.where(
					(SLE.docstatus == 1)
					& (SLE.serial_and_batch_bundle.notnull())
					& (SLE.serial_and_batch_bundle.isin(sbb_list))
				)
				.limit(1)
			).run(as_dict=True)

			if data:
				data = data[0]
				frappe.throw(
					_("Serial and Batch Bundle {0} is already used in {1} {2}.").format(
						frappe.bold(data.serial_and_batch_bundle), data.voucher_type, data.voucher_no
					)
				)

	def get_item_wise_inventory_account_map(self):
		inventory_account_map = frappe._dict()
		for table in ["items", "packed_items"]:
			if not self.get(table):
				continue

			_map = get_item_wise_inventory_account_map(self.get(table), self.company)
			inventory_account_map.update(_map)

		return inventory_account_map

	@property
	def use_item_inventory_account(self):
		return frappe.get_cached_value("Company", self.company, "enable_item_wise_inventory_account")

	def get_inventory_account_dict(
		self, row, inventory_account_map, warehouse_field=None, *, raise_error=True
	):
		account_dict = frappe._dict()

		if isinstance(row, dict):
			row = frappe._dict(row)

		if self.use_item_inventory_account:
			item_code = (
				row.rm_item_code if hasattr(row, "rm_item_code") and row.rm_item_code else row.item_code
			)

			account_dict = inventory_account_map.get(item_code)

			if not account_dict:
				frappe.throw(
					_(
						"Please set default inventory account for item {0}, or their item group."
					).format(bold(item_code))
				)

			return account_dict

		if not warehouse_field:
			warehouse_field = "warehouse"

		warehouse = row.get(warehouse_field)
		if not warehouse:
			warehouse = self.get(warehouse_field)

		if warehouse:
			account_dict = inventory_account_map.get(warehouse)
			if not account_dict and raise_error:
				account = get_warehouse_account(frappe.get_cached_doc("Warehouse", warehouse))
				account_dict = frappe._dict(
					account=account,
					account_currency=frappe.get_cached_value("Account", account, "account_currency"),
				)
				inventory_account_map[warehouse] = account_dict

		return account_dict

	def get_inventory_account_map(self):
		if self.use_item_inventory_account:
			return self.get_item_wise_inventory_account_map()

		return get_warehouse_account_map(self.company)

	def make_gl_entries(self, gl_entries=None, from_repost=False, via_landed_cost_voucher=False):
		if self.docstatus == 2:
			make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

		provisional_accounting_for_non_stock_items = cint(
			frappe.get_cached_value(
				"Company", self.company, "enable_provisional_accounting_for_non_stock_items"
			)
		)
		need_inventory_map = (self.get_stock_items() or self.get("packed_items")) and (
			cint(hisaabdari.is_perpetual_inventory_enabled(self.company))
		)

		inventory_account_map = frappe._dict()
		if need_inventory_map:
			inventory_account_map = self.get_inventory_account_map()

		if need_inventory_map or provisional_accounting_for_non_stock_items:
			if self.docstatus == 1:
				if not gl_entries:
					gl_entries = (
						self.get_gl_entries(inventory_account_map, via_landed_cost_voucher)
						if self.doctype == "Purchase Receipt"
						else self.get_gl_entries(inventory_account_map)
					)
				make_gl_entries(gl_entries, from_repost=from_repost)

	def validate_serialized_batch(self):
		from hisaabdari.stock.doctype.serial_no.serial_no import get_serial_nos

		is_material_issue = False
		if self.doctype == "Stock Entry" and self.purpose in ["Material Issue", "Material Transfer"]:
			is_material_issue = True

		check_batches = self.is_batch_check_needed()
		for d in self.get("items"):
			if hasattr(d, "serial_no") and hasattr(d, "batch_no") and d.serial_no and d.batch_no:
				serial_nos = frappe.get_all(
					"Serial No",
					fields=["batch_no", "name", "warehouse"],
					filters={"name": ("in", get_serial_nos(d.serial_no))},
				)

				for row in serial_nos:
					if row.warehouse and row.batch_no != d.batch_no:
						frappe.throw(
							_("Row #{0}: Serial No {1} does not belong to Batch {2}").format(
								d.idx, row.name, d.batch_no
							)
						)

			if (
				check_batches
				and flt(d.qty) > 0.0
				and d.get("batch_no")
				and self.get("posting_date")
				and self.docstatus < 2
			):
				expiry_date, disabled = frappe.get_cached_value(
					"Batch", d.get("batch_no"), ["expiry_date", "disabled"]
				)
				self.validate_batch_is_usable(
					d.idx, d.batch_no, None if is_material_issue else expiry_date, disabled
				)

		if check_batches:
			self.validate_outward_bundle_batches(check_expiry=not is_material_issue)

	def is_batch_check_needed(self) -> bool:
		"""An invoice without Update Stock moves no stock, so its batches were checked when they moved."""
		is_invoice = self.doctype in ("Sales Invoice", "Purchase Invoice")
		return not is_invoice or bool(self.get("update_stock"))

	def validate_batch_is_usable(self, idx, batch_no, expiry_date, disabled):
		if disabled:
			frappe.throw(
				_("Row #{0}: The batch {1} is disabled.").format(idx, get_link_to_form("Batch", batch_no))
			)

		if expiry_date and getdate(expiry_date) < getdate(self.posting_date):
			frappe.throw(
				_("Row #{0}: The batch {1} has already expired.").format(
					idx, get_link_to_form("Batch", batch_no)
				),
				BatchExpiredError,
			)

	def validate_outward_bundle_batches(self, check_expiry=True, rows=None, qty_field="qty"):
		if self.get("is_return") or not self.get("posting_date") or self.docstatus == 2:
			return

		if rows is None:
			rows = (self.get("items") or []) + (self.get("packed_items") or [])

		row_idx_by_bundle = {
			d.serial_and_batch_bundle: d.idx
			for d in rows
			if d.get("serial_and_batch_bundle") and flt(d.get(qty_field)) > 0
		}
		if not row_idx_by_bundle:
			return

		posting_date = self.posting_date if check_expiry else None
		for row in get_unusable_outward_bundle_batches(list(row_idx_by_bundle), posting_date):
			self.validate_batch_is_usable(
				row_idx_by_bundle[row.bundle],
				row.batch_no,
				row.expiry_date if check_expiry else None,
				row.disabled,
			)

	def clean_serial_nos(self):
		from hisaabdari.stock.doctype.serial_no.serial_no import clean_serial_no_string

		for row in self.get("items"):
			if hasattr(row, "serial_no") and row.serial_no:
				# remove extra whitespace and store one serial no on each line
				row.serial_no = clean_serial_no_string(row.serial_no)

		for row in self.get("packed_items") or []:
			if hasattr(row, "serial_no") and row.serial_no:
				# remove extra whitespace and store one serial no on each line
				row.serial_no = clean_serial_no_string(row.serial_no)

	def make_bundle_using_old_serial_batch_fields(self, table_name=None, via_landed_cost_voucher=False):
		if self.get("_action") == "update_after_submit":
			return

		# To handle test cases
		if frappe.in_test and frappe.flags.use_serial_and_batch_fields:
			return

		if not table_name:
			table_name = "items"

		parent_details = frappe._dict()
		if table_name == "packed_items":
			parent_details = self.get_parent_details_for_packed_items()

		auto_pick_outward = self.auto_picks_outward_serial_batch()
		picked_serial_nos = picked_batches = None
		if auto_pick_outward:
			picked_serial_nos = self.get_serial_nos_used_in_rows()
			picked_batches = self.get_batches_used_in_rows()

		for row in self.get(table_name):
			item_code = row.get("rm_item_code") or row.get("item_code")
			if not item_code or not self.is_serial_batch_item(item_code):
				continue

			if (
				not via_landed_cost_voucher
				and row.serial_and_batch_bundle
				and (row.serial_no or row.batch_no)
			):
				self.validate_serial_nos_and_batches_with_bundle(row)

			if not row.serial_no and not row.batch_no and not row.get("rejected_serial_no"):
				if not (auto_pick_outward and row.get("use_serial_batch_fields") and flt(row.get("qty")) > 0):
					continue

			if not row.use_serial_batch_fields and (
				row.serial_no or row.batch_no or row.get("rejected_serial_no")
			):
				row.use_serial_batch_fields = 1

			if row.use_serial_batch_fields and (
				not row.serial_and_batch_bundle and not row.get("rejected_serial_and_batch_bundle")
			):
				bundle_details = {
					"item_code": row.get("rm_item_code") or row.item_code,
					"posting_datetime": combine_datetime(self.posting_date, self.posting_time),
					"voucher_type": self.doctype,
					"voucher_no": self.name,
					"voucher_detail_no": row.name,
					"company": self.company,
					"is_rejected": 1 if row.get("rejected_warehouse") else 0,
					"use_serial_batch_fields": row.use_serial_batch_fields,
					"via_landed_cost_voucher": via_landed_cost_voucher,
					"do_not_submit": True if not via_landed_cost_voucher else False,
				}

				if self.is_internal_transfer() and row.get("from_warehouse") and not self.is_return:
					self.update_bundle_details(bundle_details, table_name, row)
					bundle_details["type_of_transaction"] = "Outward"
					bundle_details["warehouse"] = row.get("from_warehouse")
					bundle_details["qty"] = row.get("stock_qty") or row.get("qty")
					self.create_serial_batch_bundle(bundle_details, row)
					continue

				if row.get("qty") or row.get("consumed_qty") or row.get("stock_qty"):
					self.update_bundle_details(bundle_details, table_name, row, parent_details=parent_details)
					self.create_auto_picked_bundle(bundle_details, row, picked_serial_nos, picked_batches)

				if self.get_rejected_stock_qty(row):
					self.update_bundle_details(bundle_details, table_name, row, is_rejected=True)
					self.create_serial_batch_bundle(bundle_details, row)

	def get_serial_nos_used_in_rows(self):
		from hisaabdari.stock.doctype.serial_no.serial_no import get_serial_nos

		picked_serial_nos = defaultdict(list)
		bundle_items = {}
		for row in self.get("items") + self.get_current_packed_rows():
			item_code = row.get("rm_item_code") or row.item_code
			if row.get("serial_no"):
				picked_serial_nos[item_code].extend(get_serial_nos(row.serial_no))
			elif row.get("serial_and_batch_bundle"):
				bundle_items[row.serial_and_batch_bundle] = item_code

		if bundle_items:
			for entry in frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": ("in", list(bundle_items)), "serial_no": ("is", "set")},
				fields=["parent", "serial_no"],
			):
				picked_serial_nos[bundle_items[entry.parent]].append(entry.serial_no)

		return picked_serial_nos

	def get_batches_used_in_rows(self):
		"""Batch qty the rows already take, by (batch_no, warehouse)."""
		entries, bundles = [], []
		# the row's bundle takes the qty rounded to this precision
		precision = frappe.get_precision("Serial and Batch Entry", "qty")
		for row in self.get("items") + self.get_current_packed_rows():
			if row.get("serial_and_batch_bundle"):
				bundles.append(row.serial_and_batch_bundle)
			elif row.get("batch_no"):
				qty = row.qty if row.doctype == "Packed Item" else row.stock_qty
				entries.append(
					frappe._dict(batch_no=row.batch_no, warehouse=row.warehouse, qty=-flt(qty, precision))
				)

		if bundles:
			entries += frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": ("in", bundles), "batch_no": ("is", "set")},
				fields=["batch_no", "warehouse", "qty"],
			)

		picked_batches = frappe._dict()
		add_picked_batches(picked_batches, entries)
		return picked_batches

	def get_current_packed_rows(self):
		"""Packed rows of the current item rows; rows of removed items stay until the packing list is rebuilt."""
		item_rows = {(row.name, row.item_code) for row in self.get("items")}
		return [
			row
			for row in self.get("packed_items") or []
			if (row.parent_detail_docname, row.parent_item) in item_rows
		]

	def create_auto_picked_bundle(self, bundle_details, row, picked_serial_nos, picked_batches):
		if picked_serial_nos is None or row.serial_no:
			self.create_serial_batch_bundle(bundle_details, row)
			return

		item_code = bundle_details["item_code"]
		bundle_details["ignore_serial_nos"] = list(picked_serial_nos[item_code])
		bundle_details["already_picked_batches"] = picked_batches
		sn_doc = self.create_serial_batch_bundle(bundle_details, row)
		entries = sn_doc.get("entries") or []
		picked_serial_nos[item_code].extend(d.serial_no for d in entries if d.serial_no)
		# a row's own batch no is already counted in picked_batches
		if not row.batch_no:
			add_picked_batches(picked_batches, entries)

	def auto_picks_outward_serial_batch(self):
		if self.doctype not in ("Delivery Note", "Sales Invoice") or self.get("is_return"):
			return False

		return bool(
			frappe.get_single_value("Stock Settings", "auto_create_serial_and_batch_bundle_for_outward")
		)

	def get_parent_details_for_packed_items(self):
		parent_details = frappe._dict()
		for row in self.get("items"):
			parent_details[row.name] = row

		return parent_details

	def make_bundle_for_sales_purchase_return(self, table_name=None):
		if not self.get("is_return"):
			return

		if not table_name:
			table_name = "items"

		self.make_bundle_for_non_rejected_qty(table_name)

		if self.doctype in ["Purchase Invoice", "Purchase Receipt"]:
			self.make_bundle_for_rejected_qty(table_name)

	def make_bundle_for_rejected_qty(self, table_name=None):
		field, reference_ids = self.get_reference_ids(
			table_name, "rejected_qty", "rejected_serial_and_batch_bundle"
		)

		if not reference_ids:
			return

		child_doctype = self.doctype + " Item"
		available_dict = available_serial_batch_for_return(
			field, child_doctype, reference_ids, is_rejected=True
		)

		for row in self.get(table_name):
			if not self.needs_rejected_bundle(row):
				continue

			if data := available_dict.get(row.get(field)):
				qty_field = "rejected_qty"
				warehouse_field = "rejected_warehouse"
				if row.get("return_qty_from_rejected_warehouse"):
					qty_field = "stock_qty"
					warehouse_field = "warehouse"

				if not data.get("qty"):
					frappe.throw(
						_("For the {0}, no stock is available for the return in the warehouse {1}.").format(
							frappe.bold(row.item_code), row.get(warehouse_field)
						)
					)

				picked = filter_serial_batches(
					self, data, row, warehouse_field=warehouse_field, qty_field=qty_field
				)
				bundle = make_serial_batch_bundle_for_return(picked, row, self, warehouse_field, qty_field)
				remove_picked_serial_batches(data, picked, self)
				if row.get("return_qty_from_rejected_warehouse"):
					row.db_set(
						{
							"serial_and_batch_bundle": bundle,
							"batch_no": "",
							"serial_no": "",
						}
					)
				else:
					row.db_set(
						{
							"rejected_serial_and_batch_bundle": bundle,
							"batch_no": "",
							"rejected_serial_no": "",
						}
					)

	def make_bundle_for_non_rejected_qty(self, table_name):
		field, reference_ids = self.get_reference_ids(table_name)
		if not reference_ids:
			return

		reference_field = field
		child_doctype = self.doctype + " Item"
		if table_name == "packed_items":
			field = "parent_detail_docname"
			child_doctype = "Packed Item"

		available_dict = available_serial_batch_for_return(field, child_doctype, reference_ids)

		for row in self.get(table_name):
			if row.get("return_qty_from_rejected_warehouse") or not row.get("qty"):
				continue

			value = row.get(field)
			if table_name == "packed_items" and row.get("parent_detail_docname"):
				value = self.get_value_for_packed_item(row, reference_field)
				if not value:
					continue

			if data := available_dict.get(value):
				picked = filter_serial_batches(self, data, row)
				bundle = make_serial_batch_bundle_for_return(picked, row, self)
				remove_picked_serial_batches(data, picked, self)
				row.db_set(
					{
						"serial_and_batch_bundle": bundle,
						"batch_no": "",
						"serial_no": "",
					}
				)

				if self.doctype in ["Sales Invoice", "Delivery Note"]:
					row.db_set(
						"incoming_rate", frappe.db.get_value("Serial and Batch Bundle", bundle, "avg_rate")
					)

	def needs_rejected_bundle(self, row) -> bool:
		"""Return row takes rejected qty and has no bundle for it yet."""
		if row.get("return_qty_from_rejected_warehouse"):
			return not row.get("serial_and_batch_bundle")

		return bool(
			row.get("rejected_warehouse")
			and self.get_rejected_stock_qty(row)
			and not row.get("rejected_serial_and_batch_bundle")
		)

	def get_rejected_stock_qty(self, row) -> float:
		"""Rejected qty of a row in the stock UOM, rounded as its bundle holds it."""
		return flt(
			flt(row.get("rejected_qty")) * flt(row.get("conversion_factor", 1.0)),
			frappe.get_precision("Serial and Batch Entry", "qty"),
		)

	def get_value_for_packed_item(self, row, reference_field):
		parent_items = self.get("items", {"name": row.parent_detail_docname})
		if parent_items:
			return (row.item_code, parent_items[0].get(reference_field))

		return None

	def get_reference_ids(self, table_name, qty_field=None, bundle_field=None) -> tuple[str, list[str]]:
		field = {
			"Sales Invoice": "sales_invoice_item",
			"Delivery Note": "dn_detail",
			"Purchase Receipt": "purchase_receipt_item",
			"Purchase Invoice": "purchase_invoice_item",
		}.get(self.doctype)

		if not bundle_field:
			bundle_field = "serial_and_batch_bundle"

		if not qty_field:
			qty_field = "qty"

		reference_ids = []

		for row in self.get(table_name):
			if not self.is_serial_batch_item(row.item_code):
				continue

			needs_bundle = (
				self.needs_rejected_bundle(row)
				if qty_field == "rejected_qty"
				else row.get("qty")
				and not row.get("return_qty_from_rejected_warehouse")
				and not row.get(bundle_field)
			)
			if row.get(field) and needs_bundle and not row.get("use_serial_batch_fields"):
				reference_ids.append(row.get(field))

			if table_name == "packed_items" and row.get("parent_detail_docname"):
				parent_rows = self.get("items", {"name": row.parent_detail_docname}) or []
				for d in parent_rows:
					if (
						d.get(field)
						and not d.get(bundle_field)
						and not self.is_legacy_packed_item(row, d.get(field))
					):
						reference_ids.append(d.get(field))

		return field, reference_ids

	def is_legacy_packed_item(self, row, source_parent_detail_docname):
		"""Packed items delivered before v15 have serial / batch fields, but no bundle to return
		against. make_bundle_using_old_serial_batch_fields handles them."""
		if not (row.serial_no or row.batch_no):
			return False

		return not frappe.db.exists(
			"Packed Item",
			{
				"parent_detail_docname": source_parent_detail_docname,
				"item_code": row.item_code,
				"serial_and_batch_bundle": ("is", "set"),
			},
		)

	@frappe.request_cache
	def is_serial_batch_item(self, item_code) -> bool:
		if not frappe.db.exists("Item", item_code):
			frappe.throw(_("Item {0} does not exist.").format(bold(item_code)))

		item_details = frappe.db.get_value("Item", item_code, ["has_serial_no", "has_batch_no"], as_dict=1)

		if item_details.has_serial_no or item_details.has_batch_no:
			return True

		return False

	def update_bundle_details(self, bundle_details, table_name, row, is_rejected=False, parent_details=None):
		from hisaabdari.stock.doctype.serial_no.serial_no import get_serial_nos

		# Since qty field is different for different doctypes
		qty = row.get("qty")
		warehouse = row.get("warehouse")

		if table_name == "packed_items":
			type_of_transaction = "Inward"
			if not self.is_return:
				type_of_transaction = "Outward"
		else:
			type_of_transaction = get_type_of_transaction(self, row)

		if hasattr(row, "stock_qty"):
			qty = row.stock_qty

		if self.doctype == "Stock Entry":
			qty = row.transfer_qty
			warehouse = row.s_warehouse or row.t_warehouse

		serial_nos = row.serial_no
		if is_rejected:
			serial_nos = row.get("rejected_serial_no")
			type_of_transaction = "Inward" if not self.is_return else "Outward"
			qty = self.get_rejected_stock_qty(row)
			warehouse = row.get("rejected_warehouse")

		if (
			self.is_internal_transfer()
			and self.doctype in ["Sales Invoice", "Delivery Note"]
			and self.is_return
		):
			warehouse = row.get("target_warehouse") or row.get("warehouse")
			type_of_transaction = "Outward"

		if table_name == "packed_items":
			if not warehouse:
				warehouse = parent_details[row.parent_detail_docname].warehouse
			bundle_details["voucher_detail_no"] = parent_details[row.parent_detail_docname].name

		bundle_details.update(
			{
				"qty": qty,
				"is_rejected": is_rejected,
				"type_of_transaction": type_of_transaction,
				"warehouse": warehouse,
				"batches": frappe._dict({row.batch_no: qty}) if row.batch_no else None,
				"serial_nos": get_serial_nos(serial_nos) if serial_nos else None,
				"batch_no": row.batch_no,
			}
		)

	def create_serial_batch_bundle(self, bundle_details, row):
		from hisaabdari.stock.serial_batch_bundle import SerialBatchCreation

		sn_doc = SerialBatchCreation(bundle_details).make_serial_and_batch_bundle()

		field = "serial_and_batch_bundle"
		if bundle_details.get("is_rejected"):
			field = "rejected_serial_and_batch_bundle"

		row.set(field, sn_doc.name)
		row.db_set({field: sn_doc.name})

		return sn_doc

	def validate_serial_nos_and_batches_with_bundle(self, row):
		from hisaabdari.stock.doctype.serial_no.serial_no import get_serial_nos

		throw_error = False
		if row.serial_no:
			serial_nos = frappe.get_all(
				"Serial and Batch Entry",
				fields=["serial_no"],
				filters={"parent": row.serial_and_batch_bundle},
			)
			serial_nos = sorted([cstr(d.serial_no) for d in serial_nos])
			parsed_serial_nos = get_serial_nos(row.serial_no)

			if len(serial_nos) != len(parsed_serial_nos):
				throw_error = True
			elif serial_nos != parsed_serial_nos:
				for serial_no in serial_nos:
					if serial_no not in parsed_serial_nos:
						throw_error = True
						break

		elif row.batch_no:
			batches = sorted(
				frappe.get_all(
					"Serial and Batch Entry",
					filters={"parent": row.serial_and_batch_bundle},
					pluck="batch_no",
					distinct=True,
				)
			)

			if batches != [row.batch_no]:
				throw_error = True

		if throw_error:
			frappe.throw(
				_(
					"At row {0}: Serial and Batch Bundle {1} has already created. Please remove the values from the serial no or batch no fields."
				).format(row.idx, row.serial_and_batch_bundle)
			)

	def set_use_serial_batch_fields(self):
		if frappe.get_single_value("Stock Settings", "use_serial_batch_fields"):
			for row in self.items:
				row.use_serial_batch_fields = 1

	def get_gl_entries(
		self, inventory_account_map=None, default_expense_account=None, default_cost_center=None
	):
		if not inventory_account_map:
			inventory_account_map = self.get_inventory_account_map()

		sle_map = self.get_stock_ledger_details()
		voucher_details = self.get_voucher_details(default_expense_account, default_cost_center, sle_map)

		gl_list = []
		warehouse_with_no_account = []
		precision = self.get_debit_field_precision()
		for item_row in voucher_details:
			sle_list = sle_map.get(item_row.name)
			sle_rounding_diff = 0.0
			if sle_list:
				for sle in sle_list:
					_inv_dict = self.get_inventory_account_dict(sle, inventory_account_map)

					if _inv_dict.get("account"):
						# from warehouse account

						sle_rounding_diff += flt(sle.stock_value_difference)

						self.check_expense_account(item_row)

						# expense account/ target_warehouse / source_warehouse
						if item_row.get("target_warehouse"):
							_target_wh_inv_dict = self.get_inventory_account_dict(
								item_row, inventory_account_map, warehouse_field="target_warehouse"
							)
							expense_account = _target_wh_inv_dict["account"]
						else:
							expense_account = item_row.expense_account

						gl_list.append(
							self.get_gl_dict(
								{
									"account": _inv_dict["account"],
									"against": expense_account,
									"cost_center": item_row.cost_center,
									"project": sle.get("project") or item_row.get("project") or self.get("project"),
									"remarks": self.get("remarks") or _("Accounting Entry for Stock"),
									"debit": flt(sle.stock_value_difference, precision),
									"is_opening": item_row.get("is_opening")
									or self.get("is_opening")
									or "No",
								},
								_inv_dict["account_currency"],
								item=item_row,
							)
						)

						gl_list.append(
							self.get_gl_dict(
								{
									"account": expense_account,
									"against": _inv_dict["account"],
									"cost_center": item_row.cost_center,
									"remarks": self.get("remarks") or _("Accounting Entry for Stock"),
									"debit": -1 * flt(sle.stock_value_difference, precision),
									"project": sle.get("project")
									or item_row.get("project")
									or self.get("project"),
									"is_opening": item_row.get("is_opening")
									or self.get("is_opening")
									or "No",
								},
								item=item_row,
							)
						)
					elif sle.warehouse not in warehouse_with_no_account:
						warehouse_with_no_account.append(sle.warehouse)

			if abs(sle_rounding_diff) > (1.0 / (10**precision)) and self.is_internal_transfer():
				warehouse_asset_account = ""
				if self.get("is_internal_customer"):
					_inv_dict = self.get_inventory_account_dict(
						item_row, inventory_account_map, warehouse_field="target_warehouse"
					)

					warehouse_asset_account = _inv_dict.get("account") if _inv_dict else None
				elif self.get("is_internal_supplier"):
					_inv_dict = self.get_inventory_account_dict(item_row, inventory_account_map)

					warehouse_asset_account = _inv_dict.get("account") if _inv_dict else None

				expense_account = frappe.get_cached_value("Company", self.company, "default_expense_account")
				if not expense_account:
					frappe.throw(
						_(
							"Please set default cost of goods sold account in company {0} for booking rounding gain and loss during stock transfer"
						).format(frappe.bold(self.company))
					)

				gl_list.append(
					self.get_gl_dict(
						{
							"account": expense_account,
							"against": warehouse_asset_account,
							"cost_center": item_row.cost_center,
							"project": item_row.get("project") or self.get("project"),
							"remarks": _("Rounding gain/loss Entry for Stock Transfer"),
							"debit": sle_rounding_diff,
							"is_opening": item_row.get("is_opening") or self.get("is_opening") or "No",
						},
						_inv_dict["account_currency"],
						item=item_row,
					)
				)

				gl_list.append(
					self.get_gl_dict(
						{
							"account": warehouse_asset_account,
							"against": expense_account,
							"cost_center": item_row.cost_center,
							"remarks": _("Rounding gain/loss Entry for Stock Transfer"),
							"credit": sle_rounding_diff,
							"project": item_row.get("project") or self.get("project"),
							"is_opening": item_row.get("is_opening") or self.get("is_opening") or "No",
						},
						item=item_row,
					)
				)

		if warehouse_with_no_account:
			for wh in warehouse_with_no_account:
				if frappe.get_cached_value("Warehouse", wh, "company"):
					frappe.throw(
						_(
							"Warehouse {0} is not linked to any account, please mention the account in the warehouse record or set default inventory account in company {1}."
						).format(wh, self.company)
					)

		if self.book_expenses_added_to_stock:
			self.append_expenses_added_to_stock_entries(gl_list, voucher_details, sle_map)

		return process_gl_map(
			gl_list, precision=precision, from_repost=frappe.flags.through_repost_item_valuation
		)

	def book_stock_expense_enabled(self):
		if not hasattr(self, "_book_stock_expense_enabled"):
			self._book_stock_expense_enabled = cint(
				frappe.db.get_single_value("Accounts Settings", "book_stock_expense_gl_entries")
			)

		return self._book_stock_expense_enabled

	def append_expenses_added_to_stock_entries(self, gl_list, voucher_details, sle_map):
		if not self.book_stock_expense_enabled():
			return

		precision = self.get_debit_field_precision()

		for item_row in voucher_details:
			sle_list = sle_map.get(item_row.name)
			if not sle_list:
				continue

			amount = flt(sum(flt(sle.stock_value_difference) for sle in sle_list), precision)
			if not amount:
				continue

			item_code = item_row.get("item_code") or sle_list[0].item_code
			self.append_expenses_added_to_stock_pair(gl_list, item_code, amount, item_row)

	def append_expenses_added_to_stock_pair(self, gl_list, item_code, amount, item_row):
		# A service item holds no stock value, so there is nothing to book against it - and it must
		# not make the expense accounts mandatory either. A zero pair would be rejected by GL Entry
		# anyway, which needs a debit or a credit on every row.
		if not amount or not frappe.get_cached_value("Item", item_code, "is_stock_item"):
			return

		fields = ("expenses_added_to_stock_account", "expenses_added_to_stock_contra_account")
		details = get_expenses_added_to_stock_accounts(item_code, self.company)

		for field in fields:
			if not details.get(field):
				frappe.throw(
					_("Please set {0} in Company {1} or in the Item Defaults of Item {2}").format(
						frappe.bold(_(frappe.unscrub(field))), self.company, item_code
					)
				)

		cost_center = item_row.get("cost_center") or frappe.get_cached_value(
			"Company", self.company, "cost_center"
		)
		remarks = _("Expenses Added To Stock for Item {0}").format(item_code)
		common_args = {
			"cost_center": cost_center,
			"project": item_row.get("project") or self.get("project"),
			"remarks": remarks,
		}

		gl_list.append(
			self.get_gl_dict(
				{
					"account": details.expenses_added_to_stock_account,
					"against": details.expenses_added_to_stock_contra_account,
					"debit": amount,
					**common_args,
				},
				item=item_row,
			)
		)
		gl_list.append(
			self.get_gl_dict(
				{
					"account": details.expenses_added_to_stock_contra_account,
					"against": details.expenses_added_to_stock_account,
					"debit": -1 * amount,
					**common_args,
				},
				item=item_row,
			)
		)

	def get_debit_field_precision(self):
		if not frappe.flags.debit_field_precision:
			frappe.flags.debit_field_precision = frappe.get_precision("GL Entry", "debit_in_account_currency")

		return frappe.flags.debit_field_precision

	def get_voucher_details(self, default_expense_account, default_cost_center, sle_map):
		if self.doctype == "Stock Reconciliation":
			reconciliation_purpose = frappe.db.get_value(self.doctype, self.name, "purpose")
			is_opening = "Yes" if reconciliation_purpose == "Opening Stock" else "No"
			details = []
			for voucher_detail_no in sle_map:
				details.append(
					frappe._dict(
						{
							"name": voucher_detail_no,
							"expense_account": default_expense_account,
							"cost_center": default_cost_center,
							"is_opening": is_opening,
						}
					)
				)
			return details
		else:
			details = self.get("items")

			if default_expense_account or default_cost_center:
				for d in details:
					if default_expense_account and not d.get("expense_account"):
						d.expense_account = default_expense_account
					if default_cost_center and not d.get("cost_center"):
						d.cost_center = default_cost_center

			return details

	def get_items_and_warehouses(self) -> tuple[list[str], list[str]]:
		"""Get list of items and warehouses affected by a transaction"""

		if not (hasattr(self, "items") or hasattr(self, "packed_items")):
			return [], []

		item_rows = (self.get("items") or []) + (self.get("packed_items") or [])

		items = {d.item_code for d in item_rows if d.item_code}

		warehouses = set()
		for d in item_rows:
			if d.get("warehouse"):
				warehouses.add(d.warehouse)

			if self.doctype == "Stock Entry":
				if d.get("s_warehouse"):
					warehouses.add(d.s_warehouse)
				if d.get("t_warehouse"):
					warehouses.add(d.t_warehouse)

		return list(items), list(warehouses)

	def get_stock_ledger_details(self):
		stock_ledger = {}

		table = frappe.qb.DocType("Stock Ledger Entry")

		stock_ledger_entries = (
			frappe.qb.from_(table)
			.select(
				table.name,
				table.warehouse,
				table.stock_value_difference,
				table.valuation_rate,
				table.voucher_detail_no,
				table.item_code,
				table.posting_date,
				table.posting_time,
				table.actual_qty,
				table.qty_after_transaction,
				table.project,
			)
			.where(
				(table.voucher_type == self.doctype)
				& (table.voucher_no == self.name)
				& (table.is_cancelled == 0)
			)
		).run(as_dict=True)

		for sle in stock_ledger_entries:
			stock_ledger.setdefault(sle.voucher_detail_no, []).append(sle)

		return stock_ledger

	def check_expense_account(self, item):
		if not item.get("expense_account"):
			msg = _("Please set an Expense Account in the Items table")
			frappe.throw(
				_("Row #{0}: Expense Account not set for the Item {1}. {2}").format(
					item.idx, frappe.bold(item.item_code), msg
				),
				title=_("Expense Account Missing"),
			)

		else:
			is_expense_account = (
				frappe.get_cached_value("Account", item.get("expense_account"), "report_type")
				== "Profit and Loss"
			)
			if (
				self.doctype
				not in (
					"Purchase Receipt",
					"Purchase Invoice",
					"Stock Reconciliation",
					"Stock Entry",
				)
				and not is_expense_account
			):
				frappe.throw(
					_("Expense / Difference account ({0}) must be a 'Profit or Loss' account").format(
						item.get("expense_account")
					)
				)
			if is_expense_account and not item.get("cost_center"):
				frappe.throw(
					_("{0} {1}: Cost Center is mandatory for Item {2}").format(
						_(self.doctype), self.name, item.get("item_code")
					)
				)

	def delete_auto_created_batches(self):
		for table_name in ["items", "packed_items"]:
			if not self.get(table_name):
				continue

			for row in self.get(table_name):
				update_values = {}
				if row.get("batch_no"):
					update_values["batch_no"] = None

				if row.get("serial_and_batch_bundle"):
					update_values["serial_and_batch_bundle"] = None
					frappe.db.set_value(
						"Serial and Batch Bundle", row.serial_and_batch_bundle, {"is_cancelled": 1}
					)

					frappe.db.set_value(
						"Serial and Batch Entry", {"parent": row.serial_and_batch_bundle}, {"is_cancelled": 1}
					)

				if update_values:
					row.db_set(update_values)

				if table_name == "items" and row.get("rejected_serial_and_batch_bundle"):
					frappe.db.set_value(
						"Serial and Batch Bundle", row.rejected_serial_and_batch_bundle, {"is_cancelled": 1}
					)

					frappe.db.set_value(
						"Serial and Batch Entry",
						{"parent": row.rejected_serial_and_batch_bundle},
						{"is_cancelled": 1},
					)

					row.db_set("rejected_serial_and_batch_bundle", None)

				if row.get("current_serial_and_batch_bundle"):
					row.db_set("current_serial_and_batch_bundle", None)

	def set_serial_and_batch_bundle(self, table_name=None, ignore_validate=False):
		if not table_name:
			table_name = "items"

		QTY_FIELD = {
			"serial_and_batch_bundle": "qty",
			"current_serial_and_batch_bundle": "current_qty",
			"rejected_serial_and_batch_bundle": "rejected_qty",
		}

		for row in self.get(table_name):
			for field in QTY_FIELD.keys():
				if row.get(field):
					frappe.get_doc("Serial and Batch Bundle", row.get(field)).set_serial_and_batch_values(
						self, row, qty_field=QTY_FIELD[field]
					)

	def make_package_for_transfer(
		self,
		serial_and_batch_bundle,
		warehouse,
		type_of_transaction=None,
		do_not_submit=None,
		qty=0,
		include_bundle=None,
		exclude_serial_nos=None,
		total_qty=0,
	):
		return make_bundle_for_material_transfer(
			is_new=self.is_new(),
			docstatus=self.docstatus,
			voucher_type=self.doctype,
			voucher_no=self.name,
			serial_and_batch_bundle=serial_and_batch_bundle,
			warehouse=warehouse,
			type_of_transaction=type_of_transaction,
			do_not_submit=do_not_submit,
			qty=qty,
			include_bundle=include_bundle,
			exclude_serial_nos=exclude_serial_nos,
			total_qty=total_qty,
		)

	def get_sl_entries(self, d, args):
		sl_dict = frappe._dict(
			{
				"item_code": d.get("item_code", None),
				"warehouse": d.get("warehouse", None),
				"serial_and_batch_bundle": d.get("serial_and_batch_bundle"),
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"fiscal_year": get_fiscal_year(self.posting_date, company=self.company)[0],
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"voucher_detail_no": d.name,
				"actual_qty": (self.docstatus == 1 and 1 or -1) * flt(d.get("stock_qty")),
				"stock_uom": frappe.get_cached_value(
					"Item", args.get("item_code") or d.get("item_code"), "stock_uom"
				),
				"incoming_rate": 0,
				"company": self.company,
				"project": d.get("project") or self.get("project"),
				"is_cancelled": 1 if self.docstatus == 2 else 0,
			}
		)

		sl_dict.update(args)
		self.update_inventory_dimensions(d, sl_dict)

		if self.docstatus == 2:
			from hisaabdari.deprecation_dumpster import deprecation_warning

			deprecation_warning("unknown", "v16", "No instructions.")
			# To handle denormalized serial no records, will br deprecated in v16
			for field in ["serial_no", "batch_no"]:
				if d.get(field):
					sl_dict[field] = d.get(field)

		return sl_dict

	def validate_inventory_dimension_mandatory(self):
		# Mandatory inventory dimensions are enforced here (instead of via field-level `reqd`)
		# so we can skip service rows and never block a document that is being cancelled.
		if self.docstatus >= 2:
			return

		for table_field in ["items", "packed_items"]:
			rows = self.get(table_field)
			if rows:
				self.validate_mandatory_dimensions_in_table(rows)

	def validate_mandatory_dimensions_in_table(self, rows):
		child_doctype = rows[0].doctype
		dimensions = get_mandatory_inventory_dimensions(child_doctype)
		if not dimensions:
			return

		child_meta = frappe.get_meta(child_doctype)
		for dimension in dimensions:
			mandatory_fields = get_mandatory_dimension_fields(child_doctype, dimension)
			for row in rows:
				if mandatory_fields and not self.is_service_item_row(row):
					self.validate_mandatory_dimension_row(row, dimension, mandatory_fields, child_meta)

	def is_service_item_row(self, row) -> bool:
		item_code = row.get("item_code")
		return bool(item_code) and not frappe.get_cached_value("Item", item_code, "is_stock_item")

	def validate_mandatory_dimension_row(self, row, dimension, mandatory_fields, child_meta):
		for fieldname, condition in mandatory_fields:
			if not child_meta.has_field(fieldname) or row.get(fieldname):
				continue

			if condition and not frappe.safe_eval(condition, {"doc": row, "parent": self}):
				continue

			frappe.throw(
				_("Row #{0}: {1} is mandatory for the Inventory Dimension {2}.").format(
					row.idx,
					bold(_(child_meta.get_label(fieldname))),
					bold(dimension.name),
				)
			)

	def update_inventory_dimensions(self, row, sl_dict) -> None:
		# To handle delivery note and sales invoice
		if row.get("item_row"):
			row = row.get("item_row")

		dimensions = get_evaluated_inventory_dimension(row, sl_dict, parent_doc=self)
		for dimension in dimensions:
			if not dimension:
				continue

			if (
				self.doctype in ["Purchase Invoice", "Purchase Receipt"]
				and row.get("rejected_warehouse")
				and sl_dict.get("warehouse") == row.get("rejected_warehouse")
			):
				fieldname = f"rejected_{dimension.source_fieldname}"
				sl_dict[dimension.target_fieldname] = row.get(fieldname)
				continue

			if self.doctype in [
				"Purchase Invoice",
				"Purchase Receipt",
				"Sales Invoice",
				"Delivery Note",
				"Stock Entry",
			]:
				if (
					(
						sl_dict.actual_qty > 0
						and not self.get("is_return")
						or sl_dict.actual_qty < 0
						and self.get("is_return")
					)
					and self.doctype in ["Purchase Invoice", "Purchase Receipt", "Stock Entry"]
				) or (
					(
						sl_dict.actual_qty < 0
						and not self.get("is_return")
						or sl_dict.actual_qty > 0
						and self.get("is_return")
					)
					and self.doctype in ["Sales Invoice", "Delivery Note", "Stock Entry"]
				):
					if self.doctype == "Stock Entry":
						if row.get("t_warehouse") == sl_dict.warehouse and sl_dict.get("actual_qty") > 0:
							fieldname = f"to_{dimension.source_fieldname}"
							if dimension.source_fieldname.startswith("to_"):
								fieldname = f"{dimension.source_fieldname}"

							sl_dict[dimension.target_fieldname] = row.get(fieldname)
							continue

					sl_dict[dimension.target_fieldname] = row.get(dimension.source_fieldname)
				else:
					fieldname_start_with = "to"
					if self.doctype in ["Purchase Invoice", "Purchase Receipt"]:
						fieldname_start_with = "from"

					fieldname = f"{fieldname_start_with}_{dimension.source_fieldname}"
					sl_dict[dimension.target_fieldname] = row.get(fieldname)

					if not sl_dict.get(dimension.target_fieldname):
						sl_dict[dimension.target_fieldname] = row.get(dimension.source_fieldname)

			elif row.get(dimension.source_fieldname):
				sl_dict[dimension.target_fieldname] = row.get(dimension.source_fieldname)

			if not sl_dict.get(dimension.target_fieldname) and dimension.fetch_from_parent:
				sl_dict[dimension.target_fieldname] = self.get(dimension.fetch_from_parent)

				# Get value based on doctype name
				if not sl_dict.get(dimension.target_fieldname):
					fieldname = next(
						(
							field.fieldname
							for field in frappe.get_meta(self.doctype).fields
							if field.options == dimension.fetch_from_parent
						),
						None,
					)

					if fieldname and self.get(fieldname):
						sl_dict[dimension.target_fieldname] = self.get(fieldname)

				if sl_dict[dimension.target_fieldname] and self.docstatus == 1:
					row.db_set(dimension.source_fieldname, sl_dict[dimension.target_fieldname])

	def make_sl_entries(self, sl_entries, allow_negative_stock=False, via_landed_cost_voucher=False):
		from hisaabdari.stock.serial_batch_bundle import update_batch_qty
		from hisaabdari.stock.stock_ledger import make_sl_entries

		make_sl_entries(sl_entries, allow_negative_stock, via_landed_cost_voucher)
		update_batch_qty(
			self.doctype, self.name, self.docstatus, via_landed_cost_voucher=via_landed_cost_voucher
		)

	def make_gl_entries_on_cancel(self, from_repost=False):
		if not from_repost:
			cancel_exchange_gain_loss_journal(frappe._dict(doctype=self.doctype, name=self.name))
		if frappe.db.sql(
			"""select name from `tabGL Entry` where voucher_type=%s
			and voucher_no=%s""",
			(self.doctype, self.name),
		):
			self.make_gl_entries()

	def get_serialized_items(self):
		serialized_items = []
		item_codes = list(set(d.item_code for d in self.get("items")))
		if item_codes:
			serialized_items = frappe.db.sql_list(
				"""select name from `tabItem`
				where has_serial_no=1 and name in ({})""".format(", ".join(["%s"] * len(item_codes))),
				tuple(item_codes),
			)

		return serialized_items

	def validate_warehouse(self):
		from hisaabdari.stock.utils import validate_disabled_warehouse, validate_warehouse_company

		warehouses = list(set(d.warehouse for d in self.get("items") if getattr(d, "warehouse", None)))

		target_warehouses = list(
			set([d.target_warehouse for d in self.get("items") if getattr(d, "target_warehouse", None)])
		)

		warehouses.extend(target_warehouses)

		from_warehouse = list(
			set([d.from_warehouse for d in self.get("items") if getattr(d, "from_warehouse", None)])
		)

		warehouses.extend(from_warehouse)

		for w in warehouses:
			validate_disabled_warehouse(w)
			validate_warehouse_company(w, self.company)

	def update_billing_percentage(self, update_modified=True):
		target_ref_field = "amount"
		if self.doctype == "Delivery Note":
			total_amount = total_returned = 0
			for item in self.items:
				total_amount += flt(item.amount)
				total_returned += flt(item.returned_qty * item.rate)

			if total_returned < total_amount:
				target_ref_field = {"SUB": ["amount", {"MUL": ["returned_qty", "rate"]}], "as": "ref_amount"}

		self._update_percent_field(
			{
				"target_dt": self.doctype + " Item",
				"target_parent_dt": self.doctype,
				"target_parent_field": "per_billed",
				"target_ref_field": target_ref_field,
				"target_field": "billed_amt",
				"name": self.name,
			},
			update_modified,
		)

	def validate_customer_provided_item(self):
		for d in self.get("items"):
			# Customer Provided parts will have zero valuation rate
			if frappe.get_cached_value("Item", d.item_code, "is_customer_provided_item"):
				d.allow_zero_valuation_rate = 1

	def set_rate_of_stock_uom(self):
		if self.doctype in [
			"Purchase Receipt",
			"Purchase Invoice",
			"Purchase Order",
			"Sales Invoice",
			"Sales Order",
			"Delivery Note",
			"Quotation",
		]:
			for d in self.get("items"):
				d.stock_uom_rate = d.rate / (d.conversion_factor or 1)

	def validate_internal_transfer(self):
		if self.doctype in ("Sales Invoice", "Delivery Note", "Purchase Invoice", "Purchase Receipt"):
			if self.is_internal_transfer():
				self.validate_in_transit_warehouses()
				self.validate_multi_currency()
				self.validate_packed_items()

				if self.get("is_internal_supplier") and self.docstatus == 1 and not self.get("is_return"):
					self.validate_internal_transfer_qty()
			else:
				self.validate_internal_transfer_warehouse()

	def validate_internal_transfer_warehouse(self):
		for row in self.items:
			if row.get("target_warehouse"):
				row.target_warehouse = None

			if row.get("from_warehouse"):
				row.from_warehouse = None

	def validate_in_transit_warehouses(self):
		# a draft saved with ignore_mandatory gets its warehouses before submit
		if self.docstatus == 0 and self.flags.ignore_mandatory:
			return

		if (self.doctype == "Sales Invoice" and self.get("update_stock")) or self.doctype == "Delivery Note":
			for item in self.get("items"):
				if not item.target_warehouse:
					frappe.throw(
						_("Row {0}: Target Warehouse is mandatory for internal transfers").format(item.idx)
					)

		if (
			self.doctype == "Purchase Invoice" and self.get("update_stock")
		) or self.doctype == "Purchase Receipt":
			for item in self.get("items"):
				if not item.from_warehouse:
					frappe.throw(
						_("Row {0}: From Warehouse is mandatory for internal transfers").format(item.idx)
					)

	def validate_multi_currency(self):
		if self.currency != self.company_currency:
			frappe.throw(_("Internal transfers can only be done in company's default currency"))

	def validate_packed_items(self):
		if self.doctype == "Sales Invoice" and self.get("packed_items"):
			frappe.throw(_("Packed Items cannot be transferred internally"))

	def validate_internal_transfer_qty(self):
		if self.doctype not in ["Purchase Invoice", "Purchase Receipt"]:
			return

		self.__inter_company_reference = self.get_inter_company_reference()

		item_wise_transfer_qty = self.get_item_wise_inter_transfer_qty()
		if not item_wise_transfer_qty:
			return

		item_wise_received_qty = self.get_item_wise_inter_received_qty()
		precision = frappe.get_precision(self.doctype + " Item", "qty")

		over_receipt_allowance = frappe.get_single_value("Stock Settings", "over_delivery_receipt_allowance")

		parent_doctype = {
			"Purchase Receipt": "Delivery Note",
			"Purchase Invoice": "Sales Invoice",
		}.get(self.doctype)

		for key, transferred_qty in item_wise_transfer_qty.items():
			recevied_qty = flt(item_wise_received_qty.get(key), precision)
			if over_receipt_allowance:
				transferred_qty = transferred_qty + flt(
					transferred_qty * over_receipt_allowance / 100, precision
				)

			if recevied_qty > flt(transferred_qty, precision):
				from hisaabdari.controllers.status_updater import OverAllowanceError

				frappe.throw(
					_("For Item {0} cannot be received more than {1} qty against the {2} {3}").format(
						bold(key[1]),
						bold(flt(transferred_qty, precision)),
						bold(parent_doctype),
						get_link_to_form(parent_doctype, self.__inter_company_reference),
					),
					OverAllowanceError,
				)

	def get_inter_company_reference(self):
		if self.doctype == "Purchase Receipt":
			return self.get("inter_company_reference")

		if self.get("is_return"):
			return frappe.db.get_value(
				"Purchase Invoice", self.return_against, "inter_company_invoice_reference"
			)

		return self.get("inter_company_invoice_reference")

	def get_item_wise_inter_transfer_qty(self):
		parent_doctype = {
			"Purchase Receipt": "Delivery Note",
			"Purchase Invoice": "Sales Invoice",
		}.get(self.doctype)

		child_doctype = parent_doctype + " Item"

		parent_tab = frappe.qb.DocType(parent_doctype)
		child_tab = frappe.qb.DocType(child_doctype)

		query = (
			frappe.qb.from_(parent_doctype)
			.inner_join(child_tab)
			.on(child_tab.parent == parent_tab.name)
			.select(
				child_tab.name,
				child_tab.item_code,
				child_tab.qty,
			)
			.where((parent_tab.name == self.__inter_company_reference) & (parent_tab.docstatus == 1))
		)
		if parent_doctype == "Delivery Note":
			query = query.select(child_tab.returned_qty, child_tab.stock_qty, child_tab.conversion_factor)

		data = query.run(as_dict=True)
		item_wise_transfer_qty = defaultdict(float)
		for row in data:
			returned_qty = flt(row.get("returned_qty")) / (flt(row.get("conversion_factor")) or 1)
			item_wise_transfer_qty[(row.name, row.item_code)] += flt(row.qty) - returned_qty

		if parent_doctype == "Delivery Note":
			self.add_component_transfer_qty(item_wise_transfer_qty, self.__inter_company_reference, data)

		return item_wise_transfer_qty

	def add_component_transfer_qty(self, item_wise_transfer_qty, delivery_note, bundle_rows):
		from hisaabdari.stock.doctype.delivery_note.delivery_note import get_pending_component_qty

		bundle_rows = {row.name: row for row in bundle_rows}
		for packed in frappe.get_all(
			"Packed Item",
			filters={"parent": delivery_note, "parenttype": "Delivery Note"},
			fields=["name", "item_code", "qty", "parent_detail_docname"],
		):
			if bundle_row := bundle_rows.get(packed.parent_detail_docname):
				item_wise_transfer_qty.pop((bundle_row.name, bundle_row.item_code), None)
				item_wise_transfer_qty[(packed.name, packed.item_code)] += get_pending_component_qty(
					packed, bundle_row
				)

	def get_item_wise_inter_received_qty(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import get_inter_company_items

		if self.doctype == "Purchase Invoice":
			reference_field, item_reference_field = "inter_company_invoice_reference", "sales_invoice_item"
			fields = ["item_code", "qty"]
		else:
			reference_field, item_reference_field = "inter_company_reference", "delivery_note_item"
			fields = ["item_code", "qty", "delivery_note_packed_item"]

		other_items = get_inter_company_items(
			self.doctype,
			{reference_field: self.__inter_company_reference, "name": ("!=", self.name)},
			item_reference_field,
			fields,
		)

		# a cancelled document no longer counts
		own_items = self.items if self.docstatus == 1 else []
		item_wise_received_qty = defaultdict(float)
		for row in [*other_items, *own_items]:
			reference = row.get("delivery_note_packed_item") or row.get(item_reference_field)
			item_wise_received_qty[(reference, row.item_code)] += flt(row.qty)

		return item_wise_received_qty

	def repost_future_sle_and_gle(self, force=False, via_landed_cost_voucher=False):
		args = frappe._dict(
			{
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"company": self.company,
				"via_landed_cost_voucher": via_landed_cost_voucher,
			}
		)

		if self.docstatus == 2:
			# nothing to repost when the cancelled voucher never touched the stock ledger
			if not frappe.db.exists(
				"Stock Ledger Entry", {"voucher_type": self.doctype, "voucher_no": self.name}
			):
				return
			force = True

		if force or future_sle_exists(args, for_update=True) or repost_required_for_queue(self):
			item_based_reposting = frappe.get_single_value("Stock Reposting Settings", "item_based_reposting")
			if item_based_reposting:
				create_item_wise_repost_entries(
					voucher_type=self.doctype,
					voucher_no=self.name,
					via_landed_cost_voucher=via_landed_cost_voucher,
				)
			else:
				create_repost_item_valuation_entry(args)

	def add_gl_entry(
		self,
		gl_entries,
		account,
		cost_center,
		debit,
		credit,
		remarks,
		against_account,
		debit_in_account_currency=None,
		credit_in_account_currency=None,
		account_currency=None,
		project=None,
		voucher_detail_no=None,
		item=None,
		posting_date=None,
		dimensions=None,
	):
		gl_entry = {
			"account": account,
			"cost_center": cost_center,
			"debit": debit,
			"credit": credit,
			"against": against_account,
			"remarks": remarks,
		}

		if project:
			gl_entry.update({"project": project})

		if voucher_detail_no:
			gl_entry.update({"voucher_detail_no": voucher_detail_no})

		if debit_in_account_currency:
			gl_entry.update({"debit_in_account_currency": debit_in_account_currency})

		if credit_in_account_currency:
			gl_entry.update({"credit_in_account_currency": credit_in_account_currency})

		if posting_date:
			gl_entry.update({"posting_date": posting_date})

		if dimensions:
			gl_entry.update(dimensions)

		gl_entries.append(self.get_gl_dict(gl_entry, item=item))

	def check_for_on_hold_or_closed_status(
		self, ref_doctype: str, ref_fieldname: str, exclude_if_field: str | None = None
	) -> None:
		def _include(d):
			return d.get(ref_fieldname) and not (exclude_if_field and d.get(exclude_if_field))

		included = [(d, d.get(ref_fieldname)) for d in self.get("items") if _include(d)]
		if not included:
			return

		status_map = {
			r.name: r.status
			for r in frappe.get_all(
				ref_doctype,
				filters={"name": ["in", {name for _, name in included}]},
				fields=["name", "status"],
			)
		}

		errors = []
		seen = set()
		for _d, ref_name in included:
			if ref_name in seen:
				continue
			seen.add(ref_name)
			if (status := status_map.get(ref_name)) in ("Closed", "On Hold"):
				errors.append(
					_("{ref_doctype} {ref_name} status is {status}.").format(
						ref_doctype=frappe.bold(_(ref_doctype)),
						ref_name=frappe.bold(ref_name),
						status=frappe.bold(_(status)),
					)
				)

		if errors:
			frappe.throw("<br>".join(errors), frappe.InvalidStatusError)


@frappe.whitelist()
def show_accounting_ledger_preview(company: str, doctype: str, docname: str):
	filters = frappe._dict(company=company, include_dimensions=1)
	doc = frappe.get_lazy_doc(doctype, docname)
	doc.check_permission("read")
	frappe.has_permission("GL Entry", "read", throw=True)
	doc.run_method("before_gl_preview")

	gl_columns, gl_data = get_accounting_ledger_preview(doc, filters)

	frappe.db.rollback()

	return {"gl_columns": gl_columns, "gl_data": gl_data}


@frappe.whitelist()
def show_stock_ledger_preview(company: str, doctype: str, docname: str):
	filters = frappe._dict(company=company, valuation_field_type="Currency")
	doc = frappe.get_lazy_doc(doctype, docname)
	doc.check_permission("read")
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	doc.run_method("before_sl_preview")

	sl_columns, sl_data = get_stock_ledger_preview(doc, filters)

	frappe.db.rollback()

	return {
		"sl_columns": sl_columns,
		"sl_data": sl_data,
	}


def get_accounting_ledger_preview(doc, filters):
	from hisaabdari.accounts.report.general_ledger.general_ledger import get_columns as get_gl_columns

	gl_columns, gl_data = [], []
	fields = [
		"posting_date",
		"account",
		"debit",
		"credit",
		"against",
		"party_type",
		"party",
		"cost_center",
		"against_voucher_type",
		"against_voucher",
	]

	doc.docstatus = 1

	if doc.get("update_stock") or doc.doctype in ("Purchase Receipt", "Delivery Note", "Stock Entry"):
		make_serial_and_batch_bundles_for_preview(doc)
		doc.update_stock_ledger()

	doc.make_gl_entries()
	columns = get_gl_columns(filters)
	masked_fields = frappe.get_meta("GL Entry").get_masked_fields()
	gl_entries = mask_dict_results(get_gl_entries_for_preview(doc.doctype, doc.name, fields), masked_fields)

	gl_columns = get_columns(columns, fields, hisaabdari.get_company_currency(filters.company), masked_fields)
	gl_data = get_data(fields, gl_entries)

	return gl_columns, gl_data


def get_stock_ledger_preview(doc, filters):
	from hisaabdari.stock.report.stock_ledger.stock_ledger import get_columns as get_sl_columns

	sl_columns, sl_data = [], []
	fields = [
		"item_code",
		"stock_uom",
		"actual_qty",
		"qty_after_transaction",
		"warehouse",
		"incoming_rate",
		"valuation_rate",
		"stock_value",
		"stock_value_difference",
	]
	columns_fields = [
		"item_code",
		"stock_uom",
		"in_qty",
		"out_qty",
		"qty_after_transaction",
		"warehouse",
		"incoming_rate",
		"in_out_rate",
		"stock_value",
		"stock_value_difference",
	]

	if doc.get("update_stock") or doc.doctype in ("Purchase Receipt", "Delivery Note", "Stock Entry"):
		doc.docstatus = 1
		make_serial_and_batch_bundles_for_preview(doc)
		doc.update_stock_ledger()

		columns = get_sl_columns(filters)
		masked_fields = frappe.get_meta("Stock Ledger Entry").get_masked_fields()
		sl_entries = mask_dict_results(
			get_sl_entries_for_preview(doc.doctype, doc.name, fields), masked_fields
		)

		sl_columns = get_columns(
			columns, columns_fields, hisaabdari.get_company_currency(filters.company), masked_fields
		)
		sl_data = get_data(columns_fields, sl_entries)

	return sl_columns, sl_data


def make_serial_and_batch_bundles_for_preview(doc):
	for table_name in ("items", "packed_items"):
		if doc.get(table_name):
			# a return takes back the serial / batch nos of the original voucher, as on submit
			doc.make_bundle_for_sales_purchase_return(table_name)
			doc.make_bundle_using_old_serial_batch_fields(table_name)


def get_sl_entries_for_preview(doctype, docname, fields):
	sl_entries = frappe.get_all(
		"Stock Ledger Entry", filters={"voucher_type": doctype, "voucher_no": docname}, fields=fields
	)

	for entry in sl_entries:
		if entry.actual_qty > 0:
			entry["in_qty"] = entry.actual_qty
			entry["out_qty"] = 0
		else:
			entry["out_qty"] = abs(entry.actual_qty)
			entry["in_qty"] = 0

		if entry.actual_qty < 0:
			entry["in_out_rate"] = entry.stock_value_difference / entry.actual_qty

	return sl_entries


def get_gl_entries_for_preview(doctype, docname, fields):
	return frappe.get_all("GL Entry", filters={"voucher_type": doctype, "voucher_no": docname}, fields=fields)


def get_columns(raw_columns, fields, currency, masked_fields):
	masked_fieldnames = {df.fieldname for df in masked_fields}
	columns = []
	for source_column in raw_columns:
		fieldname = source_column.get("fieldname")
		if source_column.get("hidden") or fieldname not in fields:
			continue

		column = {
			"name": source_column.get("label"),
			"editable": False,
			"width": 110,
			# masked values are placeholder text, not numbers
			"fieldtype": "Data" if fieldname in masked_fieldnames else source_column.get("fieldtype"),
		}
		if column["fieldtype"] == "Currency":
			column["options"] = currency
		columns.append(column)

	return columns


def get_data(raw_columns, raw_data):
	datatable_data = []
	for row in raw_data:
		data_row = []
		for column in raw_columns:
			data_row.append(row.get(column) or "")

		datatable_data.append(data_row)

	return datatable_data


def repost_required_for_queue(doc: StockController) -> bool:
	"""check if stock document contains repeated item-warehouse with queue based valuation.

	if queue exists for repeated items then SLEs need to reprocessed in background again.
	"""

	consuming_sles = frappe.db.get_all(
		"Stock Ledger Entry",
		filters={
			"voucher_type": doc.doctype,
			"voucher_no": doc.name,
			"actual_qty": ("<", 0),
			"is_cancelled": 0,
		},
		fields=["item_code", "warehouse", "stock_queue"],
	)
	item_warehouses = [(sle.item_code, sle.warehouse) for sle in consuming_sles]

	unique_item_warehouses = set(item_warehouses)

	if len(unique_item_warehouses) == len(item_warehouses):
		return False

	for sle in consuming_sles:
		if sle.stock_queue != "[]":  # using FIFO/LIFO valuation
			return True
	return False


def is_reposting_pending():
	return frappe.db.exists(
		"Repost Item Valuation", {"docstatus": 1, "status": ["in", ["Queued", "In Progress"]]}
	)


def invalidate_future_sle_cache(voucher_type, voucher_no):
	if hasattr(frappe.local, "future_sle"):
		frappe.local.future_sle.pop((voucher_type, voucher_no), None)


def future_sle_exists(args, sl_entries=None, for_update=False):
	from hisaabdari.stock.utils import get_combine_datetime

	key = (args.voucher_type, args.voucher_no)
	if not hasattr(frappe.local, "future_sle"):
		frappe.local.future_sle = {}

	# The locking read neither uses nor fills the cache: a cached result may come from a plain
	# read that predates a concurrent later-posted SLE.
	if not for_update:
		if validate_future_sle_not_exists(args, key, sl_entries):
			return False
		elif get_cached_data(args, key):
			return True

	if not sl_entries:
		sl_entries = get_sle_entries_against_voucher(args)
		if not sl_entries:
			return

	or_conditions = get_conditions_to_validate_future_sle(sl_entries)

	args["posting_datetime"] = get_combine_datetime(args["posting_date"], args["posting_time"])

	sle = frappe.qb.DocType("Stock Ledger Entry")
	query = (
		frappe.qb.from_(sle)
		.select(sle.item_code, sle.warehouse, Count(sle.name).as_("total_row"))
		.where(
			Criterion.any(or_conditions)
			& (sle.posting_datetime >= args["posting_datetime"])
			& (sle.voucher_no != args["voucher_no"])
			& (sle.is_cancelled == 0)
		)
		.groupby(sle.item_code, sle.warehouse)
	)

	# A plain read uses the transaction's snapshot, which can predate a later-posted SLE that a
	# concurrent submit committed meanwhile; this voucher would then skip the repost it needs.
	# A locking read sees the latest committed rows and waits on uncommitted ones. Only the final
	# repost decision asks for it: by then this voucher already holds these ranges, whereas an
	# upfront lock over every item-warehouse pair deadlocks with concurrent submits.
	if for_update and frappe.db.db_type == "mariadb":
		query = query.for_update()

	data = query.run(as_dict=1)

	if not for_update:
		for d in data:
			frappe.local.future_sle[key][(d.item_code, d.warehouse)] = d.total_row

	return len(data)


def validate_future_sle_not_exists(args, key, sl_entries=None):
	item_key = ""
	if args.get("item_code"):
		item_key = (args.get("item_code"), args.get("warehouse"))

	if not sl_entries and hasattr(frappe.local, "future_sle"):
		if key not in frappe.local.future_sle:
			return False

		if not frappe.local.future_sle.get(key) or (
			item_key and item_key not in frappe.local.future_sle.get(key)
		):
			return True


def get_cached_data(args, key):
	if key not in frappe.local.future_sle:
		frappe.local.future_sle[key] = frappe._dict({})

	if args.get("item_code"):
		item_key = (args.get("item_code"), args.get("warehouse"))
		count = frappe.local.future_sle[key].get(item_key)

		return True if (count or count == 0) else False
	else:
		return frappe.local.future_sle[key]


def get_sle_entries_against_voucher(args):
	return frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": args.voucher_type, "voucher_no": args.voucher_no},
		fields=["item_code", "warehouse"],
		order_by="creation asc",
	)


def get_conditions_to_validate_future_sle(sl_entries):
	warehouse_items_map = {}
	for entry in sl_entries:
		if entry.warehouse not in warehouse_items_map:
			warehouse_items_map[entry.warehouse] = set()

		warehouse_items_map[entry.warehouse].add(entry.item_code)

	sle = frappe.qb.DocType("Stock Ledger Entry")
	or_conditions = []
	for warehouse, items in warehouse_items_map.items():
		or_conditions.append((sle.warehouse == warehouse) & sle.item_code.isin(list(items)))

	return or_conditions


def create_repost_item_valuation_entry(args):
	args = frappe._dict(args)
	repost_entry = frappe.new_doc("Repost Item Valuation")
	repost_entry.based_on = args.based_on
	if not args.based_on:
		repost_entry.based_on = "Transaction" if args.voucher_no else "Item and Warehouse"
	repost_entry.voucher_type = args.voucher_type
	repost_entry.voucher_no = args.voucher_no
	repost_entry.item_code = args.item_code
	repost_entry.warehouse = args.warehouse
	repost_entry.posting_date = args.posting_date
	repost_entry.posting_time = args.posting_time
	repost_entry.company = args.company
	repost_entry.allow_zero_rate = args.allow_zero_rate
	repost_entry.flags.ignore_links = True
	repost_entry.flags.ignore_permissions = True
	repost_entry.via_landed_cost_voucher = args.via_landed_cost_voucher
	repost_entry.save()
	repost_entry.submit()


def create_item_wise_repost_entries(
	voucher_type, voucher_no, allow_zero_rate=False, via_landed_cost_voucher=False
):
	"""Using a voucher create repost item valuation records for all item-warehouse pairs."""

	stock_ledger_entries = get_items_to_be_repost(voucher_type, voucher_no)

	distinct_item_warehouses = set()
	repost_entries = []

	for sle in stock_ledger_entries:
		item_wh = (sle.item_code, sle.warehouse)
		if item_wh in distinct_item_warehouses:
			continue
		distinct_item_warehouses.add(item_wh)

		repost_entry = frappe.new_doc("Repost Item Valuation")
		repost_entry.based_on = "Item and Warehouse"

		repost_entry.item_code = sle.item_code
		repost_entry.warehouse = sle.warehouse
		repost_entry.posting_date = sle.posting_date
		repost_entry.posting_time = sle.posting_time
		repost_entry.allow_zero_rate = allow_zero_rate
		repost_entry.flags.ignore_links = True
		repost_entry.flags.ignore_permissions = True
		repost_entry.via_landed_cost_voucher = via_landed_cost_voucher
		repost_entry.submit()
		repost_entries.append(repost_entry)

	return repost_entries


def make_bundle_for_material_transfer(**kwargs):
	if isinstance(kwargs, dict):
		kwargs = frappe._dict(kwargs)

	bundle_doc = frappe.get_doc("Serial and Batch Bundle", kwargs.serial_and_batch_bundle)

	if not kwargs.type_of_transaction:
		kwargs.type_of_transaction = "Inward"

	bundle_doc = frappe.copy_doc(bundle_doc)
	bundle_doc.docstatus = 0
	bundle_doc.warehouse = kwargs.warehouse
	bundle_doc.type_of_transaction = kwargs.type_of_transaction
	bundle_doc.voucher_type = kwargs.voucher_type
	bundle_doc.voucher_no = "" if kwargs.is_new or kwargs.docstatus == 2 else kwargs.voucher_no
	bundle_doc.is_cancelled = 0

	if kwargs.include_bundle:
		for entry in frappe.get_doc("Serial and Batch Bundle", kwargs.include_bundle).entries:
			bundle_doc.append("entries", entry.as_dict(no_default_fields=True))

	if kwargs.exclude_serial_nos:
		keep = [row for row in bundle_doc.entries if row.serial_no not in set(kwargs.exclude_serial_nos)]
		bundle_doc.entries = keep
		for idx, row in enumerate(keep, start=1):
			row.idx = idx

	qty = 0
	if (
		len(bundle_doc.entries) == 1
		and abs(flt(kwargs.qty)) < abs(flt(bundle_doc.total_qty))
		and not bundle_doc.has_serial_no
	):
		qty = kwargs.qty

	if kwargs.total_qty and not bundle_doc.has_serial_no:
		set_entries_total_qty(bundle_doc.entries, kwargs.total_qty)

	for row in bundle_doc.entries:
		row.is_outward = 0
		row.qty = abs(qty or row.qty)
		row.stock_value_difference = abs(row.stock_value_difference)
		if kwargs.type_of_transaction == "Outward":
			row.qty *= -1
			row.stock_value_difference *= -1
			row.is_outward = 1

		row.warehouse = kwargs.warehouse
		row.posting_datetime = bundle_doc.posting_datetime
		row.voucher_type = bundle_doc.voucher_type
		row.voucher_no = bundle_doc.voucher_no
		row.voucher_detail_no = bundle_doc.voucher_detail_no
		row.type_of_transaction = bundle_doc.type_of_transaction
		row.item_code = bundle_doc.item_code

	bundle_doc.set_incoming_rate()
	bundle_doc.calculate_qty_and_amount()
	bundle_doc.flags.ignore_permissions = True
	bundle_doc.flags.ignore_validate = True
	if kwargs.do_not_submit:
		bundle_doc.save(ignore_permissions=True)
	else:
		bundle_doc.submit()
		if kwargs.docstatus != 2:
			bundle_doc.check_future_entries_exists()

	return bundle_doc.name


def set_entries_total_qty(entries, total_qty):
	"""Let the last entry take the difference, so the entries add up to the stock qty the voucher posts."""
	entries[-1].qty = abs(flt(total_qty)) - sum(abs(flt(row.qty)) for row in entries[:-1])


def get_item_wise_inventory_account_map(rows, company):
	# returns dict of item_code and its inventory account details
	# Example: {"ITEM-001": {"account": "Stock - ABC", "account_currency": "INR"}, ...}

	inventory_map = frappe._dict()

	for row in rows:
		item_code = row.rm_item_code if hasattr(row, "rm_item_code") and row.rm_item_code else row.item_code
		if not item_code:
			continue

		if inventory_map.get(item_code):
			continue

		item_defaults = get_item_defaults(item_code, company)
		if item_defaults.default_inventory_account:
			inventory_map[item_code] = frappe._dict(
				{
					"account": item_defaults.default_inventory_account,
					"account_currency": item_defaults.inventory_account_currency,
				}
			)

		if not inventory_map.get(item_code):
			item_group_defaults = get_item_group_defaults(item_code, company)
			if item_group_defaults.default_inventory_account:
				inventory_map[item_code] = frappe._dict(
					{
						"account": item_group_defaults.default_inventory_account,
						"account_currency": item_group_defaults.inventory_account_currency,
					}
				)

	return inventory_map


@frappe.request_cache
def get_expenses_added_to_stock_accounts(item_code, company):
	"""Resolves the Expenses Added To Stock account pair for an item, falling back through
	Item Defaults -> Item Group -> Company."""
	from hisaabdari.setup.doctype.item_group.item_group import get_item_group_defaults
	from hisaabdari.stock.doctype.item.item import get_item_defaults

	fields = ["expenses_added_to_stock_account", "expenses_added_to_stock_contra_account"]
	defaults = get_item_defaults(item_code, company)

	details = frappe._dict({field: defaults.get(field) for field in fields})

	if not details.expenses_added_to_stock_account:
		details = get_item_group_defaults(item_code, company)

	details = frappe._dict({field: details.get(field) for field in fields})
	for field in fields:
		if not details.get(field):
			details[field] = frappe.get_cached_value("Company", company, field)

	return details


def get_unusable_outward_bundle_batches(bundles, posting_date):
	bundle = frappe.qb.DocType("Serial and Batch Bundle")
	entry = frappe.qb.DocType("Serial and Batch Entry")
	batch = frappe.qb.DocType("Batch")

	return (
		frappe.qb.from_(entry)
		.join(bundle)
		.on(entry.parent == bundle.name)
		.join(batch)
		.on(entry.batch_no == batch.name)
		.select(bundle.name.as_("bundle"), entry.batch_no, batch.expiry_date, batch.disabled)
		.where(
			bundle.name.isin(bundles)
			& (bundle.type_of_transaction == "Outward")
			& (unusable_batch_condition(batch, posting_date))
		)
		.run(as_dict=True)
	)


def unusable_batch_condition(batch, posting_date):
	if not posting_date:
		return batch.disabled == 1

	return (batch.expiry_date < getdate(posting_date)) | (batch.disabled == 1)


def add_picked_batches(picked_batches, entries):
	for entry in entries:
		if entry.batch_no:
			picked = picked_batches.setdefault(
				(entry.batch_no, entry.warehouse),
				frappe._dict(batch_no=entry.batch_no, warehouse=entry.warehouse, qty=0),
			)
			picked.qty += entry.qty
