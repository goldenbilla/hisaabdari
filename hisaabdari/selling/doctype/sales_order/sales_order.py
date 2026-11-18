# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
import frappe.utils
from frappe import _, qb
from frappe.contacts.doctype.address.address import get_company_address
from frappe.desk.notifications import clear_doctype_notifications
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.model.utils import get_fetch_values
from frappe.query_builder import Case
from frappe.query_builder.functions import Abs, IfNull, Round, Sum
from frappe.utils import cint, cstr, flt, get_link_to_form, getdate
from pypika import Order

from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import (
	unlink_inter_company_doc,
	update_linked_doc,
	validate_inter_company_party,
)
from hisaabdari.accounts.party import CROSS_PARTY_FIELD_NO_MAP, get_party_account
from hisaabdari.buying.utils import get_qty_to_order
from hisaabdari.controllers.mapper import get_qty_already_mapped
from hisaabdari.controllers.selling_controller import SellingController
from hisaabdari.selling.doctype.customer.customer import (
	check_credit_limit,
	is_sales_order_credit_check_bypassed,
)
from hisaabdari.setup.doctype.item_group.item_group import get_item_group_defaults
from hisaabdari.stock.doctype.item.item import get_item_defaults
from hisaabdari.stock.stock_balance import get_reserved_qty, update_bin_qty

form_grid_templates = {"items": "templates/form_grid/item_grid.html"}

LINK_SEARCH_FIELDTYPES = {
	"Autocomplete",
	"Data",
	"Link",
	"Long Text",
	"Read Only",
	"Select",
	"Small Text",
	"Text",
	"Text Editor",
}


class WarehouseRequired(frappe.ValidationError):
	pass


