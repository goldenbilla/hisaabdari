# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
import frappe.utils
from frappe import _, msgprint, throw
from frappe.contacts.doctype.address.address import get_address_display
from frappe.model.mapper import get_mapped_doc
from frappe.model.utils import get_fetch_values
from frappe.utils import (
	cint,
	flt,
	formatdate,
	get_link_to_form,
	getdate,
	nowdate,
)
from frappe.utils.data import comma_and

import hisaabdari
from hisaabdari.accounts.doctype.repost_accounting_ledger.repost_accounting_ledger import (
	validate_docs_for_voucher_types,
)
from hisaabdari.accounts.general_ledger import get_round_off_account_and_cost_center
from hisaabdari.accounts.party import (
	CROSS_PARTY_FIELD_NO_MAP,
	get_due_date,
	get_party_account,
	get_party_details,
)
from hisaabdari.accounts.utils import (
	get_account_currency,
	update_voucher_outstanding,
)
from hisaabdari.controllers.accounts_controller import validate_account_head
from hisaabdari.controllers.selling_controller import SellingController
from hisaabdari.setup.doctype.company.company import update_company_current_month_sales
from hisaabdari.setup.doctype.terms_and_conditions.terms_and_conditions import clear_inapplicable_terms
from hisaabdari.stock.doctype.delivery_note.delivery_note import update_billed_amount_based_on_so
from hisaabdari.stock.utils import get_bin_qty_map

form_grid_templates = {"items": "templates/form_grid/item_grid.html"}


