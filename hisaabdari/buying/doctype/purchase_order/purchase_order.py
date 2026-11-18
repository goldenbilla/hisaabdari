# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
from frappe import _, msgprint
from frappe.desk.notifications import clear_doctype_notifications
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cstr, flt

from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import (
	unlink_inter_company_doc,
	update_linked_doc,
	validate_inter_company_party,
)
from hisaabdari.accounts.party import get_party_account, get_party_account_currency
from hisaabdari.buying.utils import validate_for_items
from hisaabdari.controllers.buying_controller import BuyingController, get_stock_qty_status_args
from hisaabdari.controllers.mapper import get_qty_already_mapped
from hisaabdari.controllers.taxes_and_totals import remove_margin
from hisaabdari.setup.doctype.item_group.item_group import get_item_group_defaults
from hisaabdari.stock.doctype.item.item import get_item_defaults, get_last_purchase_details
from hisaabdari.stock.stock_balance import get_ordered_qty, update_bin_qty

form_grid_templates = {"items": "templates/form_grid/item_grid.html"}


class PurchaseOrder(BuyingController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from hisaabdari.accounts.doctype.item_wise_tax_detail.item_wise_tax_detail import ItemWiseTaxDetail
		from hisaabdari.accounts.doctype.payment_schedule.payment_schedule import PaymentSchedule
		from hisaabdari.accounts.doctype.purchase_taxes_and_charges.purchase_taxes_and_charges import (
			PurchaseTaxesandCharges,
		)
		from hisaabdari.buying.doctype.purchase_order_item.purchase_order_item import PurchaseOrderItem

		additional_discount_percentage: DF.Float
		address_display: DF.TextEditor | None
		advance_paid: DF.Currency
		advance_payment_status: DF.Literal["Not Initiated", "Initiated", "Partially Paid", "Fully Paid"]
		amended_from: DF.Link | None
		apply_discount_on: DF.Literal["", "Grand Total", "Net Total"]
		auto_repeat: DF.Link | None
		base_discount_amount: DF.Currency
		base_grand_total: DF.Currency
		base_in_words: DF.Data | None
		base_net_total: DF.Currency
		base_rounded_total: DF.Currency
		base_rounding_adjustment: DF.Currency
		base_taxes_and_charges_added: DF.Currency
		base_taxes_and_charges_deducted: DF.Currency
		base_total: DF.Currency
		base_total_taxes_and_charges: DF.Currency
		billing_address: DF.Link | None
		billing_address_display: DF.TextEditor | None
		buying_price_list: DF.Link | None
		company: DF.Link
		contact_display: DF.SmallText | None
		contact_email: DF.SmallText | None
		contact_mobile: DF.SmallText | None
		contact_person: DF.Link | None
		conversion_rate: DF.Float
		cost_center: DF.Link | None
		currency: DF.Link
		customer: DF.Link | None
		customer_contact_display: DF.SmallText | None
		customer_contact_email: DF.Code | None
		customer_contact_mobile: DF.SmallText | None
		customer_contact_person: DF.Link | None
		customer_name: DF.Data | None
		disable_rounded_total: DF.Check
		discount_amount: DF.Currency
		dispatch_address: DF.Link | None
		dispatch_address_display: DF.TextEditor | None
		from_date: DF.Date | None
		grand_total: DF.Currency
		group_same_items: DF.Check
		has_unit_price_items: DF.Check
		ignore_pricing_rule: DF.Check
		in_words: DF.Data | None
		inter_company_order_reference: DF.Link | None
		is_internal_supplier: DF.Check
		item_wise_tax_details: DF.Table[ItemWiseTaxDetail]
		items: DF.Table[PurchaseOrderItem]
		language: DF.Data | None
		letter_head: DF.Link | None
		naming_series: DF.Literal["PUR-ORD-.YYYY.-"]
		net_total: DF.Currency
		order_confirmation_date: DF.Date | None
		order_confirmation_no: DF.Data | None
		other_charges_calculation: DF.TextEditor | None
		party_account_currency: DF.Link | None
		payment_schedule: DF.Table[PaymentSchedule]
		payment_terms_template: DF.Link | None
		per_billed: DF.Percent
		per_received: DF.Percent
		plc_conversion_rate: DF.Float
		price_list_currency: DF.Link | None
		remarks: DF.SmallText | None
		represents_company: DF.Link | None
		rounded_total: DF.Currency
		rounding_adjustment: DF.Currency
		scan_barcode: DF.Data | None
		schedule_date: DF.Date | None
		select_print_heading: DF.Link | None
		set_from_warehouse: DF.Link | None
		set_warehouse: DF.Link | None
		shipping_address: DF.Link | None
		shipping_address_display: DF.TextEditor | None
		status: DF.Literal[
			"",
			"Draft",
			"On Hold",
			"To Receive and Bill",
			"To Bill",
			"To Receive",
			"Completed",
			"Cancelled",
			"Closed",
			"Delivered",
		]
		supplier: DF.Link
		supplier_address: DF.Link | None
		supplier_group: DF.Link | None
		supplier_name: DF.Data | None
		taxes: DF.Table[PurchaseTaxesandCharges]
		taxes_and_charges: DF.Link | None
		taxes_and_charges_added: DF.Currency
		taxes_and_charges_deducted: DF.Currency
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
	# end: auto-generated types

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.status_updater = []

	def onload(self):
		self.set_onload("can_update_items", self.can_update_items())

	def before_validate(self):
		self.set_has_unit_price_items()
		self.flags.allow_zero_qty = self.has_unit_price_items

	def validate(self):
		super().validate()

		self.set_status()

		self.validate_supplier()
		self.validate_schedule_date()
		validate_for_items(self)
		self.set_last_purchase_rate()

		self.validate_uom_is_integer("uom", "qty")
		self.validate_uom_is_integer("stock_uom", "stock_qty")

		self.validate_minimum_order_qty()

		if not self.advance_payment_status:
			self.advance_payment_status = "Not Initiated"

		validate_inter_company_party(
			self.doctype, self.supplier, self.company, self.inter_company_order_reference
		)
		self.reset_default_field_value("set_warehouse", "items", "warehouse")
		self.set_missing_terms()

	def set_last_purchase_rate(self):
		if frappe.db.get_single_value("Buying Settings", "disable_last_purchase_rate"):
			return

		for d in self.get("items"):
			if d.item_code:
				d.last_purchase_rate = flt(
					item_last_purchase_rate(
						self.name, self.conversion_rate, d.item_code, d.conversion_factor
					),
					d.precision("last_purchase_rate"),
				)

	def set_has_unit_price_items(self):
		"""
		If permitted in settings and any item has 0 qty, the PO has unit price items.
		"""
		if not frappe.db.get_single_value("Buying Settings", "allow_zero_qty_in_purchase_order"):
			return

		self.has_unit_price_items = any(
			not row.qty for row in self.get("items") if (row.item_code and not row.qty)
		)

	def validate_supplier(self):
		self.party_account_currency = get_party_account_currency("Supplier", self.supplier, self.company)

	def validate_minimum_order_qty(self):
		if not self.get("items"):
			return
		items = list(set(d.item_code for d in self.get("items")))

		itemwise_min_order_qty = frappe._dict(
			frappe.db.sql(
				"""select name, min_order_qty
			from tabItem where name in ({})""".format(", ".join(["%s"] * len(items))),
				items,
			)
		)

		itemwise_qty = frappe._dict()
		for d in self.get("items"):
			itemwise_qty.setdefault(d.item_code, 0)
			itemwise_qty[d.item_code] += flt(d.stock_qty)

		precision = self.items[0].precision("stock_qty")
		for item_code, qty in itemwise_qty.items():
			if flt(qty, precision) < flt(itemwise_min_order_qty.get(item_code), precision):
				frappe.throw(
					_(
						"Item {0}: Ordered qty {1} cannot be less than minimum order qty {2} (defined in Item)."
					).format(item_code, flt(qty, precision), itemwise_min_order_qty.get(item_code))
				)

		self.warn_marginal_min_order_qty(itemwise_qty, itemwise_min_order_qty)

	def warn_marginal_min_order_qty(self, itemwise_qty, itemwise_min_order_qty):
		"""Toast when an item's ordered qty exceeds its minimum only by purchase UOM rounding."""
		if not self.is_new():
			return

		precision = self.items[0].precision("stock_qty")
		itemwise_steps = {}
		itemwise_stock_uom = frappe._dict()
		for d in self.get("items"):
			step = 10 ** -d.precision("qty") * flt(d.conversion_factor)
			itemwise_steps.setdefault(d.item_code, set()).add(step)
			itemwise_stock_uom[d.item_code] = d.stock_uom

		for item_code, qty in itemwise_qty.items():
			steps = itemwise_steps[item_code]
			if len(steps) != 1:
				continue

			step = next(iter(steps))
			min_order_qty = flt(itemwise_min_order_qty.get(item_code))
			overage = flt(qty) - min_order_qty
			if min_order_qty and flt(overage, precision) > 0 and overage < step:
				frappe.toast(
					_(
						"Item {0}: Ordered qty {1} {2} exceeds the minimum order qty {3} {2} by {4} {2} due to purchase UOM rounding."
					).format(
						item_code,
						flt(qty, precision),
						itemwise_stock_uom[item_code],
						min_order_qty,
						flt(overage, precision),
					),
					indicator="orange",
				)

	@frappe.whitelist()
	def get_last_purchase_rate(self):
		"""get last purchase rates for all items"""

		conversion_rate = flt(self.get("conversion_rate")) or 1.0
		for d in self.get("items"):
			if d.item_code:
				last_purchase_details = get_last_purchase_details(d.item_code, self.name)
				if last_purchase_details:
					d.base_price_list_rate = last_purchase_details["base_price_list_rate"] * (
						flt(d.conversion_factor) or 1.0
					)
					d.discount_percentage = last_purchase_details["discount_percentage"]
					d.discount_amount = (
						last_purchase_details["discount_amount"]
						* (flt(d.conversion_factor) or 1.0)
						/ conversion_rate
					)
					d.base_rate = last_purchase_details["base_rate"] * (flt(d.conversion_factor) or 1.0)
					d.price_list_rate = d.base_price_list_rate / conversion_rate
					d.rate = d.base_rate / conversion_rate
					d.last_purchase_rate = d.rate
					remove_margin(d)
				else:
					item_last_purchase_rate = frappe.get_cached_value(
						"Item", d.item_code, "last_purchase_rate"
					)
					if item_last_purchase_rate:
						d.base_price_list_rate = d.base_rate = item_last_purchase_rate * (
							flt(d.conversion_factor) or 1.0
						)
						d.price_list_rate = d.rate = d.last_purchase_rate = d.base_rate / conversion_rate
						remove_margin(d)

	def update_ordered_qty(self, po_item_rows=None):
		"""update requested qty (before ordered_qty is updated)"""
		item_wh_list = []
		for d in self.get("items"):
			if (
				(not po_item_rows or d.name in po_item_rows)
				and [d.item_code, d.warehouse] not in item_wh_list
				and frappe.get_cached_value("Item", d.item_code, "is_stock_item")
				and d.warehouse
				and not d.delivered_by_supplier
			):
				item_wh_list.append([d.item_code, d.warehouse])
		for item_code, warehouse in item_wh_list:
			update_bin_qty(item_code, warehouse, {"ordered_qty": get_ordered_qty(item_code, warehouse)})

	def check_modified_date(self):
		mod_db = frappe.db.sql("select modified from `tabPurchase Order` where name = %s", self.name)
		date_diff = frappe.db.sql(f"select '{mod_db[0][0]}' - '{cstr(self.modified)}' ")

		if date_diff and date_diff[0][0]:
			msgprint(
				_("{0} {1} has been modified. Please refresh.").format(self.doctype, self.name),
				raise_exception=True,
			)

	def update_status(self, status):
		self.check_modified_date()
		self.set_status(update=True, status=status)
		self.update_ordered_qty()
		self.notify_update()
		clear_doctype_notifications(self)

	def on_submit(self):
		super().on_submit()

		if self.is_against_so():
			self.update_status_updater()

		self.update_prevdoc_status()

		self.update_ordered_qty()

		update_linked_doc(self.doctype, self.name, self.inter_company_order_reference)

	def on_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Payment Ledger Entry",
			"Advance Payment Ledger Entry",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
		)

		super().on_cancel()

		if self.is_against_so():
			self.update_status_updater()

		if self.has_drop_ship_item():
			self.set_received_qty_to_zero_for_drop_ship_items()
			self.update_receiving_percentage()
			self.update_delivered_qty_in_sales_order()

		self.db_set("status", "Cancelled")

		self.update_prevdoc_status()

		self.update_ordered_qty()

		unlink_inter_company_doc(self.doctype, self.name, self.inter_company_order_reference)

	def update_status_updater(self):
		self.status_updater.extend(self.get_sales_order_status_updater())

	@staticmethod
	def get_sales_order_status_updater():
		return [
			{
				"source_dt": "Purchase Order Item",
				"target_dt": "Sales Order Item",
				"target_field": "ordered_qty",
				"target_parent_dt": "Sales Order",
				"target_parent_field": "",
				"join_field": "sales_order_item",
				"target_ref_field": "stock_qty",
				**get_stock_qty_status_args(
					frappe.get_single_value("Stock Settings", "allow_to_edit_stock_uom_qty_for_sales")
				),
			},
			{
				"source_dt": "Purchase Order Item",
				"target_dt": "Packed Item",
				"target_field": "ordered_qty",
				"target_parent_dt": "Sales Order",
				"target_parent_field": "",
				"join_field": "sales_order_packed_item",
				"target_ref_field": "qty",
				**get_stock_qty_status_args(),
			},
		]

	def update_delivered_qty_in_sales_order(self):
		"""Update delivered qty in Sales Order for drop ship"""
		sales_orders_to_update = []
		for item in self.items:
			if item.sales_order and item.delivered_by_supplier == 1:
				if item.sales_order not in sales_orders_to_update:
					sales_orders_to_update.append(item.sales_order)

		for so_name in sales_orders_to_update:
			so = frappe.get_lazy_doc("Sales Order", so_name)
			so.update_delivery_status()
			so.set_status(update=True)
			so.notify_update()

	def set_received_qty_to_zero_for_drop_ship_items(self):
		for item in self.items:
			if item.delivered_by_supplier:
				item.db_set("received_qty", 0)

	def has_drop_ship_item(self):
		return any(d.delivered_by_supplier for d in self.items)

	@frappe.whitelist()
	def update_dropship_received_qty(self, data: list[dict]):
		self.check_permission("write")
		if not data:
			frappe.throw(_("Please select at least one item to update delivered quantity."))

		for d in data:
			item = next((item for item in self.items if item.name == d.get("name")), None)

			if not item:
				frappe.throw(
					_("Item with name {0} not found in the Purchase Order").format(frappe.bold(d.get("name")))
				)

			if not item.delivered_by_supplier:
				frappe.throw(
					_(
						"Item {0} is not a drop ship item. Only drop ship items can have Delivered Qty updated."
					).format(frappe.bold(item.item_code))
				)

			if not item.has_permlevel_access_to("received_qty", permission_type="write"):
				frappe.throw(
					_("You don't have permission to update Received Qty DocField for item {0}").format(
						frappe.bold(item.item_code)
					)
				)

			if not d.get("qty_change"):
				frappe.throw(
					_(
						"Item {0} has no changes in delivered quantity. Please unselect the row if you do not wish to update its quantity."
					).format(frappe.bold(item.item_code))
				)

			if d.get("qty_change") < 0 and abs(d.get("qty_change")) > item.received_qty:
				frappe.throw(
					_("Delivered Qty cannot be reduced by more than {0} for item {1}").format(
						item.received_qty, frappe.bold(item.item_code)
					)
				)

			if d.get("qty_change") > 0 and item.received_qty + d.get("qty_change") > item.qty:
				frappe.throw(
					_("Delivered Qty cannot be increased by more than {0} for item {1}").format(
						item.qty - item.received_qty, frappe.bold(item.item_code)
					)
				)

			qty_change = item.received_qty + d.get("qty_change")
			item.db_set("received_qty", qty_change, update_modified=True)
			self.add_comment(
				"Label",
				_("updated delivered quantity for item {0} to {1}").format(
					frappe.bold(item.item_code), frappe.bold(qty_change)
				),
			)
		self.update_receiving_percentage()
		self.set_status(update=True)
		self.update_delivered_qty_in_sales_order()

	def is_against_so(self):
		return any(d.sales_order for d in self.items if d.sales_order)

	def update_receiving_percentage(self):
		total_qty, received_qty = 0.0, 0.0
		for item in self.items:
			received_qty += min(item.received_qty, item.qty)
			total_qty += item.qty
		if total_qty and received_qty:
			self.db_set("per_received", flt(received_qty / total_qty) * 100, update_modified=False)
		else:
			self.db_set("per_received", 0, update_modified=False)

	def can_update_items(self) -> bool:
		result = True

		return result

	def update_ordered_qty_in_so_for_removed_items(self, removed_items):
		"""Recalculate the ordered qty of Sales Order rows linked to rows removed through Update Items."""
		if not removed_items:
			return

		# the removed rows are still in self.items, so their Sales Order rows are recalculated too
		for args in self.get_sales_order_status_updater():
			self._update_children({**args, "cond": ""}, update_modified=True)