class SalesOrder(SellingController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from hisaabdari.accounts.doctype.item_wise_tax_detail.item_wise_tax_detail import ItemWiseTaxDetail
		from hisaabdari.accounts.doctype.payment_schedule.payment_schedule import PaymentSchedule
		from hisaabdari.accounts.doctype.sales_taxes_and_charges.sales_taxes_and_charges import (
			SalesTaxesandCharges,
		)
		from hisaabdari.selling.doctype.sales_order_item.sales_order_item import SalesOrderItem
		from hisaabdari.stock.doctype.packed_item.packed_item import PackedItem

		additional_discount_percentage: DF.Float
		address_display: DF.TextEditor | None
		advance_paid: DF.Currency
		advance_payment_status: DF.Literal["Not Requested", "Requested", "Partially Paid", "Fully Paid"]
		amended_from: DF.Link | None
		apply_discount_on: DF.Literal["", "Grand Total", "Net Total"]
		auto_repeat: DF.Link | None
		base_discount_amount: DF.Currency
		base_grand_total: DF.Currency
		base_in_words: DF.Data | None
		base_net_total: DF.Currency
		base_rounded_total: DF.Currency
		base_rounding_adjustment: DF.Currency
		base_total: DF.Currency
		base_total_taxes_and_charges: DF.Currency
		billing_status: DF.Literal["Not Billed", "Fully Billed", "Partly Billed", "Closed"]
		company: DF.Link
		company_address: DF.Link | None
		company_address_display: DF.TextEditor | None
		company_contact_person: DF.Link | None
		contact_display: DF.SmallText | None
		contact_email: DF.Data | None
		contact_mobile: DF.SmallText | None
		contact_person: DF.Link | None
		contact_phone: DF.Data | None
		conversion_rate: DF.Float
		cost_center: DF.Link | None
		currency: DF.Link
		customer: DF.Link
		customer_address: DF.Link | None
		customer_group: DF.Link | None
		customer_name: DF.Data | None
		delivery_date: DF.Date | None
		delivery_status: DF.Literal[
			"Not Delivered", "Fully Delivered", "Partly Delivered", "Closed", "Not Applicable"
		]
		disable_rounded_total: DF.Check
		discount_amount: DF.Currency
		dispatch_address: DF.TextEditor | None
		dispatch_address_name: DF.Link | None
		from_date: DF.Date | None
		grand_total: DF.Currency
		group_same_items: DF.Check
		has_unit_price_items: DF.Check
		ignore_default_payment_terms_template: DF.Check
		ignore_pricing_rule: DF.Check
		in_words: DF.Data | None
		inter_company_order_reference: DF.Link | None
		is_internal_customer: DF.Check
		item_wise_tax_details: DF.Table[ItemWiseTaxDetail]
		items: DF.Table[SalesOrderItem]
		language: DF.Link | None
		letter_head: DF.Link | None
		naming_series: DF.Literal["SAL-ORD-.YYYY.-"]
		net_total: DF.Currency
		order_type: DF.Literal["", "Sales", "Maintenance", "Shopping Cart"]
		other_charges_calculation: DF.TextEditor | None
		packed_items: DF.Table[PackedItem]
		party_account_currency: DF.Link | None
		payment_schedule: DF.Table[PaymentSchedule]
		payment_terms_template: DF.Link | None
		per_billed: DF.Percent
		per_delivered: DF.Percent
		plc_conversion_rate: DF.Float
		po_date: DF.Date | None
		po_no: DF.Data | None
		price_list_currency: DF.Link
		represents_company: DF.Link | None
		rounded_total: DF.Currency
		rounding_adjustment: DF.Currency
		scan_barcode: DF.Data | None
		select_print_heading: DF.Link | None
		selling_price_list: DF.Link
		set_warehouse: DF.Link | None
		shipping_address: DF.TextEditor | None
		shipping_address_name: DF.Link | None
		skip_delivery_note: DF.Check
		status: DF.Literal[
			"",
			"Draft",
			"On Hold",
			"To Pay",
			"To Deliver and Bill",
			"To Bill",
			"To Deliver",
			"Completed",
			"Cancelled",
			"Closed",
		]
		tax_id: DF.Data | None
		taxes: DF.Table[SalesTaxesandCharges]
		taxes_and_charges: DF.Link | None
		tc_name: DF.Link | None
		terms: DF.TextEditor | None
		title: DF.Data | None
		to_date: DF.Date | None
		total: DF.Currency
		total_net_weight: DF.Float
		total_qty: DF.Float
		total_taxes_and_charges: DF.Currency
		transaction_date: DF.Date
		transaction_time: DF.Time | None
		utm_campaign: DF.Link | None
		utm_content: DF.Data | None
		utm_medium: DF.Link | None
		utm_source: DF.Link | None
	# end: auto-generated types

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.status_updater = [
			{
				"source_dt": "Sales Order Item",
				"target_dt": "Quotation Item",
				"join_field": "quotation_item",
				"target_field": "ordered_qty",
				"target_ref_field": "stock_qty",
				"source_field": "stock_qty",
			}
		]

	def onload(self) -> None:
		super().onload()

		if self.docstatus == 1 and self.status not in {"Closed", "On Hold"}:
			self.set_onload(
				"has_potentially_billable_items",
				has_potentially_billable_items(self.name),
			)

	def can_update_items(self) -> bool:
		result = True

		return result

	def before_validate(self):
		self.set_has_unit_price_items()
		self.flags.allow_zero_qty = self.has_unit_price_items

	def validate(self):
		super().validate()
		self.validate_delivery_date()
		self.validate_po()
		self.validate_uom_is_integer("stock_uom", "stock_qty")
		self.validate_uom_is_integer("uom", "qty")
		self.validate_for_items()
		self.validate_warehouse()
		self.validate_drop_ship()
		validate_inter_company_party(
			self.doctype, self.customer, self.company, self.inter_company_order_reference
		)

		self.validate_with_previous_doc()
		self.set_status()

		if not self.billing_status:
			self.billing_status = "Not Billed"
		if not self.delivery_status:
			self.delivery_status = "Not Delivered"
		if not self.advance_payment_status:
			self.advance_payment_status = "Not Requested"

		self.reset_default_field_value("set_warehouse", "items", "warehouse")

	def set_has_unit_price_items(self):
		"""
		If permitted in settings and any item has 0 qty, the SO has unit price items.
		"""
		if not frappe.get_single_value("Selling Settings", "allow_zero_qty_in_sales_order"):
			return

		self.has_unit_price_items = any(
			not row.qty for row in self.get("items") if (row.item_code and not row.qty)
		)

	def validate_po(self):
		# validate p.o date v/s delivery date
		if self.po_date and not self.skip_delivery_note:
			for d in self.get("items"):
				if d.delivery_date and getdate(self.po_date) > getdate(d.delivery_date):
					frappe.throw(
						_("Row #{0}: Expected Delivery Date cannot be before Purchase Order Date").format(
							d.idx
						)
					)

		if self.po_no and self.customer and not self.skip_delivery_note:
			so = frappe.db.sql(
				"select name from `tabSales Order` \
				where ifnull(po_no, '') = %s and name != %s and docstatus < 2\
				and customer = %s",
				(self.po_no, self.name, self.customer),
			)
			if so and so[0][0]:
				if cint(
					frappe.get_single_value("Selling Settings", "allow_against_multiple_purchase_orders")
				):
					frappe.msgprint(
						_(
							"Warning: Sales Order {0} already exists against Customer's Purchase Order {1}"
						).format(frappe.bold(so[0][0]), frappe.bold(self.po_no)),
						alert=True,
					)
				else:
					frappe.throw(
						_(
							"Sales Order {0} already exists against Customer's Purchase Order {1}. To allow multiple Sales Orders, Enable {2} in {3}"
						).format(
							frappe.bold(so[0][0]),
							frappe.bold(self.po_no),
							frappe.bold(
								_("'Allow Multiple Sales Orders Against a Customer's Purchase Order'")
							),
							get_link_to_form("Selling Settings", "Selling Settings"),
						)
					)

	def validate_for_items(self):
		for d in self.get("items"):
			# used for production plan
			d.transaction_date = self.transaction_date

			tot_avail_qty = frappe.db.sql(
				"select projected_qty from `tabBin` \
				where item_code = %s and warehouse = %s",
				(d.item_code, d.warehouse),
			)
			d.projected_qty = tot_avail_qty and flt(tot_avail_qty[0][0]) or 0

	def validate_sales_mntc_quotation(self):
		for d in self.get("items"):
			if d.prevdoc_docname:
				res = frappe.db.sql(
					"select name from `tabQuotation` where name=%s and order_type = %s",
					(d.prevdoc_docname, self.order_type),
				)
				if not res:
					frappe.msgprint(
						_("Quotation {0} not of type {1}").format(d.prevdoc_docname, self.order_type)
					)

	def validate_delivery_date(self):
		if self.order_type == "Sales" and not self.skip_delivery_note:
			delivery_date_list = [d.delivery_date for d in self.get("items") if d.delivery_date]
			max_delivery_date = max(delivery_date_list) if delivery_date_list else None
			if (max_delivery_date and not self.delivery_date) or (
				max_delivery_date and getdate(self.delivery_date) != getdate(max_delivery_date)
			):
				self.delivery_date = max_delivery_date
			if self.delivery_date:
				for d in self.get("items"):
					if not d.delivery_date:
						d.delivery_date = self.delivery_date
					if getdate(self.transaction_date) > getdate(d.delivery_date):
						frappe.msgprint(
							_("Expected Delivery Date should be after Sales Order Date"),
							indicator="orange",
							title=_("Invalid Delivery Date"),
							raise_exception=True,
						)
			else:
				frappe.throw(_("Please enter Delivery Date"))

		self.validate_sales_mntc_quotation()

	def validate_warehouse(self):
		super().validate_warehouse()

		for d in self.get("items"):
			if (
				frappe.get_cached_value("Item", d.item_code, "is_stock_item") == 1
				and not d.warehouse
				and not cint(d.delivered_by_supplier)
			):
				frappe.throw(
					_("Source warehouse required for stock item {0}").format(d.item_code), WarehouseRequired
				)

	def validate_with_previous_doc(self):
		super().validate_with_previous_doc(
			{
				"Quotation": {"ref_dn_field": "prevdoc_docname", "compare_fields": [["company", "="]]},
				"Quotation Item": {
					"ref_dn_field": "quotation_item",
					"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
					"is_child_table": True,
					"allow_duplicate_prev_row_id": True,
				},
			}
		)

		if cint(frappe.get_single_value("Selling Settings", "maintain_same_sales_rate")):
			self.validate_rate_with_reference_doc([["Quotation", "prevdoc_docname", "quotation_item"]])

	def update_prevdoc_status(self, flag=None, update_quotation_qty=False):
		# Update Items edits ordered rows without going through on_submit/on_cancel,
		# so recompute the quotation's ordered_qty and re-run the over-order check here.
		if update_quotation_qty:
			super().update_prevdoc_status()

		for quotation in set(d.prevdoc_docname for d in self.get("items")):
			if quotation:
				doc = frappe.get_doc("Quotation", quotation)
				if doc.docstatus.is_cancelled():
					frappe.throw(_("Quotation {0} is cancelled").format(quotation))

				doc.set_status(update=True)

	def update_ordered_qty_in_quotation_for_removed_items(self, removed_items):
		"""Recompute Quotation Item ordered_qty for rows removed via Update Items.

		`update_qty` on the surviving rows never visits a removed row's quotation_item,
		so without this it keeps counting as ordered even after the row (or the SO) is gone.
		"""
		soi = frappe.qb.DocType("Sales Order Item")
		quotations = set()
		for item in removed_items:
			quotation_item = item.get("quotation_item")
			if not quotation_item:
				continue

			ordered_qty = (
				frappe.qb.from_(soi)
				.select(Sum(soi.stock_qty))
				.where((soi.quotation_item == quotation_item) & (soi.docstatus == 1))
			).run()[0][0]
			frappe.db.set_value("Quotation Item", quotation_item, "ordered_qty", flt(ordered_qty))

			quotation = frappe.db.get_value("Quotation Item", quotation_item, "parent")
			if quotation:
				quotations.add(quotation)

		for quotation in quotations:
			frappe.get_doc("Quotation", quotation).set_status(update=True)

	def validate_drop_ship(self):
		for d in self.get("items"):
			if d.delivered_by_supplier and not d.supplier:
				frappe.throw(_("Row #{0}: Set Supplier for item {1}").format(d.idx, d.item_code))

	def on_submit(self):
		super().update_prevdoc_status()
		self.check_credit_limit()
		self.update_reserved_qty()

		self.update_prevdoc_status("submit")

		update_linked_doc(self.doctype, self.name, self.inter_company_order_reference)

	def on_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Stock Ledger Entry",
			"Payment Ledger Entry",
			"Advance Payment Ledger Entry",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
		)
		super().on_cancel()
		super().update_prevdoc_status()
		# Cannot cancel closed SO
		if self.status == "Closed":
			frappe.throw(_("Closed order cannot be cancelled. Unclose to cancel."))

		self.check_nextdoc_docstatus()
		self.update_reserved_qty()
		self.update_prevdoc_status("cancel")

		self.db_set("status", "Cancelled")

		unlink_inter_company_doc(self.doctype, self.name, self.inter_company_order_reference)

	def on_trash(self):
		pass

	def check_credit_limit(self):
		if not is_sales_order_credit_check_bypassed(self.customer, self.company):
			check_credit_limit(self.customer, self.company)

	def check_nextdoc_docstatus(self):
		linked_invoices = frappe.db.sql_list(
			"""select distinct t1.name
			from `tabSales Invoice` t1,`tabSales Invoice Item` t2
			where t1.name = t2.parent and t2.sales_order = %s and t1.docstatus = 0""",
			self.name,
		)

		if linked_invoices:
			linked_invoices = [get_link_to_form("Sales Invoice", si) for si in linked_invoices]
			frappe.throw(
				_("Sales Invoice {0} must be deleted before cancelling this Sales Order").format(
					", ".join(linked_invoices)
				)
			)

	def check_modified_date(self):
		mod_db = frappe.db.get_value("Sales Order", self.name, "modified")
		date_diff = frappe.db.sql(f"select TIMEDIFF('{mod_db}', '{cstr(self.modified)}')")
		if date_diff and date_diff[0][0]:
			frappe.throw(_("{0} {1} has been modified. Please refresh.").format(self.doctype, self.name))

	def update_status(self, status):
		self.check_modified_date()
		self.set_status(update=True, status=status)
		# Upon Sales Order Re-open, check for credit limit.
		# Limit should be checked after the 'Hold/Closed' status is reset.
		if status == "Draft" and self.docstatus == 1:
			self.check_credit_limit()
		self.update_reserved_qty()
		self.notify_update()
		clear_doctype_notifications(self)

	def update_reserved_qty(self, so_item_rows=None):
		"""update requested qty (before ordered_qty is updated)"""
		item_wh_list = []

		def _valid_for_reserve(item_code, warehouse):
			if (
				item_code
				and warehouse
				and [item_code, warehouse] not in item_wh_list
				and frappe.get_cached_value("Item", item_code, "is_stock_item")
			):
				item_wh_list.append([item_code, warehouse])

		for d in self.get("items"):
			if (not so_item_rows or d.name in so_item_rows) and not d.delivered_by_supplier:
				_valid_for_reserve(d.item_code, d.warehouse)

		for item_code, warehouse in item_wh_list:
			update_bin_qty(item_code, warehouse, {"reserved_qty": get_reserved_qty(item_code, warehouse)})

	def on_update_after_submit(self):
		self.check_credit_limit()

	def before_update_after_submit(self):
		super().before_update_after_submit()
		self.validate_po()
		self.validate_drop_ship()
		self.validate_supplier_after_submit()
		self.validate_delivery_date()

	def validate_supplier_after_submit(self):
		"""Check that supplier is the same after submit if PO is already made"""
		exc_list = []

		for item in self.items:
			if item.supplier:
				supplier = frappe.db.get_value("Sales Order Item", item.name, "supplier")
				if item.ordered_qty > 0.0 and item.supplier != supplier:
					exc_list.append(
						_("Row #{0}: Not allowed to change Supplier as Purchase Order already exists").format(
							item.idx
						)
					)

		if exc_list:
			frappe.throw("\n".join(exc_list))

	def update_delivery_status(self):
		"""Update delivery status from Purchase Order for drop shipping"""
		tot_qty, delivered_qty = 0.0, 0.0

		for item in self.items:
			if item.delivered_by_supplier:
				item.db_set("delivered_qty", self.get_drop_ship_delivered_qty(item), update_modified=False)

			delivered_qty += min(item.delivered_qty, item.qty)
			tot_qty += item.qty

		if tot_qty != 0:
			self.db_set("per_delivered", flt(delivered_qty / tot_qty) * 100, update_modified=False)

	def get_drop_ship_delivered_qty(self, item) -> float:
		"""Qty received against the drop-ship Purchase Orders of `item`, in the Sales Order UOM."""
		po_item = frappe.qb.DocType("Purchase Order Item")
		received_stock_qty = (
			frappe.qb.from_(po_item)
			.select(Sum(po_item.received_qty * po_item.conversion_factor))
			.where((po_item.sales_order_item == item.name) & (po_item.docstatus == 1))
		).run()[0][0]
		return flt(
			flt(received_stock_qty) / flt(item.conversion_factor or 1), item.precision("delivered_qty")
		)

	def set_indicator(self):
		"""Set indicator for portal"""
		self.indicator_color = {
			"Draft": "red",
			"On Hold": "orange",
			"To Deliver and Bill": "orange",
			"To Bill": "orange",
			"To Deliver": "orange",
			"Completed": "green",
			"Cancelled": "red",
		}.get(self.status, "blue")

		self.indicator_title = _(self.status)

	def on_recurring(self, reference_doc, auto_repeat_doc):
		super().on_recurring(reference_doc, auto_repeat_doc)

		def _get_delivery_date(ref_doc_delivery_date, red_doc_transaction_date, transaction_date):
			delivery_date = auto_repeat_doc.get_next_schedule_date(schedule_date=ref_doc_delivery_date)

			if delivery_date <= transaction_date:
				delivery_date_diff = frappe.utils.date_diff(ref_doc_delivery_date, red_doc_transaction_date)
				delivery_date = frappe.utils.add_days(transaction_date, delivery_date_diff)

			return delivery_date

		self.set(
			"delivery_date",
			_get_delivery_date(
				reference_doc.delivery_date, reference_doc.transaction_date, self.transaction_date
			),
		)

		for d in self.get("items"):
			reference_delivery_date = frappe.db.get_value(
				"Sales Order Item",
				{"parent": reference_doc.name, "item_code": d.item_code, "idx": d.idx},
				"delivery_date",
			)

			d.set(
				"delivery_date",
				_get_delivery_date(
					reference_delivery_date, reference_doc.transaction_date, self.transaction_date
				),
			)

	def set_missing_values(self, for_validate=False):
		super().set_missing_values(for_validate)

		if self.delivery_date:
			for item in self.items:
				if not item.delivery_date:
					item.delivery_date = self.delivery_date