class SalesInvoice(SellingController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from hisaabdari.accounts.doctype.item_wise_tax_detail.item_wise_tax_detail import ItemWiseTaxDetail
		from hisaabdari.accounts.doctype.payment_schedule.payment_schedule import PaymentSchedule
		from hisaabdari.accounts.doctype.sales_invoice_advance.sales_invoice_advance import SalesInvoiceAdvance
		from hisaabdari.accounts.doctype.sales_invoice_item.sales_invoice_item import SalesInvoiceItem
		from hisaabdari.accounts.doctype.sales_invoice_payment.sales_invoice_payment import SalesInvoicePayment
		from hisaabdari.accounts.doctype.sales_taxes_and_charges.sales_taxes_and_charges import (
			SalesTaxesandCharges,
		)
		from hisaabdari.stock.doctype.packed_item.packed_item import PackedItem

		account_for_change_amount: DF.Link | None
		additional_discount_account: DF.Link | None
		additional_discount_percentage: DF.Float
		address_display: DF.TextEditor | None
		advances: DF.Table[SalesInvoiceAdvance]
		against_income_account: DF.SmallText | None
		allocate_advances_automatically: DF.Check
		amended_from: DF.Link | None
		apply_discount_on: DF.Literal["", "Grand Total", "Net Total"]
		auto_repeat: DF.Link | None
		base_change_amount: DF.Currency
		base_discount_amount: DF.Currency
		base_grand_total: DF.Currency
		base_in_words: DF.SmallText | None
		base_net_total: DF.Currency
		base_paid_amount: DF.Currency
		base_rounded_total: DF.Currency
		base_rounding_adjustment: DF.Currency
		base_total: DF.Currency
		base_total_taxes_and_charges: DF.Currency
		base_write_off_amount: DF.Currency
		cash_bank_account: DF.Link | None
		change_amount: DF.Currency
		company: DF.Link
		company_address: DF.Link | None
		company_address_display: DF.TextEditor | None
		company_contact_person: DF.Link | None
		company_tax_id: DF.Data | None
		contact_display: DF.SmallText | None
		contact_email: DF.Data | None
		contact_mobile: DF.SmallText | None
		contact_person: DF.Link | None
		conversion_rate: DF.Float
		cost_center: DF.Link | None
		currency: DF.Link
		customer: DF.Link
		customer_address: DF.Link | None
		customer_group: DF.Link | None
		customer_name: DF.SmallText | None
		debit_to: DF.Link
		disable_rounded_total: DF.Check
		discount_amount: DF.Currency
		dispatch_address: DF.TextEditor | None
		dispatch_address_name: DF.Link | None
		due_date: DF.Date | None
		from_date: DF.Date | None
		grand_total: DF.Currency
		group_same_items: DF.Check
		ignore_default_payment_terms_template: DF.Check
		ignore_pricing_rule: DF.Check
		in_words: DF.SmallText | None
		inter_company_invoice_reference: DF.Link | None
		is_cash_or_non_trade_discount: DF.Check
		is_debit_note: DF.Check
		is_internal_customer: DF.Check
		is_opening: DF.Literal["No", "Yes"]
		is_return: DF.Check
		item_wise_tax_details: DF.Table[ItemWiseTaxDetail]
		items: DF.Table[SalesInvoiceItem]
		language: DF.Link | None
		letter_head: DF.Link | None
		naming_series: DF.Literal["ACC-SINV-.YYYY.-", "ACC-SINV-RET-.YYYY.-"]
		net_total: DF.Currency
		only_include_allocated_payments: DF.Check
		other_charges_calculation: DF.TextEditor | None
		outstanding_amount: DF.Currency
		packed_items: DF.Table[PackedItem]
		paid_amount: DF.Currency
		party_account_currency: DF.Link | None
		payment_schedule: DF.Table[PaymentSchedule]
		payment_terms_template: DF.Link | None
		payments: DF.Table[SalesInvoicePayment]
		plc_conversion_rate: DF.Float
		po_date: DF.Date | None
		po_no: DF.Data | None
		posting_date: DF.Date
		posting_time: DF.Time | None
		price_list_currency: DF.Link
		remarks: DF.SmallText | None
		represents_company: DF.Link | None
		return_against: DF.Link | None
		rounded_total: DF.Currency
		rounding_adjustment: DF.Currency
		scan_barcode: DF.Data | None
		select_print_heading: DF.Link | None
		selling_price_list: DF.Link
		set_posting_time: DF.Check
		set_target_warehouse: DF.Link | None
		set_warehouse: DF.Link | None
		shipping_address: DF.TextEditor | None
		shipping_address_name: DF.Link | None
		status: DF.Literal[
			"",
			"Draft",
			"Return",
			"Credit Note Issued",
			"Submitted",
			"Paid",
			"Partly Paid",
			"Unpaid",
			"Overdue",
			"Cancelled",
			"Internal Transfer",
		]
		tax_id: DF.Data | None
		taxes: DF.Table[SalesTaxesandCharges]
		taxes_and_charges: DF.Link | None
		tc_name: DF.Link | None
		terms: DF.TextEditor | None
		title: DF.Data | None
		to_date: DF.Date | None
		total: DF.Currency
		total_advance: DF.Currency
		total_net_weight: DF.Float
		total_qty: DF.Float
		total_taxes_and_charges: DF.Currency
		unrealized_profit_loss_account: DF.Link | None
		update_billed_amount_in_delivery_note: DF.Check
		update_billed_amount_in_sales_order: DF.Check
		update_outstanding_for_self: DF.Check
		update_stock: DF.Check
		use_company_roundoff_cost_center: DF.Check
		utm_campaign: DF.Link | None
		utm_content: DF.Data | None
		utm_medium: DF.Link | None
		utm_source: DF.Link | None
		write_off_account: DF.Link | None
		write_off_amount: DF.Currency
		write_off_cost_center: DF.Link | None
		write_off_outstanding_amount_automatically: DF.Check
	# end: auto-generated types

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.status_updater = [
			{
				"source_dt": "Sales Invoice Item",
				"target_field": "billed_amt",
				"target_ref_field": "amount",
				"target_dt": "Sales Order Item",
				"join_field": "so_detail",
				"target_parent_dt": "Sales Order",
				"target_parent_field": "per_billed",
				"source_field": "amount",
				"percent_join_field": "sales_order",
				"status_field": "billing_status",
				"keyword": "Billed",
				"overflow_type": "billing",
				"billing_flag": "update_billed_amount_in_sales_order",
				"extra_cond": """ and exists(select name from `tabSales Invoice`
				where name=`tabSales Invoice Item`.parent and (is_return=0 or update_billed_amount_in_sales_order=1))""",
			}
		]

	def set_indicator(self):
		"""Set indicator for portal"""
		if self.outstanding_amount < 0:
			self.indicator_title = _("Credit Note Issued")
			self.indicator_color = "gray"
		elif self.outstanding_amount > 0 and getdate(self.due_date) >= getdate(nowdate()):
			self.indicator_color = "orange"
			self.indicator_title = _("Unpaid")
		elif self.outstanding_amount > 0 and getdate(self.due_date) < getdate(nowdate()):
			self.indicator_color = "red"
			self.indicator_title = _("Overdue")
		elif cint(self.is_return) == 1:
			self.indicator_title = _("Return")
			self.indicator_color = "gray"
		else:
			self.indicator_color = "green"
			self.indicator_title = _("Paid")

	def validate(self):
		self.validate_auto_set_posting_time()
		super().validate()

		if not self.is_debit_note:
			self.so_dn_required()

		self.validate_with_previous_doc()
		self.validate_uom_is_integer("stock_uom", "stock_qty")
		self.validate_uom_is_integer("uom", "qty")
		self.check_sales_order_on_hold_or_close("sales_order")
		self.validate_debit_to_acc()
		self.clear_unallocated_advances("Sales Invoice Advance", "advances")
		self.validate_item_cost_centers()
		self.check_conversion_rate()
		self.validate_accounts()

		validate_inter_company_party(
			self.doctype, self.customer, self.company, self.inter_company_invoice_reference
		)

		self.validate_dropship_item()

		if cint(self.update_stock):
			self.validate_warehouse()
			self.update_current_stock()

		self.validate_delivery_note()

		if not self.is_opening:
			self.is_opening = "No"

		self.set_against_income_account()

		self.validate_delivery_note_rows_billed_by_invoice()
		self.validate_closed_delivery_notes()
		self.validate_multiple_billing("Delivery Note", "dn_detail", "amount")

		self.set_status()
		self.reset_default_field_value("set_warehouse", "items", "warehouse")

	def validate_accounts(self):
		self.validate_income_account()

	def validate_for_repost(self):
		self.validate_income_account()
		validate_docs_for_voucher_types(["Sales Invoice"])

	def validate_item_cost_centers(self):
		for item in self.items:
			item.validate_cost_center(self.company)

	def validate_income_account(self):
		for item in self.get("items"):
			validate_account_head(item.idx, item.income_account, self.company, _("Income"))

	def before_submit(self):
		self.add_remarks()

	def on_submit(self):
		self.check_prev_docstatus()

		if self.is_return and not self.update_billed_amount_in_sales_order:
			# NOTE status updating bypassed for is_return
			self.status_updater = []

		self.update_status_updater_args()
		self.update_prevdoc_status()

		self.update_billing_status_in_dn()

		# Updating stock ledger should always be called after updating prevdoc status,
		# because updating reserved qty in bin depends upon updated delivered qty in SO
		if self.update_stock == 1:
			for table_name in ["items", "packed_items"]:
				if not self.get(table_name):
					continue

				self.make_bundle_for_sales_purchase_return(table_name)
				self.make_bundle_using_old_serial_batch_fields(table_name)

			self.validate_standalone_serial_nos_customer()
			self.update_stock_ledger()

		# this sequence because outstanding may get -ve
		self.make_gl_entries()

		if self.update_stock == 1:
			self.repost_future_sle_and_gle()

		if not self.is_return:
			self.update_billing_status_for_zero_amount_refdoc("Delivery Note")
			self.update_billing_status_for_zero_amount_refdoc("Sales Order")
			if self.is_opening != "Yes":
				self.check_credit_limit()
				self.check_overdue_billing_threshold()

		if not self.is_return:
			self.update_against_document_in_jv()

		if frappe.get_single_value("Selling Settings", "sales_update_frequency") == "Each Transaction":
			update_company_current_month_sales(self.company)
		update_linked_doc(self.doctype, self.name, self.inter_company_invoice_reference)

		if self.is_return and self.return_against:
			frappe.get_doc(self.doctype, self.return_against).set_status(update=True)

	def on_cancel(self):
		check_if_return_invoice_linked_with_payment_entry(self)

		super().on_cancel()

		self.check_sales_order_on_hold_or_close("sales_order")

		if self.is_return and not self.update_billed_amount_in_sales_order:
			# NOTE status updating bypassed for is_return
			self.status_updater = []

		self.update_status_updater_args()
		self.update_prevdoc_status()
		self.update_billing_status_in_dn()

		if not self.is_return:
			self.update_billing_status_for_zero_amount_refdoc("Delivery Note")
			self.update_billing_status_for_zero_amount_refdoc("Sales Order")

		# Updating stock ledger should always be called after updating prevdoc status,
		# because updating reserved qty in bin depends upon updated delivered qty in SO
		if self.update_stock == 1:
			self.update_stock_ledger()

		self.make_gl_entries_on_cancel()

		if self.update_stock == 1:
			self.repost_future_sle_and_gle()

		self.db_set("status", "Cancelled")

		if frappe.get_single_value("Selling Settings", "sales_update_frequency") == "Each Transaction":
			update_company_current_month_sales(self.company)

		unlink_inter_company_doc(self.doctype, self.name, self.inter_company_invoice_reference)

		self.ignore_linked_doctypes = (
			"GL Entry",
			"Stock Ledger Entry",
			"Repost Item Valuation",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
			"Payment Ledger Entry",
			"Serial and Batch Bundle",
		)

		self.delete_auto_created_batches()

		if self.is_return and self.return_against:
			frappe.get_doc(self.doctype, self.return_against).set_status(update=True)

	def update_status_updater_args(self):
		if not cint(self.update_stock):
			return

		self.status_updater.extend(
			[
				{
					"source_dt": "Sales Invoice Item",
					"target_dt": "Sales Order Item",
					"target_parent_dt": "Sales Order",
					"target_parent_field": "per_delivered",
					"target_field": "delivered_qty",
					"target_ref_field": "qty",
					"source_field": "qty * conversion_factor",
					"target_conversion_factor": "conversion_factor",
					"join_field": "so_detail",
					"percent_join_field": "sales_order",
					"status_field": "delivery_status",
					"keyword": "Delivered",
					"second_source_dt": "Delivery Note Item",
					"second_source_field": "qty * conversion_factor",
					"second_join_field": "so_detail",
					"overflow_type": "delivery",
					"extra_cond": """ and exists(select name from `tabSales Invoice`
					where name=`tabSales Invoice Item`.parent and update_stock = 1)""",
				},
			]
		)

		if not cint(self.is_return):
			return

		self.status_updater.append(
			{
				"source_dt": "Sales Invoice Item",
				"target_dt": "Sales Order Item",
				"join_field": "so_detail",
				"target_field": "returned_qty",
				"target_parent_dt": "Sales Order",
				"source_field": "-1 * qty * conversion_factor",
				"target_conversion_factor": "conversion_factor",
				"second_source_dt": "Delivery Note Item",
				"second_source_field": "-1 * qty * conversion_factor",
				"second_join_field": "so_detail",
				"extra_cond": """ and exists (select name from `tabSales Invoice` where name=`tabSales Invoice Item`.parent and update_stock=1 and is_return=1)""",
				"second_source_extra_cond": """ and exists (select name from `tabDelivery Note` where name=`tabDelivery Note Item`.parent and is_return=1)""",
			}
		)

	def check_credit_limit(self):
		from hisaabdari.selling.doctype.customer.customer import (
			check_credit_limit,
			is_sales_order_credit_check_bypassed,
		)

		validate_against_credit_limit = False
		bypass_credit_limit_check_at_sales_order = is_sales_order_credit_check_bypassed(
			self.customer, self.company
		)

		if bypass_credit_limit_check_at_sales_order:
			validate_against_credit_limit = True

		for d in self.get("items"):
			if not (d.sales_order or d.delivery_note):
				validate_against_credit_limit = True
				break
		if validate_against_credit_limit:
			check_credit_limit(self.customer, self.company, bypass_credit_limit_check_at_sales_order)

	def check_overdue_billing_threshold(self):
		from hisaabdari.selling.doctype.customer.customer import check_overdue_billing_threshold

		check_overdue_billing_threshold(self.customer, self.company)

	@frappe.whitelist()
	def set_missing_values(self, for_validate=False):
		if not self.debit_to:
			self.debit_to = get_party_account("Customer", self.customer, self.company)
			self.party_account_currency = frappe.db.get_value(
				"Account", self.debit_to, "account_currency", cache=True
			)
		if not self.due_date and self.customer:
			self.due_date = get_due_date(
				self.posting_date,
				"Customer",
				self.customer,
				self.company,
				template_name=self.payment_terms_template,
			)

		super().set_missing_values(for_validate)

	def on_update_after_submit(self):
		fields_to_check = [
			"additional_discount_account",
			"unrealized_profit_loss_account",
			"is_opening",
		]
		child_tables = {
			"items": ("income_account", "expense_account", "discount_account"),
			"taxes": ("account_head",),
		}
		needs_repost = self.check_if_fields_updated(fields_to_check, child_tables)
		if needs_repost:
			self.validate_for_repost()
			self.repost_accounting_entries()

	def get_company_abbr(self):
		return frappe.db.sql("select abbr from tabCompany where name=%s", self.company)[0][0]

	def validate_debit_to_acc(self):
		if not self.debit_to:
			self.debit_to = get_party_account("Customer", self.customer, self.company)
			if not self.debit_to:
				self.raise_missing_debit_credit_account_error("Customer", self.customer)

		account = frappe.get_cached_value(
			"Account", self.debit_to, ["account_type", "report_type", "account_currency"], as_dict=True
		)

		if not account:
			frappe.throw(_("Debit To is required"), title=_("Account Missing"))

		if account.report_type != "Balance Sheet":
			msg = (
				_("Please ensure {} account is a Balance Sheet account.").format(frappe.bold(_("Debit To")))
				+ " "
			)
			msg += _(
				"You can change the parent account to a Balance Sheet account or select a different account."
			)
			frappe.throw(msg, title=_("Invalid Account"))

		if self.customer and account.account_type != "Receivable":
			msg = (
				_("Please ensure {} account {} is a Receivable account.").format(
					frappe.bold(_("Debit To")), frappe.bold(self.debit_to)
				)
				+ " "
			)
			msg += _("Change the account type to Receivable or select a different account.")
			frappe.throw(msg, title=_("Invalid Account"))

		self.party_account_currency = account.account_currency

	def validate_with_previous_doc(self):
		super().validate_with_previous_doc(
			{
				"Sales Order": {
					"ref_dn_field": "sales_order",
					"compare_fields": [
						["customer", "="],
						["company", "="],
						["currency", "="],
					],
				},
				"Sales Order Item": {
					"ref_dn_field": "so_detail",
					"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
					"is_child_table": True,
					"allow_duplicate_prev_row_id": True,
				},
				"Delivery Note": {
					"ref_dn_field": "delivery_note",
					"compare_fields": [
						["customer", "="],
						["company", "="],
						["currency", "="],
					],
				},
				"Delivery Note Item": {
					"ref_dn_field": "dn_detail",
					"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
					"is_child_table": True,
					"allow_duplicate_prev_row_id": True,
				},
			}
		)

		if (
			cint(frappe.get_single_value("Selling Settings", "maintain_same_sales_rate"))
			and not self.is_return
			and not self.is_internal_customer
		):
			self.validate_rate_with_reference_doc(
				[["Sales Order", "sales_order", "so_detail"], ["Delivery Note", "delivery_note", "dn_detail"]]
			)

	def validate_closed_delivery_notes(self):
		delivery_notes = {d.delivery_note for d in self.items if d.delivery_note}
		if self.is_return or not delivery_notes:
			return

		if closed := frappe.get_all(
			"Delivery Note", filters={"name": ("in", list(delivery_notes)), "status": "Closed"}, pluck="name"
		):
			frappe.throw(
				_("Delivery Note {0} is closed and cannot be invoiced").format(
					", ".join(frappe.bold(name) for name in closed)
				)
			)

	def validate_delivery_note_rows_billed_by_invoice(self):
		dn_details = [d.dn_detail for d in self.items if d.dn_detail]
		if self.is_return or not dn_details:
			return

		billing_invoices = frappe._dict(
			frappe.get_all(
				"Delivery Note Item",
				filters={"name": ("in", dn_details), "against_sales_invoice": ("is", "set")},
				fields=["name", "against_sales_invoice"],
				as_list=True,
			)
		)
		for d in self.items:
			invoice = billing_invoices.get(d.dn_detail)
			if invoice and invoice != self.name:
				frappe.throw(
					_(
						"Row #{0}: Delivery Note {1} was created from Sales Invoice {2}, which already bills it"
					).format(d.idx, frappe.bold(d.delivery_note), get_link_to_form("Sales Invoice", invoice))
				)

	def set_against_income_account(self):
		"""Set against account for debit to account"""
		against_acc = []
		for d in self.get("items"):
			if d.income_account and d.income_account not in against_acc:
				against_acc.append(d.income_account)
		self.against_income_account = ",".join(against_acc)

	def force_set_against_income_account(self):
		self.set_against_income_account()
		frappe.db.set_value(self.doctype, self.name, "against_income_account", self.against_income_account)

	def add_remarks(self):
		if not self.remarks:
			if self.po_no:
				self.remarks = _("Against Customer Order {0}").format(self.po_no)
				if self.po_date:
					self.remarks += " " + _("dated {0}").format(formatdate(self.po_date))

	def validate_auto_set_posting_time(self):
		# Don't auto set the posting date and time if invoice is amended
		if self.is_new() and self.amended_from:
			self.set_posting_time = 1

		self.validate_posting_time()

	def so_dn_required(self):
		"""check in manage account if sales order / delivery note required or not."""
		if self.is_return:
			return

		prev_doc_field_map = {
			"Sales Order": ["so_required", None],
			"Delivery Note": ["dn_required", "update_stock"],
		}
		for key, value in prev_doc_field_map.items():
			if frappe.get_single_value("Selling Settings", value[0]) == "Yes":
				if frappe.get_value("Customer", self.customer, value[0]):
					continue

				for d in self.get("items"):
					if d.item_code and not d.get(key.lower().replace(" ", "_")) and not (
						value[1] and self.get(value[1])
					):
						msgprint(
							_("{0} is mandatory for Item {1}").format(key, d.item_code), raise_exception=1
						)

	def validate_warehouse(self):
		super().validate_warehouse()

		for d in self.get_item_list():
			if (
				not d.warehouse
				and d.item_code
				and frappe.get_cached_value("Item", d.item_code, "is_stock_item")
			):
				frappe.throw(_("Warehouse required for stock Item {0}").format(d.item_code))

	def validate_delivery_note(self):
		"""If items are linked with a delivery note, stock cannot be updated again."""
		if not cint(self.update_stock):
			return

		notes = [item.delivery_note for item in self.items if item.delivery_note]
		if notes:
			frappe.throw(
				_("Stock cannot be updated against the following Delivery Notes: {0}").format(
					comma_and(notes)
				),
			)

	def validate_dropship_item(self):
		"""If items are drop shipped, stock cannot be updated."""
		if not cint(self.update_stock):
			return

		if any(item.delivered_by_supplier for item in self.items):
			frappe.throw(
				_(
					"Stock cannot be updated because the invoice contains a drop shipping item. Please disable 'Update Stock' or remove the drop shipping item."
				),
			)

	def update_current_stock(self):
		bin_qty_map = get_bin_qty_map(self.items + self.packed_items)

		for item in self.items:
			if item.item_code and item.warehouse:
				bin_data = bin_qty_map.get((item.item_code, item.warehouse))
				item.actual_qty = bin_data.actual_qty if bin_data else 0

		for packed_item in self.packed_items:
			bin_data = bin_qty_map.get((packed_item.item_code, packed_item.warehouse))
			packed_item.actual_qty = bin_data.actual_qty if bin_data else 0
			packed_item.projected_qty = bin_data.projected_qty if bin_data else 0

	def check_prev_docstatus(self):
		for d in self.get("items"):
			if (
				d.sales_order
				and frappe.db.get_value("Sales Order", d.sales_order, "docstatus", cache=True) != 1
			):
				frappe.throw(_("Sales Order {0} is not submitted").format(d.sales_order))

			if (
				d.delivery_note
				and frappe.db.get_value("Delivery Note", d.delivery_note, "docstatus", cache=True) != 1
			):
				throw(_("Delivery Note {0} is not submitted").format(d.delivery_note))

	def make_gl_entries(self, gl_entries=None, from_repost=False):
		from hisaabdari.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries

		auto_accounting_for_stock = hisaabdari.is_perpetual_inventory_enabled(self.company)
		if not gl_entries:
			gl_entries = self.get_gl_entries()

		if gl_entries:
			# if POS and amount is written off, updating outstanding amt after posting all gl entries
			update_outstanding = "No" if self.write_off_account else "Yes"

			if self.docstatus == 1:
				make_gl_entries(
					gl_entries,
					update_outstanding=update_outstanding,
					merge_entries=False,
					from_repost=from_repost,
				)

				self.make_exchange_gain_loss_journal()
			elif self.docstatus == 2:
				make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

			if update_outstanding == "No":
				update_voucher_outstanding(
					voucher_type=self.doctype,
					voucher_no=self.return_against
					if cint(self.is_return) and self.return_against
					else self.name,
					account=self.debit_to,
					party_type="Customer",
					party=self.customer,
				)

		elif self.docstatus == 2 and cint(self.update_stock) and cint(auto_accounting_for_stock):
			make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def get_gl_entries(self, inventory_account_map=None):
		from hisaabdari.accounts.general_ledger import merge_similar_entries

		gl_entries = []

		self.make_customer_gl_entry(gl_entries)

		self.make_tax_gl_entries(gl_entries)
		self.make_internal_transfer_gl_entries(gl_entries)

		self.make_item_gl_entries(gl_entries)
		self.make_precision_loss_gl_entry(gl_entries)
		self.make_discount_gl_entries(gl_entries)

		gl_entries = make_regional_gl_entries(gl_entries, self)

		# merge gl entries before adding pos entries
		gl_entries = merge_similar_entries(gl_entries)

		self.make_gle_for_rounding_adjustment(gl_entries)

		self.set_transaction_currency_and_rate_in_gl_map(gl_entries)
		return gl_entries

	def make_customer_gl_entry(self, gl_entries):
		# Checked both rounding_adjustment and rounded_total
		# because rounded_total had value even before introduction of posting GLE based on rounded total
		grand_total = (
			self.rounded_total if (self.rounding_adjustment and self.rounded_total) else self.grand_total
		)
		base_grand_total = flt(
			self.base_rounded_total
			if (self.base_rounding_adjustment and self.base_rounded_total)
			else self.base_grand_total,
			self.precision("base_grand_total"),
		)

		if grand_total and not self.is_internal_transfer():
			against_voucher = self.name
			if self.is_return and self.return_against and not self.update_outstanding_for_self:
				against_voucher = self.return_against

			# Did not use base_grand_total to book rounding loss gle
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.debit_to,
						"party_type": "Customer",
						"party": self.customer,
						"due_date": self.due_date,
						"against": self.against_income_account,
						"debit": base_grand_total,
						"debit_in_account_currency": base_grand_total
						if self.party_account_currency == self.company_currency
						else grand_total,
						"debit_in_transaction_currency": grand_total,
						"against_voucher": against_voucher,
						"against_voucher_type": self.doctype,
						"cost_center": self.cost_center,
					},
					self.party_account_currency,
					item=self,
				)
			)

	def make_tax_gl_entries(self, gl_entries):
		enable_discount_accounting = cint(
			frappe.get_single_value("Selling Settings", "enable_discount_accounting")
		)

		for tax in self.get("taxes"):
			amount, base_amount = self.get_tax_amounts(tax, enable_discount_accounting)

			if flt(tax.base_tax_amount_after_discount_amount):
				account_currency = get_account_currency(tax.account_head)
				gl_entries.append(
					self.get_gl_dict(
						{
							"account": tax.account_head,
							"against": self.customer,
							"credit": flt(base_amount, tax.precision("tax_amount_after_discount_amount")),
							"credit_in_account_currency": (
								flt(base_amount, tax.precision("base_tax_amount_after_discount_amount"))
								if account_currency == self.company_currency
								else flt(amount, tax.precision("tax_amount_after_discount_amount"))
							),
							"credit_in_transaction_currency": flt(
								amount, tax.precision("tax_amount_after_discount_amount")
							),
							"cost_center": tax.cost_center,
						},
						account_currency,
						item=tax,
					)
				)

	def make_internal_transfer_gl_entries(self, gl_entries):
		if self.is_internal_transfer() and flt(self.base_total_taxes_and_charges):
			account_currency = get_account_currency(self.unrealized_profit_loss_account)
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.unrealized_profit_loss_account,
						"against": self.customer,
						"debit": flt(self.total_taxes_and_charges),
						"debit_in_account_currency": flt(self.base_total_taxes_and_charges),
						"debit_in_transaction_currency": flt(self.total_taxes_and_charges),
						"cost_center": self.cost_center,
					},
					account_currency,
					item=self,
				)
			)

	def make_item_gl_entries(self, gl_entries, deferred_return_items=None):
		# income account gl entries
		enable_discount_accounting = cint(
			frappe.get_single_value("Selling Settings", "enable_discount_accounting")
		)

		for item in self.get("items"):
			if flt(item.base_net_amount, item.precision("base_net_amount")) or enable_discount_accounting:
				# Do not book income for transfer within same company
				if self.is_internal_transfer():
					continue

				income_account = self.get_item_income_account(item, deferred_return_items)

				amount, base_amount = self.get_amount_and_base_amount(item, enable_discount_accounting)

				account_currency = get_account_currency(income_account)
				gl_entries.append(
					self.get_gl_dict(
						{
							"account": income_account,
							"against": self.customer,
							"credit": flt(base_amount, item.precision("base_net_amount")),
							"credit_in_account_currency": (
								flt(base_amount, item.precision("base_net_amount"))
								if account_currency == self.company_currency
								else flt(amount, item.precision("net_amount"))
							),
							"credit_in_transaction_currency": flt(amount, item.precision("net_amount")),
							"cost_center": item.cost_center,
						},
						account_currency,
						item=item,
					)
				)

		# expense account gl entries
		if cint(self.update_stock) and hisaabdari.is_perpetual_inventory_enabled(self.company):
			gl_entries += super().get_gl_entries()

	def get_item_income_account(self, item, deferred_return_items=None):
		return item.income_account

	@property
	def enable_discount_accounting(self):
		if not hasattr(self, "_enable_discount_accounting"):
			self._enable_discount_accounting = cint(
				frappe.get_single_value("Selling Settings", "enable_discount_accounting")
			)

		return self._enable_discount_accounting

	def make_gle_for_rounding_adjustment(self, gl_entries):
		if (
			flt(self.rounding_adjustment, self.precision("rounding_adjustment"))
			and self.base_rounding_adjustment
			and not self.is_internal_transfer()
		):
			(
				round_off_account,
				round_off_cost_center,
				round_off_for_opening,
			) = get_round_off_account_and_cost_center(
				self.company, "Sales Invoice", self.name, self.use_company_roundoff_cost_center
			)

			if self.is_opening == "Yes" and self.rounding_adjustment:
				if not round_off_for_opening:
					frappe.throw(
						_(
							"Opening Invoice has rounding adjustment of {0}.<br><br> '{1}' account is required to post these values. Please set it in Company: {2}.<br><br> Or, '{3}' can be enabled to not post any rounding adjustment."
						).format(
							frappe.bold(self.rounding_adjustment),
							frappe.bold("Round Off for Opening"),
							get_link_to_form("Company", self.company),
							frappe.bold("Disable Rounded Total"),
						)
					)
				else:
					round_off_account = round_off_for_opening

			rounding_adjustment = flt(self.rounding_adjustment, self.precision("rounding_adjustment"))
			base_rounding_adjustment = flt(
				self.base_rounding_adjustment, self.precision("base_rounding_adjustment")
			)
			round_off_account_currency = get_account_currency(round_off_account)
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": round_off_account,
						"against": self.customer,
						"credit_in_account_currency": base_rounding_adjustment
						if round_off_account_currency == self.company_currency
						else rounding_adjustment,
						"credit_in_transaction_currency": rounding_adjustment,
						"credit": base_rounding_adjustment,
						"cost_center": round_off_cost_center
						if self.use_company_roundoff_cost_center
						else (self.cost_center or round_off_cost_center),
					},
					round_off_account_currency,
					item=self,
				)
			)

	def update_billing_status_in_dn(self, update_modified=True):
		if self.is_return and not self.update_billed_amount_in_delivery_note:
			return

		updated_delivery_notes = []

		SalesInvoiceItem = frappe.qb.DocType("Sales Invoice Item")
		from frappe.query_builder.functions import Coalesce, Sum

		for d in self.get("items"):
			if d.dn_detail:
				query = (
					frappe.qb.from_(SalesInvoiceItem)
					.select(Coalesce(Sum(SalesInvoiceItem.amount), 0))
					.where(SalesInvoiceItem.dn_detail == d.dn_detail)
					.where(SalesInvoiceItem.docstatus == 1)
				)

				res = query.run()
				billed_amt = res[0][0] if res else 0

				frappe.db.set_value(
					"Delivery Note Item",
					d.dn_detail,
					"billed_amt",
					billed_amt,
					update_modified=update_modified,
				)
				updated_delivery_notes.append(d.delivery_note)
			elif d.so_detail:
				updated_delivery_notes += update_billed_amount_based_on_so(d.so_detail, update_modified)

		for dn in set(updated_delivery_notes):
			frappe.get_doc("Delivery Note", dn).update_billing_percentage(update_modified=update_modified)

	def on_recurring(self, reference_doc, auto_repeat_doc):
		super().on_recurring(reference_doc, auto_repeat_doc)
		self.po_no = reference_doc.po_no
		# The payment schedule is rebuilt from the template, relative to the new posting date.
		self.payment_terms_template = reference_doc.payment_terms_template
		self.due_date = None

	def set_status(self, update=False, status=None, update_modified=True):
		if self.is_new():
			if self.get("amended_from"):
				self.status = "Draft"
			return

		outstanding_amount = flt(self.outstanding_amount, self.precision("outstanding_amount"))
		total = get_total_in_party_account_currency(self)

		if not status:
			if self.docstatus == 2:
				status = "Cancelled"
			elif self.docstatus == 1:
				if self.is_internal_transfer():
					self.status = "Internal Transfer"
				elif is_overdue(self, total):
					self.status = "Overdue"
				elif 0 < outstanding_amount < total:
					self.status = "Partly Paid"
				elif outstanding_amount > 0 and getdate(self.due_date) >= getdate():
					self.status = "Unpaid"
				# Check if outstanding amount is 0 due to credit note issued against invoice
				elif self.is_return == 0 and frappe.db.get_value(
					"Sales Invoice", {"is_return": 1, "return_against": self.name, "docstatus": 1}
				):
					self.status = "Credit Note Issued"
				elif self.is_return == 1:
					self.status = "Return"
				elif outstanding_amount <= 0:
					self.status = "Paid"
				else:
					self.status = "Submitted"

			else:
				self.status = "Draft"

		if update:
			self.db_set("status", self.status, update_modified=update_modified)