@frappe.request_cache
def item_last_purchase_rate(name, conversion_rate, item_code, conversion_factor=1.0):
	"""get last purchase rate for an item"""

	conversion_rate = flt(conversion_rate) or 1.0

	last_purchase_details = get_last_purchase_details(item_code, name)
	if last_purchase_details:
		last_purchase_rate = (
			last_purchase_details["base_net_rate"] * (flt(conversion_factor) or 1.0)
		) / conversion_rate
		return last_purchase_rate
	else:
		item_last_purchase_rate = frappe.get_cached_value("Item", item_code, "last_purchase_rate")
		if item_last_purchase_rate:
			return item_last_purchase_rate * (flt(conversion_factor) or 1.0) / conversion_rate


@frappe.whitelist(methods=["POST"])
def close_or_unclose_purchase_orders(names, status):
	frappe.has_permission("Purchase Order", "write", throw=True)

	names = json.loads(names)
	for name in names:
		if not isinstance(name, str):
			frappe.throw(_("Invalid name"), frappe.PermissionError)

		# the check above is doctype level, so on its own it lets a caller restricted to one company close
		# another company's orders. Matches what update_status() already does.
		po = frappe.get_lazy_doc("Purchase Order", name, check_permission="submit")
		if po.docstatus == 1:
			if status == "Closed":
				if po.status not in ("Cancelled", "Closed") and (
					po.per_received < 100 or po.per_billed < 100
				):
					po.update_status(status)
			else:
				if po.status == "Closed":
					po.update_status("Draft")

	frappe.local.message_log = []