@frappe.whitelist(methods=["POST"])
def close_or_unclose_sales_orders(names, status):
	frappe.has_permission("Sales Order", "write", throw=True)

	names = json.loads(names)
	for name in names:
		if not isinstance(name, str):
			frappe.throw(_("Invalid name"), frappe.PermissionError)

		# the check above is doctype level, so on its own it lets a caller restricted to one company close
		# another company's orders. Matches what update_status() already does.
		so = frappe.get_lazy_doc("Sales Order", name, check_permission="submit")
		if so.docstatus == 1:
			if status == "Closed":
				if so.status not in ("Cancelled", "Closed") and (
					so.per_delivered < 100 or so.per_billed < 100
				):
					so.update_status(status)
			else:
				if so.status == "Closed":
					so.update_status("Draft")

	frappe.local.message_log = []


@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None, kwargs=None):
	if not kwargs:
		kwargs = {
			"skip_item_mapping": frappe.flags.args and frappe.flags.args.skip_item_mapping,
		}

	kwargs = frappe._dict(kwargs)

	mapped_qty_by_item = get_qty_already_mapped(target_doc, "so_detail")

	mapper = {
		"Sales Order": {"doctype": "Delivery Note", "validation": {"docstatus": ["=", 1]}},
		"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "reset_value": True},
	}

	# 0 qty is accepted, as the qty is uncertain for some items
	has_unit_price_items = frappe.db.get_value("Sales Order", source_name, "has_unit_price_items")

	def is_unit_price_row(source):
		return has_unit_price_items and source.qty == 0

	def select_item(d):
		filtered_items = kwargs.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	def set_missing_values(source, target):
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")
		target.run_method("set_use_serial_batch_fields")

		if source.company_address:
			target.update({"company_address": source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Delivery Note", "company_address", target.company_address))

		# if invoked in bulk creation, validations are ignored and thus this method is nerver invoked
		if frappe.flags.bulk_transaction:
			# set target items names to ensure proper linking with packed_items
			target.set_new_name()

	def condition(doc):
		# make_mapped_doc sets js `args` into `frappe.flags.args`
		if frappe.flags.args and frappe.flags.args.delivery_dates:
			if cstr(doc.delivery_date) not in frappe.flags.args.delivery_dates:
				return False
		if frappe.flags.args and frappe.flags.args.until_delivery_date:
			if cstr(doc.delivery_date) > frappe.flags.args.until_delivery_date:
				return False

		return (
			(abs(doc.delivered_qty) + abs(mapped_qty_by_item.get(doc.name, 0)) < abs(doc.qty))
			or (is_unit_price_row(doc) and doc.name not in mapped_qty_by_item)
		) and doc.delivered_by_supplier != 1

	def remaining_qty(source):
		return flt(source.qty) - flt(source.delivered_qty) - flt(mapped_qty_by_item.get(source.name, 0))

	def update_item(source, target, source_parent):
		target.base_amount = remaining_qty(source) * flt(source.base_rate)
		target.amount = remaining_qty(source) * flt(source.rate)
		target.qty = flt(source.qty) if is_unit_price_row(source) else remaining_qty(source)

		item = get_item_defaults(target.item_code, source_parent.company)
		item_group = get_item_group_defaults(target.item_code, source_parent.company)

		if item:
			target.cost_center = item.get("buying_cost_center") or item_group.get("buying_cost_center")

	if not kwargs.skip_item_mapping:
		mapper["Sales Order Item"] = {
			"doctype": "Delivery Note Item",
			"field_map": {
				"rate": "rate",
				"name": "so_detail",
				"parent": "against_sales_order",
			},
			"condition": lambda d: condition(d) and select_item(d),
			"postprocess": update_item,
		}

	so = frappe.get_doc("Sales Order", source_name)
	target_doc = get_mapped_doc("Sales Order", so.name, mapper, target_doc)

	if not kwargs.skip_item_mapping and frappe.flags.bulk_transaction and not target_doc.items:
		# the (date) condition filter resulted in an unintendedly created empty DN; remove it
		del target_doc
		return

	# Should be called after mapping items.
	target_doc.packed_items = []
	set_missing_values(so, target_doc)

	return target_doc


def get_qty_net_of_returns(so_item, credit_note_returned_qty: float = 0) -> float:
	"""Return the ordered quantity billable after returns and re-deliveries."""
	qty = flt(so_item.qty)
	returned_qty = flt(so_item.returned_qty) - flt(credit_note_returned_qty)

	return min(qty, max(qty - returned_qty, flt(so_item.delivered_qty)))


@frappe.whitelist()
def make_sales_invoice(
	source_name: str,
	target_doc: str | dict | Document | None = None,
	args: str | dict | None = None,
	ignore_permissions: bool = False,
):
	if args is None:
		args = {}
	if isinstance(args, str):
		args = json.loads(args)

	# 0 qty is accepted, as the qty is uncertain for some items
	has_unit_price_items = frappe.db.get_value("Sales Order", source_name, "has_unit_price_items")
	invoiced_qty_by_item = None
	pending_qty_by_item = {}
	amount_allowance_by_item = {}
	mapped_qty_by_item = get_qty_already_mapped(target_doc, "so_detail")

	def is_unit_price_row(source):
		return has_unit_price_items and source.qty == 0

	def is_amount_billable(source):
		from hisaabdari.controllers.status_updater import get_allowance_for

		if source.item_code not in amount_allowance_by_item:
			amount_allowance_by_item[source.item_code] = flt(
				get_allowance_for(source.item_code, qty_or_amount="amount")[0]
			)

		allowance = amount_allowance_by_item[source.item_code]
		return abs(flt(source.billed_amt)) < abs(flt(source.amount)) * (1 + allowance / 100)

	def get_invoiced_qty_by_item():
		nonlocal invoiced_qty_by_item

		if invoiced_qty_by_item is None:
			invoice = frappe.qb.DocType("Sales Invoice")
			invoice_item = frappe.qb.DocType("Sales Invoice Item")
			sales_order_item = frappe.qb.DocType("Sales Order Item")
			qty_in_stock_uom = invoice_item.qty * invoice_item.conversion_factor
			credit_note_qty = (
				Case().when(get_credit_note_return_criterion(invoice), -qty_in_stock_uom).else_(0)
			)
			rows = (
				frappe.qb.from_(invoice_item)
				.inner_join(sales_order_item)
				.on(invoice_item.so_detail == sales_order_item.name)
				.inner_join(invoice)
				.on(invoice.name == invoice_item.parent)
				.select(
					sales_order_item.name.as_("so_detail"),
					(Sum(qty_in_stock_uom) / sales_order_item.conversion_factor).as_("billed_qty"),
					(Sum(credit_note_qty) / sales_order_item.conversion_factor).as_(
						"credit_note_returned_qty"
					),
				)
				.where((invoice_item.docstatus == 1) & (sales_order_item.parent == source_name))
				.groupby(sales_order_item.name)
			).run(as_dict=True)
			invoiced_qty_by_item = {row.so_detail: row for row in rows}

		return invoiced_qty_by_item

	def get_pending_qty(source):
		if source.name not in pending_qty_by_item:
			invoiced = get_invoiced_qty_by_item().get(source.name, frappe._dict())
			billable_qty = get_qty_net_of_returns(source, invoiced.credit_note_returned_qty)
			billable_qty -= flt(invoiced.billed_qty)
			billable_qty -= mapped_qty_by_item.get(source.name, 0)
			pending_qty_by_item[source.name] = max(flt(billable_qty, source.precision("qty")), 0)

		return pending_qty_by_item[source.name]

	def is_qty_billed_below_amount(source):
		invoiced = get_invoiced_qty_by_item().get(source.name, frappe._dict())
		return (
			source.name not in mapped_qty_by_item
			and flt(flt(source.qty) - flt(invoiced.billed_qty), source.precision("qty")) <= 0
			and abs(flt(source.billed_amt)) < abs(flt(source.amount))
		)

	def postprocess(source, target):
		set_missing_values(source, target)
		# Get the advance paid Journal Entries in Sales Invoice Advance
		if target.get("allocate_advances_automatically"):
			target.set_advances()

	def set_missing_values(source, target):
		target.flags.ignore_permissions = ignore_permissions
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")
		target.run_method("set_use_serial_batch_fields")

		if source.company_address:
			target.update({"company_address": source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Sales Invoice", "company_address", target.company_address))

		target.debit_to = get_party_account("Customer", source.customer, source.company)

	def update_item(source, target, source_parent):
		if source_parent.has_unit_price_items:
			# 0 Amount rows (as seen in Unit Price Items) should be mapped as it is
			pending_amount = flt(source.amount) - flt(source.billed_amt)
			target.amount = pending_amount if flt(source.amount) else 0
		else:
			target.amount = flt(source.amount) - flt(source.billed_amt)

		target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = source.qty if is_unit_price_row(source) else get_pending_qty(source)

		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	doclist = get_mapped_doc(
		"Sales Order",
		source_name,
		{
			"Sales Order": {
				"doctype": "Sales Invoice",
				"field_map": {
					"party_account_currency": "party_account_currency",
				},
				"field_no_map": ["payment_terms_template"],
				"validation": {"docstatus": ["=", 1]},
			},
			"Sales Order Item": {
				"doctype": "Sales Invoice Item",
				"field_map": {
					"name": "so_detail",
					"parent": "sales_order",
				},
				"postprocess": update_item,
				"condition": lambda doc: not args.get("skip_item_mapping")
				and select_item(doc)
				and (
					doc.name not in mapped_qty_by_item
					if is_unit_price_row(doc)
					else (
						doc.qty
						and (
							((doc.base_amount == 0 or is_amount_billable(doc)) and get_pending_qty(doc) > 0)
							or is_qty_billed_below_amount(doc)
						)
					)
				),
			},
			"Sales Taxes and Charges": {
				"doctype": "Sales Taxes and Charges",
				"reset_value": True,
			},
		},
		target_doc,
		postprocess,
		ignore_permissions=ignore_permissions,
	)

	automatically_fetch_payment_terms = cint(
		frappe.get_single_value("Accounts Settings", "automatically_fetch_payment_terms")
	)
	if automatically_fetch_payment_terms:
		doclist.set_payment_schedule()

	return doclist


@frappe.whitelist()
def get_events(start, end, filters=None):
	"""Returns events for Gantt / Calendar view rendering.

	:param start: Start date-time.
	:param end: End date-time.
	:param filters: Filters (JSON).
	"""
	from frappe.desk.calendar import get_event_conditions

	conditions = get_event_conditions("Sales Order", filters)

	data = frappe.db.sql(
		f"""
		select
			distinct `tabSales Order`.name, `tabSales Order`.customer_name, `tabSales Order`.status,
			`tabSales Order`.delivery_status, `tabSales Order`.billing_status,
			`tabSales Order Item`.delivery_date
		from
			`tabSales Order`, `tabSales Order Item`
		where `tabSales Order`.name = `tabSales Order Item`.parent
			and `tabSales Order`.skip_delivery_note = 0
			and (ifnull(`tabSales Order Item`.delivery_date, '0000-00-00')!= '0000-00-00') \
			and (`tabSales Order Item`.delivery_date between %(start)s and %(end)s)
			and `tabSales Order`.docstatus < 2
			{conditions}
		""",
		{"start": start, "end": end},
		as_dict=True,
		update={
			"allDay": 0,
			"convertToUserTz": 0,
		},
	)
	return data


@frappe.whitelist()
def make_purchase_order(source_name, selected_items=None, target_doc=None):
	"""Creates Purchase Order for each Supplier. Returns a list of doc objects."""

	from hisaabdari.setup.utils import get_exchange_rate

	if not selected_items:
		return

	if isinstance(selected_items, str):
		selected_items = json.loads(selected_items)

	def set_missing_values(source, target):
		target.supplier = supplier
		target.currency = frappe.db.get_value(
			"Supplier", filters={"name": supplier}, fieldname=["default_currency"]
		)
		company_currency = frappe.db.get_value(
			"Company", filters={"name": target.company}, fieldname=["default_currency"]
		)

		target.conversion_rate = get_exchange_rate(target.currency, company_currency, args="for_buying")

		target.apply_discount_on = ""
		target.additional_discount_percentage = 0.0
		target.discount_amount = 0.0
		target.tc_name = ""
		target.terms = ""
		target.payment_schedule = []

		default_price_list = frappe.get_value("Supplier", supplier, "default_price_list")
		if default_price_list:
			target.buying_price_list = default_price_list

		default_payment_terms = frappe.get_value("Supplier", supplier, "payment_terms")
		if default_payment_terms:
			target.payment_terms_template = default_payment_terms

		if any(item.delivered_by_supplier for item in target.items):
			if source.shipping_address_name:
				target.shipping_address = source.shipping_address_name
				target.shipping_address_display = source.shipping_address
			else:
				target.shipping_address = source.customer_address
				target.shipping_address_display = source.address_display

			target.customer_contact_person = source.contact_person
			target.customer_contact_display = source.contact_display
			target.customer_contact_mobile = source.contact_mobile
			target.customer_contact_email = source.contact_email

		else:
			target.customer = ""
			target.customer_name = ""

		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source, target, source_parent):
		target.schedule_date = source.delivery_date
		target.qty = qty_to_order[source.name]
		target.stock_qty = target.qty * flt(source.conversion_factor)

	def filter_items(item, supplier):
		if (
			qty_to_order[item.name] > 0
			and item.name in items_to_map
			and items_to_map[item.name] == supplier
		):
			return True

		return False

	sales_order = frappe.get_doc("Sales Order", source_name)
	sales_order.check_permission("read")
	qty_to_order = get_qty_to_order(sales_order.items, "sales_order_item")
	items_to_map = {}
	for item in selected_items:
		filters = {"name": item.get("name")} if item.get("name") else {"item_code": item.get("item_code")}
		rows = sales_order.get("items", filters)
		if len(rows) != 1:
			frappe.throw(
				_("Select a valid Sales Order row for Item {0}.").format(
					frappe.bold(item.get("item_code") or item.get("name"))
				),
				title=_("Invalid Item Selection"),
			)
		items_to_map[rows[0].name] = item.get("supplier")

	suppliers = list(set(items_to_map.values()))

	if not suppliers:
		suppliers = [None]

	purchase_orders = []
	for supplier in suppliers:
		doc = get_mapped_doc(
			"Sales Order",
			source_name,
			{
				"Sales Order": {
					"doctype": "Purchase Order",
					"field_no_map": [*CROSS_PARTY_FIELD_NO_MAP],
					"validation": {"docstatus": ["=", 1]},
				},
				"Sales Order Item": {
					"doctype": "Purchase Order Item",
					"field_map": [
						["name", "sales_order_item"],
						["parent", "sales_order"],
						["stock_uom", "stock_uom"],
						["uom", "uom"],
						["conversion_factor", "conversion_factor"],
						["delivery_date", "schedule_date"],
					],
					"field_no_map": [
						"rate",
						"price_list_rate",
						"item_tax_template",
						"discount_percentage",
						"discount_amount",
						"mapped_additional_discount_amount",
						"pricing_rules",
						"margin_type",
						"margin_rate_or_amount",
					],
					"postprocess": update_item,
					"condition": lambda doc, s=supplier: filter_items(doc, s),
				},
			},
			target_doc,
			set_missing_values,
		)

		if doc.supplier:
			doc.insert()
		purchase_orders.append(doc)

	return purchase_orders


@frappe.whitelist(methods=["POST"])
def update_status(status, name):
	if status not in ("Draft", "On Hold", "Closed"):
		frappe.throw(_("Sales Order status cannot be set to {0}").format(status))

	so = frappe.get_doc("Sales Order", name, check_permission="submit")
	if so.docstatus != 1:
		frappe.throw(_("Only a submitted Sales Order can be put On Hold, Closed or re-opened"))

	so.update_status(status)


@frappe.whitelist()
def make_inter_company_purchase_order(source_name, target_doc=None):
	from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_transaction

	return make_inter_company_transaction("Sales Order", source_name, target_doc)


def get_credit_note_return_criterion(invoice):
	"""Match return invoices that reverse both the delivery and the billing of Sales Order rows."""
	return (
		(invoice.is_return == 1)
		& (invoice.update_stock == 1)
		& (invoice.update_billed_amount_in_sales_order == 1)
	)


def get_billed_qty_query(sales_order_item):
	"""Return the qty billed against a Sales Order Item by submitted Sales Invoices."""
	invoice_item = qb.DocType("Sales Invoice Item")
	return (
		qb.from_(invoice_item)
		.select(
			IfNull(Sum(invoice_item.qty * invoice_item.conversion_factor), 0)
			/ sales_order_item.conversion_factor
		)
		.where((invoice_item.docstatus == 1) & (invoice_item.so_detail == sales_order_item.name))
	)


def get_pending_qty_criterion(sales_order_item, billed_qty):
	"""Mirror the mapper's pending quantity check."""
	invoice = qb.DocType("Sales Invoice")
	invoice_item = qb.DocType("Sales Invoice Item")
	credit_note_returned_qty = (
		qb.from_(invoice_item)
		.inner_join(invoice)
		.on(invoice.name == invoice_item.parent)
		.select(
			IfNull(Sum(-invoice_item.qty * invoice_item.conversion_factor), 0)
			/ sales_order_item.conversion_factor
		)
		.where(
			(invoice_item.docstatus == 1)
			& (invoice_item.so_detail == sales_order_item.name)
			& get_credit_note_return_criterion(invoice)
		)
	)
	returned_qty = sales_order_item.returned_qty - credit_note_returned_qty

	qty_precision = frappe.get_precision("Sales Order Item", "qty")
	has_unbilled_ordered_qty = Round(sales_order_item.qty - billed_qty, qty_precision) > 0
	has_unbilled_delivered_qty = (
		Round(sales_order_item.qty - returned_qty - billed_qty, qty_precision) > 0
	) | (Round(sales_order_item.delivered_qty - billed_qty, qty_precision) > 0)

	return has_unbilled_ordered_qty & has_unbilled_delivered_qty


def get_qty_billed_below_amount_criterion(sales_order_item, billed_qty):
	"""Mirror the mapper's check for a fully billed qty that is billed below the row amount."""
	qty_precision = frappe.get_precision("Sales Order Item", "qty")
	return (Round(sales_order_item.qty - billed_qty, qty_precision) <= 0) & (
		Abs(sales_order_item.billed_amt) < Abs(sales_order_item.amount)
	)


def get_potentially_billable_item_criterion(sales_order, sales_order_item, item):
	"""Return the row level checks the Sales Invoice mapper applies."""
	global_allowance = flt(frappe.get_cached_value("Accounts Settings", None, "over_billing_allowance"))
	allowance = (
		Case().when(item.over_billing_allowance != 0, item.over_billing_allowance).else_(global_allowance)
	)

	has_amount_headroom = (sales_order_item.base_amount == 0) | (
		Abs(sales_order_item.billed_amt) < Abs(sales_order_item.amount) * (1 + allowance / 100)
	)
	is_unit_price_row = (sales_order.has_unit_price_items == 1) & (sales_order_item.qty == 0)
	billed_qty = get_billed_qty_query(sales_order_item)
	is_billable_row = (sales_order_item.qty != 0) & (
		(has_amount_headroom & get_pending_qty_criterion(sales_order_item, billed_qty))
		| get_qty_billed_below_amount_criterion(sales_order_item, billed_qty)
	)

	return is_unit_price_row | is_billable_row


def has_potentially_billable_items(sales_order: str) -> bool:
	"""Return whether a Sales Order has an item with billing amount headroom."""
	so = qb.DocType("Sales Order")
	so_item = qb.DocType("Sales Order Item")
	item = qb.DocType("Item")

	return bool(
		qb.from_(so_item)
		.inner_join(so)
		.on(so.name == so_item.parent)
		.left_join(item)
		.on(item.name == so_item.item_code)
		.select(so_item.name)
		.where((so_item.parent == sales_order) & get_potentially_billable_item_criterion(so, so_item, item))
		.limit(1)
		.run()
	)


@frappe.whitelist(methods=["GET"])
@frappe.validate_and_sanitize_search_inputs
def get_potentially_billable_sales_orders(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
):
	"""Return Sales Orders that have an item with billing amount headroom."""
	so = qb.DocType("Sales Order")
	so_item = qb.DocType("Sales Order Item")
	item = qb.DocType("Item")
	meta = frappe.get_meta("Sales Order")

	search_fields = list(dict.fromkeys(["name", meta.title_field, *meta.get_search_fields()]))
	or_filters = (
		{
			fieldname: ("like", f"%{txt}%")
			for fieldname in search_fields
			if fieldname
			and (
				fieldname == "name"
				or ((field := meta.get_field(fieldname)) and field.fieldtype in LINK_SEARCH_FIELDTYPES)
			)
		}
		if txt
		else None
	)

	query = frappe.qb.get_query(
		so,
		fields=[so.name, so.customer, so.transaction_date, so.creation],
		filters=filters,
		or_filters=or_filters,
		ignore_permissions=False,
	)

	return (
		query.inner_join(so_item)
		.on(so_item.parent == so.name)
		.left_join(item)
		.on(item.name == so_item.item_code)
		.where(get_potentially_billable_item_criterion(so, so_item, item))
		.distinct()
		.orderby(so.transaction_date, order=Order.asc)
		.orderby(so.creation, order=Order.asc)
		.limit(cint(page_len))
		.offset(cint(start))
		.run(as_dict=True)
	)