def get_total_in_party_account_currency(doc):
	total_fieldname = "grand_total" if doc.disable_rounded_total else "rounded_total"
	if doc.party_account_currency != doc.currency:
		total_fieldname = "base_" + total_fieldname

	return flt(doc.get(total_fieldname), doc.precision(total_fieldname))


def is_overdue(doc, total):
	outstanding_amount = flt(doc.outstanding_amount, doc.precision("outstanding_amount"))
	if outstanding_amount <= 0:
		return

	today = getdate()
	if not doc.get("payment_schedule"):
		return getdate(doc.due_date) < today

	# calculate payable amount till date
	payment_amount_field = (
		"base_payment_amount" if doc.party_account_currency != doc.currency else "payment_amount"
	)

	payable_amount = flt(
		sum(
			payment.get(payment_amount_field)
			for payment in doc.payment_schedule
			if getdate(payment.due_date) < today
		),
		doc.precision("outstanding_amount"),
	)

	return flt(total - outstanding_amount, doc.precision("outstanding_amount")) < payable_amount


def validate_inter_company_party(doctype, party, company, inter_company_reference):
	if not party:
		return

	if doctype in ["Sales Invoice", "Sales Order"]:
		partytype, ref_partytype, internal = "Customer", "Supplier", "is_internal_customer"

		if doctype == "Sales Invoice":
			ref_doc = "Purchase Invoice"
		else:
			ref_doc = "Purchase Order"
	else:
		partytype, ref_partytype, internal = "Supplier", "Customer", "is_internal_supplier"

		if doctype == "Purchase Invoice":
			ref_doc = "Sales Invoice"
		else:
			ref_doc = "Sales Order"

	if inter_company_reference:
		doc = frappe.get_doc(ref_doc, inter_company_reference)
		ref_party = doc.supplier if doctype in ["Sales Invoice", "Sales Order"] else doc.customer
		if (
			frappe.db.get_value(partytype, {"represents_company": doc.company, "disabled": 0}, "name")
			!= party
		):
			frappe.throw(_("Invalid {0} for Inter Company Transaction.").format(_(partytype)))
		if frappe.get_cached_value(ref_partytype, ref_party, "represents_company") != company:
			frappe.throw(_("Invalid Company for Inter Company Transaction."))

	elif frappe.db.get_value(partytype, {"name": party, internal: 1}, "name") == party:
		companies = frappe.get_all(
			"Allowed To Transact With",
			fields=["company"],
			filters={"parenttype": partytype, "parent": party},
		)
		companies = [d.company for d in companies]
		if company not in companies:
			frappe.throw(
				_(
					"{0} not allowed to transact with {1}. Please change the Company or add the Company in the 'Allowed To Transact With'-Section in the Customer record."
				).format(_(partytype), company)
			)