def set_missing_values(source, target):
	target.set_transaction_date_exchange_rate()
	target.run_method("set_missing_values")
	target.run_method("calculate_taxes_and_totals")
	target.run_method("set_use_serial_batch_fields")


def is_unit_price_row(po_item, has_unit_price_items) -> bool:
	return bool(has_unit_price_items) and po_item.qty == 0


@frappe.whitelist()
def make_purchase_receipt(source_name, target_doc=None, args=None):
	if args is None:
		args = {}
	if isinstance(args, str):
		args = json.loads(args)

	has_unit_price_items = frappe.db.get_value("Purchase Order", source_name, "has_unit_price_items")
	mapped_qty_by_item = get_qty_already_mapped(target_doc, "purchase_order_item")

	def update_item(obj, target, source_parent):
		received_qty = flt(obj.received_qty) + flt(mapped_qty_by_item.get(obj.name, 0))
		pending_qty = flt(obj.qty) - received_qty

		target.qty = flt(obj.qty) if is_unit_price_row(obj, has_unit_price_items) else pending_qty
		target.stock_qty = pending_qty * flt(obj.conversion_factor)
		target.amount = pending_qty * flt(obj.rate)
		target.base_amount = pending_qty * flt(obj.rate) * flt(source_parent.conversion_rate)

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	doc = get_mapped_doc(
		"Purchase Order",
		source_name,
		{
			"Purchase Order": {
				"doctype": "Purchase Receipt",
				"validation": {
					"docstatus": ["=", 1],
				},
			},
			"Purchase Order Item": {
				"doctype": "Purchase Receipt Item",
				"field_map": {
					"name": "purchase_order_item",
					"parent": "purchase_order",
					"sales_order": "sales_order",
					"sales_order_item": "sales_order_item",
				},
				"postprocess": update_item,
				"condition": lambda doc: (
					doc.name not in mapped_qty_by_item
					if is_unit_price_row(doc, has_unit_price_items)
					else abs(doc.received_qty) + abs(mapped_qty_by_item.get(doc.name, 0)) < abs(doc.qty)
				)
				and doc.delivered_by_supplier != 1
				and select_item(doc),
			},
			"Purchase Taxes and Charges": {"doctype": "Purchase Taxes and Charges", "reset_value": True},
		},
		target_doc,
		set_missing_values,
	)

	return doc