def get_inter_company_counterpart(doctype: str) -> tuple[str, str]:
	"""Return the counterpart doctype and the field both documents use to reference each other."""
	if doctype in ["Sales Invoice", "Purchase Invoice"]:
		ref_doc = "Purchase Invoice" if doctype == "Sales Invoice" else "Sales Invoice"
		return ref_doc, "inter_company_invoice_reference"

	ref_doc = "Purchase Order" if doctype == "Sales Order" else "Sales Order"
	return ref_doc, "inter_company_order_reference"


def update_linked_doc(doctype, name, inter_company_reference):
	ref_doc, ref_field = get_inter_company_counterpart(doctype)
	if inter_company_reference:
		frappe.db.set_value(ref_doc, inter_company_reference, ref_field, name)


def unlink_inter_company_doc(doctype, name, inter_company_reference):
	ref_doc, ref_field = get_inter_company_counterpart(doctype)
	if not inter_company_reference:
		return

	frappe.db.set_value(doctype, name, ref_field, "")
	if frappe.db.get_value(ref_doc, inter_company_reference, ref_field) != name:
		return

	remaining_counterpart = frappe.db.get_value(doctype, {ref_field: inter_company_reference, "docstatus": 1})
	frappe.db.set_value(ref_doc, inter_company_reference, ref_field, remaining_counterpart or "")


@frappe.whitelist()
def get_bank_cash_account(mode_of_payment, company):
	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account"
	)
	if not account:
		frappe.throw(
			_("Please set default Cash or Bank account in Mode of Payment {0}").format(
				get_link_to_form("Mode of Payment", mode_of_payment)
			),
			title=_("Missing Account"),
		)
	return {"account": account}


@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None):
	def set_missing_values(source, target):
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty = flt(source_doc.qty) - flt(source_doc.delivered_qty)
		target_doc.stock_qty = target_doc.qty * flt(source_doc.conversion_factor)

		target_doc.base_amount = target_doc.qty * flt(source_doc.base_rate)
		target_doc.amount = target_doc.qty * flt(source_doc.rate)

	doclist = get_mapped_doc(
		"Sales Invoice",
		source_name,
		{
			"Sales Invoice": {"doctype": "Delivery Note", "validation": {"docstatus": ["=", 1]}},
			"Sales Invoice Item": {
				"doctype": "Delivery Note Item",
				"field_map": {
					"name": "si_detail",
					"parent": "against_sales_invoice",
					"serial_no": "serial_no",
					"sales_order": "against_sales_order",
					"so_detail": "so_detail",
					"cost_center": "cost_center",
				},
				"postprocess": update_item,
				"condition": lambda doc: doc.delivered_by_supplier != 1
				and not doc.dn_detail
				and doc.qty - doc.delivered_qty > 0,
			},
			"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "reset_value": True},
		},
		target_doc,
		set_missing_values,
	)

	return doclist