@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None, args=None):
	return get_mapped_purchase_invoice(source_name, target_doc, args=args)


def get_mapped_purchase_invoice(source_name, target_doc=None, ignore_permissions=False, args=None):
	if args is None:
		args = {}
	if isinstance(args, str):
		args = json.loads(args)

	def postprocess(source, target):
		target.flags.ignore_permissions = ignore_permissions
		set_missing_values(source, target)

		# Get the advance paid Journal Entries in Purchase Invoice Advance
		if target.get("allocate_advances_automatically"):
			target.set_advances()

		target.set_payment_schedule()
		target.credit_to = get_party_account("Supplier", source.supplier, source.company)

	from hisaabdari.buying.report.purchase_order_analysis.purchase_order_analysis import get_billed_qty_data

	has_unit_price_items = frappe.db.get_value("Purchase Order", source_name, "has_unit_price_items")
	mapped_qty_by_item = get_qty_already_mapped(target_doc, "po_detail")
	po_items = frappe.get_all("Purchase Order Item", filters={"parent": source_name}, fields=["name"])
	billed_qty_by_item = get_billed_qty_data(po_items) if po_items else {}

	def get_billed_and_mapped_qty(po_item):
		billed_qty = flt(billed_qty_by_item.get(po_item.name), po_item.precision("qty"))
		return billed_qty + flt(mapped_qty_by_item.get(po_item.name, 0))

	def is_qty_billed_below_amount(po_item):
		return (
			po_item.name not in mapped_qty_by_item
			and po_item.qty <= get_billed_and_mapped_qty(po_item)
			and abs(flt(po_item.billed_amt)) < abs(flt(po_item.amount))
		)

	def update_item(obj, target, source_parent):
		target.qty = (
			0
			if is_unit_price_row(obj, has_unit_price_items)
			else max(flt(obj.qty) - get_billed_and_mapped_qty(obj), 0)
		)

		item = get_item_defaults(target.item_code, source_parent.company)
		item_group = get_item_group_defaults(target.item_code, source_parent.company)
		target.cost_center = (
			obj.cost_center
			or item.get("buying_cost_center")
			or item_group.get("buying_cost_center")
		)

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	fields = {
		"Purchase Order": {
			"doctype": "Purchase Invoice",
			"field_map": {
				"party_account_currency": "party_account_currency",
			},
			"field_no_map": ["payment_terms_template"],
			"validation": {
				"docstatus": ["=", 1],
			},
		},
		"Purchase Order Item": {
			"doctype": "Purchase Invoice Item",
			"field_map": {
				"name": "po_detail",
				"parent": "purchase_order",
			},
			"postprocess": update_item,
			"condition": lambda doc: (
				doc.name not in mapped_qty_by_item
				if is_unit_price_row(doc, has_unit_price_items)
				else doc.qty > get_billed_and_mapped_qty(doc) or is_qty_billed_below_amount(doc)
			)
			and select_item(doc),
		},
		"Purchase Taxes and Charges": {"doctype": "Purchase Taxes and Charges", "reset_value": True},
	}

	doc = get_mapped_doc(
		"Purchase Order",
		source_name,
		fields,
		target_doc,
		postprocess,
		ignore_permissions=ignore_permissions,
	)

	return doc


@frappe.whitelist(methods=["POST"])
def update_status(status, name):
	if status not in ("Draft", "Submitted", "On Hold", "Closed"):
		frappe.throw(_("Cannot set the status of a Purchase Order to {0}.").format(status))

	po = frappe.get_lazy_doc("Purchase Order", name, check_permission="submit")
	if po.docstatus != 1:
		frappe.throw(_("Only a submitted Purchase Order can be held, closed or re-opened."))

	po.update_status(status)
	po.update_delivered_qty_in_sales_order()


@frappe.whitelist()
def make_inter_company_sales_order(source_name, target_doc=None):
	from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_transaction

	return make_inter_company_transaction("Purchase Order", source_name, target_doc)