@frappe.whitelist()
def make_sales_return(source_name, target_doc=None):
	from hisaabdari.controllers.sales_and_purchase_return import make_return_doc

	return make_return_doc("Sales Invoice", source_name, target_doc)


def get_inter_company_details(doc, doctype):
	if doctype in ["Sales Invoice", "Sales Order", "Delivery Note"]:
		parties = frappe.db.get_all(
			"Supplier",
			fields=["name"],
			filters={"disabled": 0, "is_internal_supplier": 1, "represents_company": doc.company},
		)
		company = frappe.get_cached_value("Customer", doc.customer, "represents_company")

		if not parties:
			frappe.throw(
				_("No Supplier found for Inter Company Transactions which represents company {0}").format(
					frappe.bold(doc.company)
				)
			)

		party = get_internal_party(parties, "Supplier", doc)
	else:
		parties = frappe.db.get_all(
			"Customer",
			fields=["name"],
			filters={"disabled": 0, "is_internal_customer": 1, "represents_company": doc.company},
		)
		company = frappe.get_cached_value("Supplier", doc.supplier, "represents_company")

		if not parties:
			frappe.throw(
				_("No Customer found for Inter Company Transactions which represents company {0}").format(
					frappe.bold(doc.company)
				)
			)

		party = get_internal_party(parties, "Customer", doc)

	return {"party": party, "company": company}


def get_internal_party(parties, link_doctype, doc):
	if len(parties) == 1:
		party = parties[0].name
	else:
		# If more than one Internal Supplier/Customer, get supplier/customer on basis of address
		if doc.get("company_address") or doc.get("shipping_address"):
			party = frappe.db.get_value(
				"Dynamic Link",
				{
					"parent": doc.get("company_address") or doc.get("shipping_address"),
					"parenttype": "Address",
					"link_doctype": link_doctype,
				},
				"link_name",
			)

			if not party:
				party = parties[0].name
		else:
			party = parties[0].name

	return party


def validate_inter_company_transaction(doc, doctype):
	details = get_inter_company_details(doc, doctype)
	price_list = (
		doc.selling_price_list
		if doctype in ["Sales Invoice", "Sales Order", "Delivery Note"]
		else doc.buying_price_list
	)
	valid_price_list = frappe.db.get_value("Price List", {"name": price_list, "buying": 1, "selling": 1})
	if not valid_price_list and not doc.is_internal_transfer():
		frappe.throw(_("Selected Price List should have buying and selling fields checked."))

	party = details.get("party")
	if not party:
		partytype = "Supplier" if doctype in ["Sales Invoice", "Sales Order"] else "Customer"
		frappe.throw(_("No {0} found for Inter Company Transactions.").format(partytype))


def validate_no_counterpart_sales_invoice(purchase_invoice):
	"""Purchase Invoice rows link no Sales Invoice rows, so its header link marks it as already invoiced."""
	if sales_invoice := purchase_invoice.inter_company_invoice_reference:
		frappe.throw(
			_(
				"Cannot create Intercompany Sales Invoice. Purchase Invoice {0} already has Sales Invoice {1}."
			).format(purchase_invoice.name, get_link_to_form("Sales Invoice", sales_invoice))
		)


@frappe.whitelist()
def make_inter_company_purchase_invoice(source_name, target_doc=None):
	return make_inter_company_transaction("Sales Invoice", source_name, target_doc)


@hisaabdari.allow_regional
def make_regional_gl_entries(gl_entries, doc):
	return gl_entries


def make_inter_company_transaction(doctype, source_name, target_doc=None):
	if doctype in ["Sales Invoice", "Sales Order"]:
		source_doc = frappe.get_doc(doctype, source_name)
		target_doctype = "Purchase Invoice" if doctype == "Sales Invoice" else "Purchase Order"
		target_detail_field = "sales_invoice_item" if doctype == "Sales Invoice" else "sales_order_item"
		source_document_warehouse_field = "target_warehouse"
		target_document_warehouse_field = "from_warehouse"
		received_items = get_received_items(source_name, target_doctype, target_detail_field)
	else:
		source_doc = frappe.get_doc(doctype, source_name)
		target_doctype = "Sales Invoice" if doctype == "Purchase Invoice" else "Sales Order"
		source_document_warehouse_field = "from_warehouse"
		target_document_warehouse_field = "target_warehouse"
		received_items = (
			get_received_items(source_name, "Sales Order", "purchase_order_item")
			if doctype == "Purchase Order"
			else {}
		)

	if doctype != "Purchase Invoice":
		validate_not_made_from_counterpart(source_doc, target_doctype, received_items)

	validate_inter_company_transaction(source_doc, doctype)
	details = get_inter_company_details(source_doc, doctype)

	def set_missing_values(source, target):
		target.conversion_rate = target.plc_conversion_rate = 0
		target.run_method("set_missing_values")
		set_purchase_references(target)

	def update_details(source_doc, target_doc, source_parent):
		def _validate_address_link(address, link_doctype, link_name):
			return frappe.db.get_value(
				"Dynamic Link",
				{
					"parent": address,
					"parenttype": "Address",
					"link_doctype": link_doctype,
					"link_name": link_name,
				},
				"parent",
			)

		_, reference_field = get_inter_company_counterpart(target_doc.doctype)
		target_doc.set(reference_field, source_doc.name)
		clear_inapplicable_terms(target_doc)
		if target_doc.doctype in ["Purchase Invoice", "Purchase Order"]:
			target_doc.company = details.get("company")
			target_doc.supplier = details.get("party")
			target_doc.is_internal_supplier = 1
			target_doc.ignore_pricing_rule = 1
			target_doc.buying_price_list = source_doc.selling_price_list

			# Invert Addresses
			if source_doc.company_address and _validate_address_link(
				source_doc.company_address, "Supplier", details.get("party")
			):
				update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
			if source_doc.dispatch_address_name and _validate_address_link(
				source_doc.dispatch_address_name, "Company", details.get("company")
			):
				update_address(
					target_doc,
					"dispatch_address",
					"dispatch_address_display",
					source_doc.dispatch_address_name,
				)
			if source_doc.shipping_address_name and _validate_address_link(
				source_doc.shipping_address_name, "Company", details.get("company")
			):
				update_address(
					target_doc,
					"shipping_address",
					"shipping_address_display",
					source_doc.shipping_address_name,
				)
			if source_doc.customer_address and _validate_address_link(
				source_doc.customer_address, "Company", details.get("company")
			):
				update_address(
					target_doc, "billing_address", "billing_address_display", source_doc.customer_address
				)

			update_taxes(
				target_doc,
				party=target_doc.supplier,
				party_type="Supplier",
				company=target_doc.company,
				doctype=target_doc.doctype,
				party_address=target_doc.supplier_address,
				company_address=target_doc.shipping_address,
			)

		else:
			target_doc.company = details.get("company")
			target_doc.customer = details.get("party")
			target_doc.selling_price_list = source_doc.buying_price_list

			if source_doc.supplier_address and _validate_address_link(
				source_doc.supplier_address, "Company", details.get("company")
			):
				update_address(
					target_doc, "company_address", "company_address_display", source_doc.supplier_address
				)
			if source_doc.shipping_address and _validate_address_link(
				source_doc.shipping_address, "Customer", details.get("party")
			):
				update_address(
					target_doc, "shipping_address_name", "shipping_address", source_doc.shipping_address
				)
			if source_doc.shipping_address and _validate_address_link(
				source_doc.shipping_address, "Customer", details.get("party")
			):
				update_address(target_doc, "customer_address", "address_display", source_doc.shipping_address)

			update_taxes(
				target_doc,
				party=target_doc.customer,
				party_type="Customer",
				company=target_doc.company,
				doctype=target_doc.doctype,
				party_address=target_doc.customer_address,
				company_address=target_doc.company_address,
				shipping_address_name=target_doc.shipping_address_name,
			)

	def get_pending_qty(row):
		received_stock_qty = received_items.get(row.name, 0.0)
		if not received_stock_qty:
			return flt(row.qty)

		pending_stock_qty = flt(flt(row.stock_qty) - received_stock_qty, row.precision("stock_qty"))
		return flt(max(pending_stock_qty, 0) / (flt(row.conversion_factor) or 1), row.precision("qty"))

	def update_item(source, target, source_parent):
		target.qty = get_pending_qty(source)
		if source.doctype == "Purchase Order Item" and target.doctype == "Sales Order Item":
			target.purchase_order = source.parent
			target.purchase_order_item = source.name

		if (
			source.get("purchase_order")
			and source.get("purchase_order_item")
			and target.doctype == "Purchase Invoice Item"
		):
			target.purchase_order = source.purchase_order
			target.po_detail = source.purchase_order_item

		if (source.get("serial_no") or source.get("batch_no")) and not source.get("serial_and_batch_bundle"):
			target.use_serial_batch_fields = 1

		clear_item_tax_template_of_other_company(target, details.get("company"))

	item_field_map = {
		"doctype": target_doctype + " Item",
		"field_no_map": ["income_account", "expense_account", "cost_center", "warehouse"],
		"field_map": {
			"rate": "rate",
		},
		"postprocess": update_item,
		"condition": lambda doc: get_pending_qty(doc) > 0,
	}

	if doctype in ["Sales Invoice", "Sales Order"]:
		item_field_map["field_map"].update(
			{
				"name": target_detail_field,
			}
		)

	if source_doc.get("update_stock"):
		item_field_map["field_map"].update(
			{
				source_document_warehouse_field: target_document_warehouse_field,
				"batch_no": "batch_no",
				"serial_no": "serial_no",
			}
		)
	elif target_doctype == "Sales Order":
		item_field_map["field_map"].update(
			{
				source_document_warehouse_field: "warehouse",
			}
		)

	doclist = get_mapped_doc(
		doctype,
		source_name,
		{
			doctype: {
				"doctype": target_doctype,
				"validation": {"docstatus": ["=", 1]},
				"postprocess": update_details,
				"set_target_warehouse": "set_from_warehouse",
				"field_no_map": [*CROSS_PARTY_FIELD_NO_MAP, "set_warehouse", "cost_center"],
			},
			doctype + " Item": item_field_map,
		},
		target_doc,
		set_missing_values,
	)
	if doctype == "Purchase Invoice":
		validate_no_counterpart_sales_invoice(source_doc)

	if not doclist.get("items"):
		if target_doctype in ("Sales Invoice", "Purchase Invoice"):
			message = _(
				"Cannot create Intercompany {0}. All items in the source {1} have already been fully invoiced. "
				"Please check the existing linked {2}s."
			)
		else:
			message = _(
				"Cannot create Intercompany {0}. All items in the source {1} have already been fully ordered. "
				"Please check the existing linked {2}s."
			)
		frappe.throw(message.format(target_doctype, doctype, target_doctype))

	return doclist


def validate_not_made_from_counterpart(source_doc, target_doctype, received_items):
	"""A document made from its counterpart links it, but the counterpart rows link none of its rows back."""
	reference_field = get_inter_company_counterpart(source_doc.doctype)[1]
	reference = source_doc.get(reference_field)
	if reference and not any(row.name in received_items for row in source_doc.items):
		frappe.throw(
			_("Cannot create Intercompany {0}. {1} {2} was created from {0} {3}.").format(
				target_doctype,
				source_doc.doctype,
				source_doc.name,
				get_link_to_form(target_doctype, reference),
			)
		)


def clear_item_tax_template_of_other_company(item, company):
	if (
		item.get("item_tax_template")
		and frappe.get_cached_value("Item Tax Template", item.item_tax_template, "company") != company
	):
		item.item_tax_template = None


@frappe.whitelist()
def get_received_items(reference_name: str, doctype: str, reference_fieldname: str):
	# The targets and reference fields the callers use. Stating them rejects a caller-supplied
	# doctype that would otherwise be filtered on a column it does not have.
	reference_fields = {
		"Purchase Invoice": ("inter_company_invoice_reference", "Sales Invoice", "sales_invoice_item"),
		"Purchase Order": ("inter_company_order_reference", "Sales Order", "sales_order_item"),
		"Sales Order": ("inter_company_order_reference", "Purchase Order", "purchase_order_item"),
	}
	if doctype not in reference_fields:
		frappe.throw(_("Invalid doctype {0}").format(doctype), frappe.PermissionError)

	reference_field, source_doctype, expected_fieldname = reference_fields[doctype]

	# The targets belong to the counterpart company and the caller may legitimately not read them, so
	# the source document decides access. doc= brings User Permissions in.
	frappe.has_permission(source_doctype, doc=reference_name, throw=True)

	# `reference_fieldname` becomes a selected column and the result key, so it has to be this target's
	# own reference field: any other item-table column would be returned from unauthorised rows.
	if reference_fieldname != expected_fieldname:
		frappe.throw(
			_("{0} is not a valid reference field for {1}").format(reference_fieldname, doctype),
			frappe.ValidationError,
		)

	received_items_map = {}
	for item in get_inter_company_items(
		doctype, {reference_field: reference_name}, reference_fieldname, ["stock_qty"]
	):
		key = item.get(reference_fieldname)
		if key:
			received_items_map[key] = received_items_map.get(key, 0.0) + flt(item.stock_qty)

	return received_items_map


def get_inter_company_items(doctype, filters, reference_fieldname, fields):
	"""Items of the submitted documents matching `filters`, and of their returns for Purchase Invoices.
	A return row links only the invoice row it returns, so it gets that row's `reference_fieldname`."""
	parents = frappe.get_all(doctype, filters={**filters, "docstatus": 1}, pluck="name")
	if not parents:
		return []

	fields = ["name", reference_fieldname, *fields]
	if doctype == "Purchase Invoice":
		parents += frappe.get_all(
			doctype, filters={"return_against": ("in", parents), "docstatus": 1}, pluck="name"
		)
		fields.append("purchase_invoice_item")

	items = frappe.get_all(doctype + " Item", filters={"parent": ("in", parents)}, fields=fields)
	reference_by_row = {item.name: item.get(reference_fieldname) for item in items}
	for item in items:
		item[reference_fieldname] = reference_by_row[item.name] or reference_by_row.get(
			item.get("purchase_invoice_item")
		)

	return items


def set_purchase_references(doc):
	# add internal PO or PR links if any

	if doc.is_internal_transfer():
		if doc.doctype == "Purchase Receipt":
			so_item_map = get_delivery_note_details(doc.inter_company_invoice_reference)

			if so_item_map:
				pd_item_map, parent_child_map, warehouse_map = get_pd_details(
					"Purchase Order Item", so_item_map, "sales_order_item"
				)

				update_pr_items(doc, so_item_map, pd_item_map, parent_child_map, warehouse_map)

		elif doc.doctype == "Purchase Invoice":
			dn_item_map, so_item_map = get_sales_invoice_details(doc.inter_company_invoice_reference)
			# First check for Purchase receipt
			if list(dn_item_map.values()):
				pd_item_map, parent_child_map, warehouse_map = get_pd_details(
					"Purchase Receipt Item", dn_item_map, "delivery_note_item"
				)

				update_pi_items(
					doc,
					"pr_detail",
					"purchase_receipt",
					dn_item_map,
					pd_item_map,
					parent_child_map,
					warehouse_map,
				)


def update_pi_items(
	doc,
	detail_field,
	parent_field,
	sales_item_map,
	purchase_item_map,
	parent_child_map,
	warehouse_map,
):
	for item in doc.get("items"):
		item.set(detail_field, purchase_item_map.get(sales_item_map.get(item.sales_invoice_item)))
		item.set(parent_field, parent_child_map.get(sales_item_map.get(item.sales_invoice_item)))
		if doc.update_stock:
			item.warehouse = warehouse_map.get(sales_item_map.get(item.sales_invoice_item))
			if not item.warehouse and item.get("purchase_order") and item.get("purchase_order_item"):
				item.warehouse = frappe.db.get_value(
					"Purchase Order Item", item.purchase_order_item, "warehouse"
				)


def update_pr_items(doc, sales_item_map, purchase_item_map, parent_child_map, warehouse_map):
	for item in doc.get("items"):
		item.warehouse = warehouse_map.get(sales_item_map.get(item.delivery_note_item))
		if not item.warehouse and item.get("purchase_order") and item.get("purchase_order_item"):
			item.warehouse = frappe.db.get_value("Purchase Order Item", item.purchase_order_item, "warehouse")


def get_delivery_note_details(internal_reference):
	si_item_details = frappe.get_all(
		"Delivery Note Item", fields=["name", "so_detail"], filters={"parent": internal_reference}
	)

	return {d.name: d.so_detail for d in si_item_details if d.so_detail}


def get_sales_invoice_details(internal_reference):
	dn_item_map = {}
	so_item_map = {}

	si_item_details = frappe.get_all(
		"Sales Invoice Item",
		fields=["name", "so_detail", "dn_detail"],
		filters={"parent": internal_reference},
	)

	for d in si_item_details:
		if d.dn_detail:
			dn_item_map.setdefault(d.name, d.dn_detail)
		if d.so_detail:
			so_item_map.setdefault(d.name, d.so_detail)

	return dn_item_map, so_item_map


def get_pd_details(doctype, sd_detail_map, sd_detail_field):
	pd_item_map = {}
	accepted_warehouse_map = {}
	parent_child_map = {}

	pd_item_details = frappe.get_all(
		doctype,
		fields=[sd_detail_field, "name", "warehouse", "parent"],
		filters={sd_detail_field: ("in", list(sd_detail_map.values()))},
	)

	for d in pd_item_details:
		pd_item_map.setdefault(d.get(sd_detail_field), d.name)
		parent_child_map.setdefault(d.get(sd_detail_field), d.parent)
		accepted_warehouse_map.setdefault(d.get(sd_detail_field), d.warehouse)

	return pd_item_map, parent_child_map, accepted_warehouse_map


def update_taxes(
	doc,
	party=None,
	party_type=None,
	company=None,
	doctype=None,
	party_address=None,
	company_address=None,
	shipping_address_name=None,
	master_doctype=None,
):
	# Update Party Details
	party_details = get_party_details(
		party=party,
		party_type=party_type,
		company=company,
		doctype=doctype,
		party_address=party_address,
		company_address=company_address,
		shipping_address=shipping_address_name,
	)

	# Update taxes and charges if any
	doc.taxes_and_charges = party_details.get("taxes_and_charges")
	doc.set("taxes", party_details.get("taxes"))


def update_address(doc, address_field, address_display_field, address_name):
	doc.set(address_field, address_name)
	fetch_values = get_fetch_values(doc.doctype, address_field, address_name)

	for key, value in fetch_values.items():
		doc.set(key, value)

	doc.set(address_display_field, get_address_display(doc.get(address_field)))


def check_if_return_invoice_linked_with_payment_entry(self):
	# If a Return invoice is linked with payment entry along with other invoices,
	# the cancellation of the Return causes allocated amount to be greater than paid

	if not frappe.get_single_value("Accounts Settings", "unlink_payment_on_cancellation_of_invoice"):
		return

	payment_entries = []
	if self.is_return and self.return_against:
		invoice = self.return_against
	else:
		invoice = self.name

	payment_entries = frappe.db.sql_list(
		"""
		SELECT
			t1.name
		FROM
			`tabPayment Entry` t1, `tabPayment Entry Reference` t2
		WHERE
			t1.name = t2.parent
			and t1.docstatus = 1
			and t2.reference_name = %s
			and t2.allocated_amount < 0
		""",
		invoice,
	)

	links_to_pe = []
	if payment_entries:
		for payment in payment_entries:
			payment_entry = frappe.get_doc("Payment Entry", payment)
			if len(payment_entry.references) > 1:
				links_to_pe.append(payment_entry.name)
		if links_to_pe:
			payment_entries_link = [
				get_link_to_form("Payment Entry", name, label=name) for name in links_to_pe
			]
			message = _("Please cancel and amend the Payment Entry")
			message += " " + ", ".join(payment_entries_link) + " "
			message += _("to unallocate the amount of this Return Invoice before cancelling it.")
			frappe.throw(message)

