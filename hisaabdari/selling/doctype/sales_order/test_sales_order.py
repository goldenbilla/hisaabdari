# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import json

import frappe
import frappe.permissions
from frappe.core.doctype.user_permission.test_user_permission import create_user
from frappe.tests import change_settings
from frappe.utils import add_days, flt, nowdate, today

from hisaabdari.controllers.accounts_controller import InvalidQtyError, get_due_date, update_child_qty_rate
from hisaabdari.selling.doctype.sales_order.sales_order import (
	get_potentially_billable_sales_orders,
	has_potentially_billable_items,
	make_delivery_note,
	make_purchase_order,
	make_sales_invoice,
)
from hisaabdari.stock.doctype.item.test_item import make_item
from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from hisaabdari.stock.utils import InvalidWarehouseCompany
from hisaabdari.tests.permission_test_utils import make_fenced_user
from hisaabdari.tests.utils import ERPNextTestSuite


class TestSalesOrder(ERPNextTestSuite):
	def test_maximum_discount_for_percentage_amount_and_rate(self):
		item = make_item(properties={"is_stock_item": 0, "max_discount": 10})
		item_price = frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item.name,
				"price_list": "Standard Selling",
				"price_list_rate": 100,
			}
		).insert()
		user = make_fenced_user("max-discount@example.com", ["Sales User"])

		with self.set_user(user):
			for values in (
				{"discount_percentage": 50},
				{"discount_amount": 50},
				{"rate": 50},
				{"margin_type": "Percentage", "margin_rate_or_amount": 25, "discount_amount": 25},
			):
				with self.subTest(values=values):
					order = make_sales_order(
						item_list=[{"item_code": item.name, "qty": 1, **values}],
						selling_price_list="Standard Selling",
						do_not_save=True,
					)
					with self.assertRaisesRegex(frappe.ValidationError, "Maximum discount for Item"):
						order.insert().submit()

			for values, expected_rate in (
				({"discount_percentage": 10}, 90),
				({"discount_amount": 10}, 90),
				({"rate": 90}, 90),
				({"margin_type": "Percentage", "margin_rate_or_amount": 25, "discount_amount": 12.5}, 112.5),
			):
				with self.subTest(values=values):
					order = make_sales_order(
						item_list=[{"item_code": item.name, "qty": 1, **values}],
						selling_price_list="Standard Selling",
					)
					self.assertEqual(order.docstatus, 1)
					self.assertEqual(order.items[0].price_list_rate, 100)
					self.assertEqual(order.items[0].rate, expected_rate)

		item_price.price_list_rate = 0.06
		item_price.save()
		with self.set_user(user):
			order = make_sales_order(
				item_list=[{"item_code": item.name, "qty": 1, "discount_percentage": 10}],
				selling_price_list="Standard Selling",
			)
			self.assertEqual(order.items[0].discount_amount, 0.01)
			self.assertEqual(order.items[0].rate, 0.05)

		for price_list_rate, rate in ((0, 50), (-100, -100)):
			item_price.price_list_rate = price_list_rate
			item_price.save()
			with (
				self.subTest(price_list_rate=price_list_rate),
				self.change_settings("Selling Settings", {"allow_negative_rates_for_items": 1}),
				self.set_user(user),
			):
				order = make_sales_order(
					item_list=[{"item_code": item.name, "qty": 1, "rate": rate}],
					selling_price_list="Standard Selling",
				)
				self.assertEqual(order.items[0].rate, rate)
				self.assertEqual(order.items[0].discount_amount, 0)

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{
			"auto_insert_price_list_rate_if_missing": 1,
			"update_existing_price_list_rate": 1,
			"update_price_list_based_on": "Rate",
		},
	)
	def test_sales_order_expired_item_price(self):
		price_list = "_Test Price List"

		item_1 = make_item("_Test Expired Item 1", {"is_stock_item": 1})

		frappe.db.delete("Item Price", {"item_code": item_1.item_code})

		item_price = frappe.new_doc("Item Price")
		item_price.item_code = item_1.item_code
		item_price.price_list = price_list
		item_price.price_list_rate = 100
		item_price.valid_from = add_days(today(), -10)
		item_price.valid_upto = add_days(today(), -5)
		item_price.save()

		so = make_sales_order(
			item_code=item_1.item_code, qty=1, rate=1000, selling_price_list=price_list, do_not_save=True
		)
		so.save()
		so.reload()

		self.assertEqual(frappe.db.get_value("Item Price", item_price.name, "price_list_rate"), 100)
		self.assertEqual(
			frappe.db.count("Item Price", {"item_code": item_1.item_code, "price_list": price_list}),
			2,
		)
		all_item_prices = frappe.get_all(
			"Item Price", filters={"item_code": item_1.item_code}, order_by="valid_from desc"
		)
		self.assertEqual(frappe.db.get_value("Item Price", all_item_prices[0].name, "price_list_rate"), 1000)

	def test_sales_order_skip_delivery_note(self):
		so = make_sales_order(do_not_submit=True)
		so.order_type = "Maintenance"
		so.skip_delivery_note = 1
		so.append(
			"items",
			{
				"item_code": "_Test Item 2",
				"qty": 2,
				"rate": 100,
			},
		)
		so.save()
		so.submit()

		so.reload()
		si = make_sales_invoice(so.name)
		si.insert()
		si.submit()
		so.reload()
		self.assertEqual(so.status, "Completed")

	@ERPNextTestSuite.change_settings(
		"Selling Settings", {"allow_multiple_items": 1, "allow_negative_rates_for_items": 1}
	)
	def test_sales_order_with_negative_rate(self):
		"""
		Test if negative rate is allowed in Sales Order via doc submission and update items
		"""
		so = make_sales_order(qty=1, rate=100, do_not_save=True)
		so.append("items", {"item_code": "_Test Item", "qty": 1, "rate": -10})
		so.save()
		so.submit()

		first_item = so.get("items")[0]
		second_item = so.get("items")[1]
		trans_item = json.dumps(
			[
				{
					"item_code": first_item.item_code,
					"rate": first_item.rate,
					"qty": first_item.qty,
					"docname": first_item.name,
				},
				{
					"item_code": second_item.item_code,
					"rate": -20,
					"qty": second_item.qty,
					"docname": second_item.name,
				},
			]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_negative_rates_for_items": 0})
	def test_sales_order_negative_grand_total_blocked_without_setting(self):
		so = make_sales_order(qty=1, rate=100, do_not_save=True)
		so.append("items", {"item_code": "_Test Item 2", "qty": 1, "rate": -150})
		self.assertRaises(frappe.ValidationError, so.save)

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_negative_rates_for_items": 1})
	def test_sales_order_negative_grand_total_allowed_with_setting(self):
		"""Use a negative rate to represent a credit while order quantities remain positive."""
		so = make_sales_order(qty=1, rate=100, do_not_save=True)
		so.append("items", {"item_code": "_Test Item 2", "qty": 1, "rate": -150})
		so.save()
		so.submit()
		self.assertEqual(so.docstatus, 1)
		self.assertTrue(so.base_grand_total < 0)

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_negative_rates_for_items": 0})
	def test_sales_order_negative_rate_error_links_to_selling_settings(self):
		so = make_sales_order(qty=1, rate=100, do_not_save=True)
		so.append("items", {"item_code": "_Test Item 2", "qty": 1, "rate": -10})
		so.save()

		with self.assertRaises(frappe.ValidationError) as error:
			so.submit()

		self.assertIn("selling-settings", str(error.exception))

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_negative_rates_for_items": 1})
	def test_sales_order_negative_rate_setting_does_not_allow_negative_quantity(self):
		so = make_sales_order(qty=-1, rate=100, do_not_save=True)
		self.assertRaises(frappe.NonNegativeError, so.save)

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_multiple_items": 1})
	def test_sales_order_qty(self):
		so = make_sales_order(qty=1, do_not_save=True)

		# NonNegativeError with qty=-1
		so.append(
			"items",
			{
				"item_code": "_Test Item",
				"qty": -1,
				"rate": 10,
			},
		)
		self.assertRaises(frappe.NonNegativeError, so.save)

		# InvalidQtyError with qty=0
		so.items[1].qty = 0
		self.assertRaises(InvalidQtyError, so.save)

		# No error with qty=1
		so.items[1].qty = 1
		so.save()
		self.assertEqual(so.items[0].qty, 1)

	def test_sales_order_zero_qty(self):
		po = make_sales_order(qty=0, do_not_save=True)

		with change_settings("Selling Settings", {"allow_zero_qty_in_sales_order": 1}):
			po.save()
			self.assertEqual(po.items[0].qty, 0)

	def test_make_delivery_note(self):
		so = make_sales_order(do_not_submit=True)

		self.assertRaises(frappe.ValidationError, make_delivery_note, so.name)

		so.submit()
		dn = make_delivery_note(so.name)

		self.assertEqual(dn.doctype, "Delivery Note")
		self.assertEqual(len(dn.get("items")), len(so.get("items")))

	def test_make_sales_invoice(self):
		so = make_sales_order(do_not_submit=True)

		self.assertRaises(frappe.ValidationError, make_sales_invoice, so.name)

		so.submit()
		si = make_sales_invoice(so.name)

		self.assertEqual(len(si.get("items")), len(so.get("items")))
		self.assertEqual(len(si.get("items")), 1)

		si.insert()
		si.submit()

		si1 = make_sales_invoice(so.name)
		self.assertEqual(len(si1.get("items")), 0)

	def test_billing_within_rounding_of_full_completes_order(self):
		make_stock_entry(item_code="_Test Item", target="_Test Warehouse - _TC", qty=1, rate=100)
		so = make_sales_order(qty=1, rate=1000000)

		# 999999.99 / 1000000 rounds to 99.999999%, which already counts as fully billed
		si = make_sales_invoice(so.name)
		si.items[0].rate = 999999.99
		si.insert()
		si.submit()

		so.reload()
		self.assertEqual(so.per_billed, 100)
		self.assertEqual(so.billing_status, "Fully Billed")
		self.assertEqual(so.status, "To Deliver")

		make_delivery_note(so.name).submit()

		so.reload()
		self.assertEqual(so.status, "Completed")

	def test_make_sales_invoice_for_pending_qty_with_item_billing_allowance(self):
		item = make_item(
			"_Test Over Billed Pending Qty Item",
			{"is_stock_item": 1, "over_billing_allowance": 0},
		).name
		so = make_sales_order(item_code=item, qty=390, rate=100)

		for _ in range(2):
			si = make_sales_invoice(so.name)
			si.get("items")[0].qty = 120
			si.get("items")[0].rate = 162.50
			si.insert()
			si.submit()

		so.load_from_db()
		self.assertEqual(flt(so.per_billed), 100)
		self.assertEqual(so.get("items")[0].billed_amt, so.get("items")[0].amount)

		filters = {"docstatus": 1, "company": so.company, "customer": so.customer}

		def is_offered(txt=""):
			rows = get_potentially_billable_sales_orders("Sales Order", txt, "name", 0, 50, filters)
			return so.name in [row.name for row in rows]

		with change_settings("Accounts Settings", {"over_billing_allowance": 100}):
			self.assertTrue(has_potentially_billable_items(so.name))
			self.assertTrue(is_offered())
			self.assertEqual(make_sales_invoice(so.name).get("items")[0].qty, 150)

		with change_settings("Accounts Settings", {"over_billing_allowance": 0}):
			self.assertFalse(has_potentially_billable_items(so.name))
			self.assertEqual(len(make_sales_invoice(so.name).get("items")), 0)

			frappe.db.set_value("Item", item, "over_billing_allowance", 100)

			so.run_method("onload")
			self.assertTrue(so.get_onload("has_potentially_billable_items"))
			self.assertTrue(is_offered(so.customer))

			si = make_sales_invoice(so.name)
			self.assertEqual(len(si.get("items")), 1)
			self.assertEqual(si.get("items")[0].qty, 150)

	def test_make_sales_invoice_skips_fully_invoiced_free_item(self):
		free_item = make_item("_Test Free Item", {"is_stock_item": 1}).name
		so = make_sales_order(qty=10, rate=100, do_not_submit=True)
		so.append("items", {"item_code": free_item, "qty": 5, "rate": 0, "warehouse": so.items[0].warehouse})
		so.submit()

		si = make_sales_invoice(so.name)
		self.assertEqual([row.qty for row in si.items], [10, 5])
		si.insert()
		si.submit()

		self.assertEqual(len(make_sales_invoice(so.name).items), 0)

	def test_fully_billed_order_is_not_offered_within_billing_allowance(self):
		item = make_item(
			"_Test Fully Billed Allowance Item",
			{"is_stock_item": 1, "over_billing_allowance": 0},
		).name
		so = make_sales_order(item_code=item, qty=10, rate=100)

		si = make_sales_invoice(so.name)
		si.insert()
		si.submit()

		so.load_from_db()
		self.assertEqual(flt(so.per_billed), 100)

		filters = {"docstatus": 1, "company": so.company, "customer": so.customer}

		with change_settings("Accounts Settings", {"over_billing_allowance": 100}):
			self.assertFalse(has_potentially_billable_items(so.name))

			rows = get_potentially_billable_sales_orders("Sales Order", "", "name", 0, 50, filters)
			self.assertNotIn(so.name, [row.name for row in rows])

			self.assertEqual(len(make_sales_invoice(so.name).get("items")), 0)

	def test_full_qty_billed_below_amount_is_offered_with_zero_qty(self):
		so = make_sales_order(qty=1, rate=1000)

		si = make_sales_invoice(so.name)
		si.get("items")[0].rate = 400
		si.insert()
		si.submit()

		filters = {"docstatus": 1, "company": so.company, "customer": so.customer}
		rows = get_potentially_billable_sales_orders("Sales Order", "", "name", 0, 50, filters)
		self.assertIn(so.name, [row.name for row in rows])
		self.assertTrue(has_potentially_billable_items(so.name))

		si = make_sales_invoice(so.name)
		self.assertEqual([row.qty for row in si.get("items")], [0])
		self.assertEqual(len(make_sales_invoice(so.name, target_doc=si).get("items")), 1)

		si.get("items")[0].qty = 1
		si.get("items")[0].rate = 600
		si.insert()
		si.submit()

		so.load_from_db()
		self.assertEqual(flt(so.per_billed), 100)
		self.assertFalse(has_potentially_billable_items(so.name))

	def test_order_with_sub_precision_pending_qty_is_not_offered(self):
		item = make_item("_Test Sub Precision Qty Item", {"is_stock_item": 1}).name
		so = make_sales_order(item_code=item, qty=10, rate=100)

		si = make_sales_invoice(so.name)
		si.insert()
		si.submit()

		qty_precision = frappe.get_precision("Sales Order Item", "qty")
		billed_qty = 10 - 10 ** -(qty_precision + 1)
		frappe.db.set_value(
			"Sales Invoice Item", si.get("items")[0].name, "qty", billed_qty, update_modified=False
		)

		with change_settings("Accounts Settings", {"over_billing_allowance": 100}):
			self.assertFalse(has_potentially_billable_items(so.name))
			self.assertEqual(len(make_sales_invoice(so.name).get("items")), 0)

	def test_make_sales_invoice_after_return_and_redelivery(self):
		from hisaabdari.stock.doctype.delivery_note.delivery_note import make_sales_return

		so = make_sales_order(qty=10, rate=100)
		dn = create_dn_against_so(so.name, 10)

		dn_return = frappe.get_doc(make_sales_return(dn.name).as_dict())
		dn_return.insert()
		dn_return.submit()

		self.assertEqual(len(make_sales_invoice(so.name).get("items")), 0)

		create_dn_against_so(so.name, 10)

		so.load_from_db()
		item = so.get("items")[0]
		self.assertEqual(item.delivered_qty, 10)
		self.assertEqual(item.returned_qty, 10)

		si = make_sales_invoice(so.name)
		self.assertEqual(si.get("items")[0].qty, 10)

	def test_make_sales_invoice_bills_ordered_qty_for_partial_delivery(self):
		so = make_sales_order(qty=10, rate=100)
		create_dn_against_so(so.name, 4)

		si = make_sales_invoice(so.name)
		self.assertEqual(si.get("items")[0].qty, 10)

	def test_make_sales_invoice_after_partial_billing_return_and_redelivery(self):
		from hisaabdari.stock.doctype.delivery_note.delivery_note import make_sales_return

		so = make_sales_order(qty=10, rate=100)
		dn = create_dn_against_so(so.name, 10)

		si = make_sales_invoice(so.name)
		si.get("items")[0].qty = 4
		si.insert()
		si.submit()

		dn_return = frappe.get_doc(make_sales_return(dn.name).as_dict())
		dn_return.insert()
		dn_return.submit()
		create_dn_against_so(so.name, 5)

		so.load_from_db()
		item = so.get("items")[0]
		self.assertEqual(item.delivered_qty, 5)
		self.assertEqual(item.returned_qty, 10)
		self.assertEqual(item.billed_amt, 400)

		pending_invoice = make_sales_invoice(so.name)
		self.assertEqual(pending_invoice.get("items")[0].qty, 1)
		pending_invoice.insert()
		pending_invoice.submit()

		so.load_from_db()
		self.assertEqual(so.get("items")[0].billed_amt, 500)

	def test_order_neutral_credit_note_stays_out_of_later_billing(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		so = make_sales_order(qty=10, rate=100)
		si = make_sales_invoice(so.name)
		si.items[0].qty = 6
		si.insert()
		si.submit()

		credit_note = make_sales_return(si.name)
		credit_note.items[0].qty = -2
		credit_note.update_billed_amount_in_sales_order = 0
		credit_note.submit()

		si = make_sales_invoice(so.name)
		si.items[0].qty = 4
		si.insert()
		si.submit()

		so.reload()
		self.assertEqual(so.items[0].billed_amt, 1000)
		self.assertEqual(so.per_billed, 100)

	def test_make_sales_invoice_after_update_stock_credit_note(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		so = make_sales_order(qty=5, rate=100)
		si = make_sales_invoice(so.name)
		si.update_stock = 1
		si.insert()
		si.submit()

		credit_note = make_sales_return(si.name)
		credit_note.update_billed_amount_in_sales_order = 1
		credit_note.get("items")[0].qty = -2
		credit_note.insert()
		credit_note.submit()

		self.assertTrue(has_potentially_billable_items(so.name))
		pending_invoice = make_sales_invoice(so.name)
		self.assertEqual(pending_invoice.get("items")[0].qty, 2)

		pending_invoice.update_stock = 1
		pending_invoice.insert()
		pending_invoice.submit()

		self.assertFalse(has_potentially_billable_items(so.name))
		self.assertEqual(len(make_sales_invoice(so.name).get("items")), 0)

	def test_returned_qty_after_return_delivery_note_and_update_stock_credit_note(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return as make_credit_note
		from hisaabdari.stock.doctype.delivery_note.delivery_note import make_sales_return

		for credit_note_first in (False, True):
			with self.subTest(credit_note_first=credit_note_first):
				so = make_sales_order(qty=5, rate=100)
				dn = create_dn_against_so(so.name, 2)
				si = make_sales_invoice(so.name)
				si.update_stock = 1
				si.get("items")[0].qty = 3
				si.insert()
				si.submit()

				dn_return = frappe.get_doc(make_sales_return(dn.name).as_dict())
				credit_note = make_credit_note(si.name)
				credit_note.update_billed_amount_in_sales_order = 1
				credit_note.get("items")[0].qty = -1

				for return_doc in [credit_note, dn_return] if credit_note_first else [dn_return, credit_note]:
					return_doc.insert()
					return_doc.submit()

				so.load_from_db()
				self.assertEqual(so.get("items")[0].returned_qty, 3)
				self.assertEqual(make_sales_invoice(so.name).get("items")[0].qty, 1)

	def test_delivery_progress_after_returns_in_stock_uom(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return as make_credit_note
		from hisaabdari.stock.doctype.delivery_note.delivery_note import make_sales_return

		item = make_item(uoms=[{"uom": "Box", "conversion_factor": 12}])
		make_stock_entry(item_code=item.name, target="_Test Warehouse - _TC", qty=24, rate=10)
		so = make_sales_order(item_code=item.name, qty=2, uom="Box", rate=120)

		dn = make_delivery_note(so.name)
		dn.items[0].qty = 1
		dn.submit()
		dn_return = make_sales_return(dn.name)
		dn_return.items[0].update({"uom": item.stock_uom, "conversion_factor": 1, "qty": -2})
		dn_return.submit()

		si = make_sales_invoice(so.name)
		si.update_stock = 1
		si.items[0].qty = 1
		si.submit()
		credit_note = make_credit_note(si.name)
		credit_note.items[0].update({"uom": item.stock_uom, "conversion_factor": 1, "qty": -4})
		credit_note.submit()

		so.reload()
		self.assertEqual(so.items[0].delivered_qty, 1.5)
		self.assertEqual(so.items[0].returned_qty, 0.5)

	def test_make_sales_invoice_after_credit_note_in_stock_uom(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		item = make_item(uoms=[{"uom": "Box", "conversion_factor": 12}])
		make_stock_entry(item_code=item.name, target="_Test Warehouse - _TC", qty=24, rate=10)
		so = make_sales_order(item_code=item.name, qty=2, uom="Box", rate=120)

		si = make_sales_invoice(so.name)
		si.update_stock = 1
		si.submit()
		credit_note = make_sales_return(si.name)
		credit_note.update_billed_amount_in_sales_order = 1
		credit_note.items[0].update({"uom": item.stock_uom, "conversion_factor": 1, "qty": -12, "rate": 10})
		credit_note.submit()

		self.assertTrue(has_potentially_billable_items(so.name))
		self.assertEqual(make_sales_invoice(so.name).items[0].qty, 1)

	def test_make_sales_invoice_after_partial_billing_multiple_items(self):
		so = make_sales_order(
			item_list=[
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse - _TC",
					"qty": 10,
					"rate": 100,
				},
				{
					"item_code": "_Test FG Item",
					"warehouse": "_Test Warehouse - _TC",
					"qty": 10,
					"rate": 100,
				},
			]
		)

		si = make_sales_invoice(so.name)
		si.get("items")[0].qty = 4
		si.get("items")[1].qty = 6
		si.insert()
		si.submit()

		pending_invoice = make_sales_invoice(so.name)
		self.assertEqual(
			{item.so_detail: item.qty for item in pending_invoice.get("items")},
			{so.get("items")[0].name: 6, so.get("items")[1].name: 4},
		)

	def test_so_billed_amount_against_return_entry(self):
		from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		so = make_sales_order(do_not_submit=True)
		so.submit()

		si = make_sales_invoice(so.name)
		si.insert()
		si.submit()

		si1 = make_sales_return(si.name)
		si1.update_billed_amount_in_sales_order = 1
		si1.submit()
		so.load_from_db()
		self.assertEqual(so.per_billed, 0)

	@ERPNextTestSuite.change_settings(
		"Accounts Settings", {"automatically_fetch_payment_terms": 1}
	)  # Enable auto fetch
	def test_make_sales_invoice_with_terms(self):
		so = make_sales_order(do_not_submit=True)

		self.assertRaises(frappe.ValidationError, make_sales_invoice, so.name)

		so.update({"payment_terms_template": "_Test Payment Term Template"})

		so.save()
		so.submit()
		si = make_sales_invoice(so.name)

		self.assertEqual(len(si.get("items")), len(so.get("items")))
		self.assertEqual(len(si.get("items")), 1)

		si.insert()
		si.set("taxes", [])
		si.save()

		self.assertEqual(si.payment_schedule[0].payment_amount, 500.0)
		self.assertEqual(si.payment_schedule[0].due_date, so.transaction_date)
		self.assertEqual(si.payment_schedule[1].payment_amount, 500.0)
		self.assertEqual(si.payment_schedule[1].due_date, add_days(so.transaction_date, 30))

		si.submit()

		si1 = make_sales_invoice(so.name)
		self.assertEqual(len(si1.get("items")), 0)

	@ERPNextTestSuite.change_settings(
		"Accounts Settings", {"automatically_fetch_payment_terms": 1}
	)  # Enable auto fetch
	def test_auto_fetch_terms_enable(self):
		so = make_sales_order(do_not_submit=True)

		so.payment_terms_template = "_Test Payment Term Template"
		so.save()
		so.submit()

		si = make_sales_invoice(so.name)
		# Check if payment terms are copied from sales order to sales invoice
		self.assertTrue(si.payment_terms_template)
		si.insert()
		si.submit()

	@ERPNextTestSuite.change_settings(
		"Accounts Settings", {"automatically_fetch_payment_terms": 0}
	)  # Disable auto fetch
	def test_auto_fetch_terms_disable(self):
		so = make_sales_order(do_not_submit=True)

		so.payment_terms_template = "_Test Payment Term Template"
		so.save()
		so.submit()

		si = make_sales_invoice(so.name)
		# Check if payment terms are not copied from sales order to sales invoice
		self.assertFalse(si.payment_terms_template)
		si.insert()
		si.submit()

	def test_update_qty(self):
		so = make_sales_order()

		create_dn_against_so(so.name, 6)

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 6)

		# Check delivered_qty after make_sales_invoice without update_stock checked
		si1 = make_sales_invoice(so.name)
		si1.get("items")[0].qty = 6
		si1.insert()
		si1.submit()

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 6)

		# Check delivered_qty after make_sales_invoice with update_stock checked
		si2 = make_sales_invoice(so.name)
		si2.set("update_stock", 1)
		si2.get("items")[0].qty = 3
		si2.insert()
		si2.submit()

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 9)

	def test_return_against_sales_order(self):
		so = make_sales_order()

		dn = create_dn_against_so(so.name, 6)

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 6)

		# Check delivered_qty after make_sales_invoice with update_stock checked
		si2 = make_sales_invoice(so.name)
		si2.set("update_stock", 1)
		si2.get("items")[0].qty = 3
		si2.insert()
		si2.submit()

		so.load_from_db()

		self.assertEqual(so.get("items")[0].delivered_qty, 9)

		# Make return deliver note, sales invoice and check quantity
		from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
		from hisaabdari.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		dn1 = create_delivery_note(is_return=1, return_against=dn.name, qty=-3, do_not_submit=True)
		dn1.items[0].against_sales_order = so.name
		dn1.items[0].so_detail = so.items[0].name
		dn1.submit()

		si1 = create_sales_invoice(
			is_return=1, return_against=si2.name, qty=-1, update_stock=1, do_not_submit=True
		)
		si1.items[0].sales_order = so.name
		si1.items[0].so_detail = so.items[0].name
		si1.submit()

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 5)

	def test_reserved_qty_for_partial_delivery(self):
		make_stock_entry(target="_Test Warehouse - _TC", qty=10, rate=100)
		existing_reserved_qty = get_reserved_qty()

		so = make_sales_order()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 10)

		dn = create_dn_against_so(so.name)
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 5)

		# close so
		so.load_from_db()
		so.update_status("Closed")
		self.assertEqual(get_reserved_qty(), existing_reserved_qty)

		# unclose so
		so.load_from_db()
		so.update_status("Draft")
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 5)

		dn.cancel()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 10)

		# cancel
		so.load_from_db()
		so.cancel()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty)

	def test_reserved_qty_for_over_delivery(self):
		make_stock_entry(target="_Test Warehouse - _TC", qty=10, rate=100)
		# set over-delivery allowance
		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 50)

		existing_reserved_qty = get_reserved_qty()

		so = make_sales_order()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 10)

		dn = create_dn_against_so(so.name, 15)
		self.assertEqual(get_reserved_qty(), existing_reserved_qty)

		dn.cancel()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 10)

	def test_reserved_qty_for_over_delivery_via_sales_invoice(self):
		make_stock_entry(target="_Test Warehouse - _TC", qty=10, rate=100)

		# set over-delivery allowance
		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 50)
		frappe.db.set_value("Item", "_Test Item", "over_billing_allowance", 20)

		existing_reserved_qty = get_reserved_qty()

		so = make_sales_order()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 10)

		si = make_sales_invoice(so.name)
		si.update_stock = 1
		si.get("items")[0].qty = 12
		si.insert()
		si.submit()

		self.assertEqual(get_reserved_qty(), existing_reserved_qty)

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 12)
		self.assertEqual(so.per_delivered, 100)

		si.cancel()
		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 10)

		so.load_from_db()
		self.assertEqual(so.get("items")[0].delivered_qty, 0)
		self.assertEqual(so.per_delivered, 0)

	def test_sales_order_on_hold(self):
		so = make_sales_order()
		so.db_set("status", "On Hold")
		si = make_sales_invoice(so.name)
		self.assertRaises(frappe.ValidationError, create_dn_against_so, so.name)
		self.assertRaises(frappe.ValidationError, si.submit)

	def test_update_child_adding_new_item(self):
		so = make_sales_order(item_code="_Test Item", qty=4)
		create_dn_against_so(so.name, 4)
		make_sales_invoice(so.name)

		prev_total = so.get("base_total")
		prev_total_in_words = so.get("base_in_words")

		# get reserved qty before update items
		reserved_qty_for_second_item = get_reserved_qty("_Test Item 2")

		first_item_of_so = so.get("items")[0]
		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_so.item_code,
					"rate": first_item_of_so.rate,
					"qty": first_item_of_so.qty,
					"docname": first_item_of_so.name,
				},
				{"item_code": "_Test Item 2", "rate": 200, "qty": 7},
			]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

		so.reload()
		self.assertEqual(so.get("items")[-1].item_code, "_Test Item 2")
		self.assertEqual(so.get("items")[-1].rate, 200)
		self.assertEqual(so.get("items")[-1].qty, 7)
		self.assertEqual(so.get("items")[-1].amount, 1400)

		# reserved qty should increase after adding row
		self.assertEqual(get_reserved_qty("_Test Item 2"), reserved_qty_for_second_item + 7)

		self.assertEqual(so.status, "To Deliver and Bill")

		updated_total = so.get("base_total")
		updated_total_in_words = so.get("base_in_words")

		self.assertEqual(updated_total, prev_total + 1400)
		self.assertNotEqual(updated_total_in_words, prev_total_in_words)

	def test_update_child_adding_new_item_with_warehouse(self):
		so = make_sales_order(item_code="_Test Item", qty=4)

		first_item_of_so = so.get("items")[0]
		self.assertNotEqual(first_item_of_so.warehouse, "_Test Warehouse 2 - _TC")

		def get_trans_item(warehouse):
			return json.dumps(
				[
					{
						"item_code": first_item_of_so.item_code,
						"rate": first_item_of_so.rate,
						"qty": first_item_of_so.qty,
						"docname": first_item_of_so.name,
						"warehouse": warehouse,
					},
					{"item_code": "_Test Item 2", "rate": 200, "qty": 7, "warehouse": warehouse},
				]
			)

		self.assertRaises(
			InvalidWarehouseCompany,
			update_child_qty_rate,
			"Sales Order",
			get_trans_item("_Test Warehouse 2 - _TC1"),
			so.name,
		)

		self.assertRaisesRegex(
			frappe.ValidationError,
			"Group node warehouse",
			update_child_qty_rate,
			"Sales Order",
			get_trans_item("_Test Warehouse Group - _TC"),
			so.name,
		)

		if not frappe.db.exists("Warehouse", "_Test Disabled Warehouse - _TC"):
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "_Test Disabled Warehouse",
					"company": "_Test Company",
					"disabled": 1,
				}
			).insert()

		self.assertRaisesRegex(
			frappe.ValidationError,
			"Disabled Warehouse",
			update_child_qty_rate,
			"Sales Order",
			get_trans_item("_Test Disabled Warehouse - _TC"),
			so.name,
		)

		update_child_qty_rate("Sales Order", get_trans_item("_Test Warehouse 2 - _TC"), so.name)

		so.reload()
		# the new row picks up the warehouse selected in the dialog
		self.assertEqual(so.get("items")[-1].item_code, "_Test Item 2")
		self.assertEqual(so.get("items")[-1].warehouse, "_Test Warehouse 2 - _TC")
		# existing rows keep theirs, so their reserved qty stays in the same bin
		self.assertEqual(so.get("items")[0].warehouse, first_item_of_so.warehouse)

	def test_update_child_adding_new_item_without_any_default_warehouse(self):
		item_code = make_item("_Test Item Without Default Warehouse", {"is_stock_item": 1}).name
		so = make_sales_order(item_code="_Test Item", qty=4)
		existing_item = so.get("items")[0]

		# a company gets a default warehouse when its warehouses are created
		frappe.db.set_value("Company", so.company, "default_warehouse", None)

		def get_trans_items(warehouse=None):
			new_row = {"item_code": item_code, "rate": 200, "qty": 7}
			if warehouse:
				new_row["warehouse"] = warehouse

			return json.dumps(
				[
					{
						"item_code": existing_item.item_code,
						"rate": existing_item.rate,
						"qty": existing_item.qty,
						"docname": existing_item.name,
					},
					new_row,
				]
			)

		# no default in the Item Master, Item Group, Brand or Company
		self.assertRaisesRegex(
			frappe.ValidationError,
			"Cannot find a default warehouse",
			update_child_qty_rate,
			"Sales Order",
			get_trans_items(),
			so.name,
		)

		update_child_qty_rate("Sales Order", get_trans_items("_Test Warehouse - _TC"), so.name)

		so.reload()
		self.assertEqual(len(so.get("items")), 2)
		self.assertEqual(so.get("items")[0].warehouse, existing_item.warehouse)
		self.assertEqual(so.get("items")[-1].item_code, item_code)
		self.assertEqual(so.get("items")[-1].warehouse, "_Test Warehouse - _TC")

	def test_update_child_removing_item(self):
		so = make_sales_order(**{"item_list": [{"item_code": "_Test Item", "qty": 5, "rate": 1000}]})
		create_dn_against_so(so.name, 2)
		make_sales_invoice(so.name)

		# get reserved qty before update items
		reserved_qty_for_second_item = get_reserved_qty("_Test Item 2")

		# add an item so as to try removing items
		trans_item = json.dumps(
			[
				{"item_code": "_Test Item", "qty": 5, "rate": 1000, "docname": so.get("items")[0].name},
				{"item_code": "_Test Item 2", "qty": 2, "rate": 500},
			]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)
		so.reload()
		self.assertEqual(len(so.get("items")), 2)

		# reserved qty should increase after adding row
		self.assertEqual(get_reserved_qty("_Test Item 2"), reserved_qty_for_second_item + 2)

		# check if delivered items can be removed
		trans_item = json.dumps(
			[{"item_code": "_Test Item 2", "qty": 2, "rate": 500, "docname": so.get("items")[1].name}]
		)
		self.assertRaises(frappe.ValidationError, update_child_qty_rate, "Sales Order", trans_item, so.name)

		# remove last added item
		trans_item = json.dumps(
			[{"item_code": "_Test Item", "qty": 5, "rate": 1000, "docname": so.get("items")[0].name}]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

		so.reload()
		self.assertEqual(len(so.get("items")), 1)

		# reserved qty should decrease (back to initial) after deleting row
		self.assertEqual(get_reserved_qty("_Test Item 2"), reserved_qty_for_second_item)

		self.assertEqual(so.status, "To Deliver and Bill")

	def test_update_child(self):
		so = make_sales_order(item_code="_Test Item", qty=4)
		create_dn_against_so(so.name, 4)
		make_sales_invoice(so.name)

		existing_reserved_qty = get_reserved_qty()

		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": so.items[0].name}]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

		so.reload()
		self.assertEqual(so.get("items")[0].rate, 200)
		self.assertEqual(so.get("items")[0].qty, 7)
		self.assertEqual(so.get("items")[0].amount, 1400)
		self.assertEqual(so.status, "To Deliver and Bill")

		self.assertEqual(get_reserved_qty(), existing_reserved_qty + 3)

		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 200, "qty": 2, "docname": so.items[0].name}]
		)
		self.assertRaises(frappe.ValidationError, update_child_qty_rate, "Sales Order", trans_item, so.name)

	def test_update_child_qty_with_conversion_factor_after_delivery(self):
		item = make_item(uoms=[{"uom": "Box", "conversion_factor": 5}])
		sales_order = make_sales_order(item_code=item.item_code, qty=6, uom="Box")
		create_dn_against_so(sales_order.name, 2)

		row = sales_order.items[0]
		trans_items = json.dumps(
			[
				{
					"item_code": row.item_code,
					"rate": row.rate,
					"qty": 4,
					"uom": row.uom,
					"conversion_factor": 2,
					"docname": row.name,
				}
			]
		)

		self.assertRaisesRegex(
			frappe.ValidationError,
			"Cannot set quantity less than delivered quantity",
			update_child_qty_rate,
			"Sales Order",
			trans_items,
			sales_order.name,
		)

	def test_update_child_preserves_conversion_factor_precision(self):
		from hisaabdari.controllers.accounts_controller import update_child_item_uom_and_weight

		item = make_item(properties={"stock_uom": "Kg"}, uoms=[{"uom": "Box", "conversion_factor": 2}])
		sales_order = make_sales_order(item_code=item.item_code, qty=6, uom="Box")
		conversion_factor = 1.123456789123
		row = sales_order.items[0]

		update_child_item_uom_and_weight(row, {"conversion_factor": conversion_factor})

		self.assertEqual(row.conversion_factor, conversion_factor)

	def test_update_child_with_precision(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter
		from frappe.model.meta import get_field_precision

		precision = get_field_precision(frappe.get_meta("Sales Order Item").get_field("rate"))

		make_property_setter("Sales Order Item", "rate", "precision", 7, "Currency")
		so = make_sales_order(item_code="_Test Item", qty=4, rate=200.34664)

		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 200.34669, "qty": 4, "docname": so.items[0].name}]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

		so.reload()
		self.assertEqual(so.items[0].rate, 200.34669)
		make_property_setter("Sales Order Item", "rate", "precision", precision, "Currency")

	def test_sales_invoice_does_not_show_an_address_the_user_cannot_read(self):
		from hisaabdari.controllers.tests.test_accounts_controller import make_address
		from hisaabdari.selling.doctype.customer.test_customer import make_customer

		allowed, restricted = (make_address(address_title=title).name for title in ("Allowed", "Restricted"))
		test_user = create_user("test_so_address_perms@example.com", "Sales User", "Accounts User")
		frappe.permissions.add_user_permission("Address", allowed, test_user.name, applicable_for="Address")
		so = make_sales_order(customer=make_customer(frappe.generate_hash(length=10)))

		with self.set_user(test_user.name):
			self.assertTrue(make_sales_invoice(so.name).items)
			self.assertRaises(
				frappe.PermissionError,
				make_sales_invoice,
				so.name,
				target_doc=json.dumps({"doctype": "Sales Invoice", "shipping_address_name": restricted}),
			)

	def test_update_child_perm(self):
		so = make_sales_order(item_code="_Test Item", qty=4)

		test_user = create_user("test_so_child_perms@example.com", "Accounts User")
		with self.set_user(test_user.name):
			# update qty
			trans_item = json.dumps(
				[{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": so.items[0].name}]
			)
			self.assertRaises(
				frappe.ValidationError, update_child_qty_rate, "Sales Order", trans_item, so.name
			)

			# add new item
			trans_item = json.dumps([{"item_code": "_Test Item", "rate": 100, "qty": 2}])
			self.assertRaises(
				frappe.ValidationError, update_child_qty_rate, "Sales Order", trans_item, so.name
			)

	def test_make_sales_invoice_checks_item_permission_of_target_rows(self):
		so = make_sales_order(item_code="_Test Item", qty=1)
		user = create_user("test_so_target_item_perm@example.com", "Sales User", "Accounts User").name
		frappe.permissions.add_user_permission("Item", "_Test Item", user, applicable_for="Item")
		target = {"doctype": "Sales Invoice", "items": [{"item_code": "_Test Item 2", "qty": 1}]}

		with self.set_user(user):
			self.assertRaises(
				frappe.PermissionError, make_sales_invoice, so.name, target_doc=json.dumps(target)
			)

	def test_update_child_cannot_remove_item_linked_by_draft_purchase_order(self):
		so = make_sales_order(
			item_list=[
				{"item_code": "_Test Item", "qty": 5, "rate": 1000},
				{"item_code": "_Test Item 2", "qty": 2, "rate": 500},
			]
		)
		make_purchase_order(
			so.name,
			selected_items=[
				{"name": so.items[0].name, "item_code": "_Test Item", "supplier": "_Test Supplier"}
			],
		)

		kept_row = so.items[1]
		trans_item = json.dumps(
			[{"item_code": kept_row.item_code, "qty": 2, "rate": 500, "docname": kept_row.name}]
		)
		self.assertRaisesRegex(
			frappe.ValidationError,
			"already ordered on Purchase Order",
			update_child_qty_rate,
			"Sales Order",
			trans_item,
			so.name,
		)

	def test_update_child_removing_item_without_cancel_and_delete_perms(self):
		for workflow_name in frappe.get_all(
			"Workflow", filters={"document_type": "Sales Order", "is_active": 1}, pluck="name"
		):
			workflow = frappe.get_doc("Workflow", workflow_name)
			workflow.is_active = 0
			workflow.save()

		role = "_Test Sales Order Item Editor"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()

		frappe.permissions.add_permission("Sales Order", role, 0)
		for right, value in {
			"read": 1,
			"write": 1,
			"create": 1,
			"submit": 1,
			"cancel": 0,
			"delete": 0,
		}.items():
			frappe.permissions.update_permission_property("Sales Order", role, 0, right, value)
		frappe.clear_cache()

		so = make_sales_order(**{"item_list": [{"item_code": "_Test Item", "qty": 5, "rate": 1000}]})
		trans_item = json.dumps(
			[
				{"item_code": "_Test Item", "qty": 5, "rate": 1000, "docname": so.items[0].name},
				{"item_code": "_Test Item 2", "qty": 2, "rate": 500},
			]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)
		so.reload()
		self.assertEqual(len(so.items), 2)

		test_user = create_user("test_so_item_editor@example.com", role, "Accounts User", "Stock User")
		trans_item = json.dumps(
			[{"item_code": "_Test Item", "qty": 5, "rate": 1000, "docname": so.items[0].name}]
		)
		with self.set_user(test_user.name):
			update_child_qty_rate("Sales Order", trans_item, so.name)

		so.reload()
		self.assertEqual(len(so.items), 1)

	def test_update_child_qty_rate_with_workflow(self):
		from frappe.model.workflow import apply_workflow

		workflow = make_sales_order_workflow()
		so = make_sales_order(item_code="_Test Item", qty=1, rate=150, do_not_submit=1)
		apply_workflow(so, "Approve")

		user = "test@example.com"
		test_user = frappe.get_doc("User", user)
		test_user.add_roles("Sales User", "Test Junior Approver")
		with self.set_user(user):
			# user shouldn't be able to edit since grand_total will become > 200 if qty is doubled
			trans_item = json.dumps(
				[{"item_code": "_Test Item", "rate": 150, "qty": 2, "docname": so.items[0].name}]
			)
			self.assertRaises(
				frappe.ValidationError, update_child_qty_rate, "Sales Order", trans_item, so.name
			)

		user2 = "test2@example.com"
		test_user2 = frappe.get_doc("User", user2)
		test_user2.add_roles("Sales User", "Test Approver")

		with self.set_user(user2):
			# Test Approver is allowed to edit with grand_total > 200
			update_child_qty_rate("Sales Order", trans_item, so.name)
			so.reload()
			self.assertEqual(so.items[0].qty, 2)

		test_user.remove_roles("Sales User", "Test Junior Approver", "Test Approver")
		test_user2.remove_roles("Sales User", "Test Junior Approver", "Test Approver")
		workflow.is_active = 0
		workflow.save()

	def test_update_child_qty_rate_follows_allow_edit(self):
		from frappe.model.workflow import apply_workflow

		workflow = make_sales_order_edit_perm_workflow()
		so = make_sales_order(item_code="_Test Item", qty=1, rate=150, do_not_submit=1)
		apply_workflow(so, "Approve")

		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 150, "qty": 2, "docname": so.items[0].name}]
		)

		mover = "test@example.com"
		mover_user = frappe.get_doc("User", mover)
		mover_user.add_roles("Sales User", "Test Junior Approver")
		with self.set_user(mover):
			# transitioned the doc into Approved but is not the configured editor
			self.assertRaises(
				frappe.ValidationError, update_child_qty_rate, "Sales Order", trans_item, so.name
			)

		editor = "test2@example.com"
		editor_user = frappe.get_doc("User", editor)
		editor_user.add_roles("Sales User", "Test Approver")
		with self.set_user(editor):
			# Test Approver is the "Only Allow Edit For" role on Approved
			update_child_qty_rate("Sales Order", trans_item, so.name)
			so.reload()
			self.assertEqual(so.items[0].qty, 2)

		mover_user.remove_roles("Sales User", "Test Junior Approver", "Test Approver")
		editor_user.remove_roles("Sales User", "Test Junior Approver", "Test Approver")
		workflow.is_active = 0
		workflow.save()

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_multiple_items": 1})
	def test_update_child_with_tax_template(self):
		"""
		Test Action: Create a SO with one item having its tax account head already in the SO.
		Add the same item + new item with tax template via Update Items.
		Expected result: First Item's tax row is updated. New tax row is added for second Item.
		"""
		if not frappe.db.exists("Item", "Test Item with Tax"):
			make_item(
				"Test Item with Tax",
				{
					"is_stock_item": 1,
				},
			)

		if not frappe.db.exists("Item Tax Template", {"title": "Test Update Items Template"}):
			frappe.get_doc(
				{
					"doctype": "Item Tax Template",
					"title": "Test Update Items Template",
					"company": "_Test Company",
					"taxes": [
						{
							"tax_type": "_Test Account Service Tax - _TC",
							"tax_rate": 10,
						}
					],
				}
			).insert()

		new_item_with_tax = frappe.get_doc("Item", "Test Item with Tax")

		new_item_with_tax.append(
			"taxes", {"item_tax_template": "Test Update Items Template - _TC", "valid_from": nowdate()}
		)
		new_item_with_tax.save()

		tax_template = "_Test Account Excise Duty @ 10 - _TC"
		item = "_Test Item Home Desktop 100"
		if not frappe.db.exists("Item Tax", {"parent": item, "item_tax_template": tax_template}):
			item_doc = frappe.get_doc("Item", item)
			item_doc.append("taxes", {"item_tax_template": tax_template, "valid_from": nowdate()})
			item_doc.save()
		else:
			# update valid from
			frappe.db.sql(
				"""UPDATE `tabItem Tax` set valid_from = CURRENT_DATE
				where parent = %(item)s and item_tax_template = %(tax)s""",
				{"item": item, "tax": tax_template},
			)

		so = make_sales_order(item_code=item, qty=1, do_not_save=1)

		so.append(
			"taxes",
			{
				"account_head": "_Test Account Excise Duty - _TC",
				"charge_type": "On Net Total",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Excise Duty",
				"doctype": "Sales Taxes and Charges",
				"rate": 10,
			},
		)
		so.insert()
		so.submit()

		self.assertEqual(so.taxes[0].tax_amount, 10)
		self.assertEqual(so.taxes[0].total, 110)

		old_default_warehouse = frappe.db.get_value("Company", "_Test Company", "default_warehouse")
		frappe.db.set_value("Company", "_Test Company", "default_warehouse", "_Test Warehouse - _TC")

		items = json.dumps(
			[
				{"item_code": item, "rate": 100, "qty": 1, "docname": so.items[0].name},
				{
					"item_code": item,
					"rate": 200,
					"qty": 1,
				},  # added item whose tax account head already exists in PO
				{
					"item_code": new_item_with_tax.name,
					"rate": 100,
					"qty": 1,
				},  # added item whose tax account head  is missing in PO
			]
		)
		update_child_qty_rate("Sales Order", items, so.name)

		so.reload()
		self.assertEqual(so.taxes[0].tax_amount, 40)
		self.assertEqual(so.taxes[0].total, 440)
		self.assertEqual(so.taxes[1].account_head, "_Test Account Service Tax - _TC")
		self.assertEqual(so.taxes[1].tax_amount, 40)
		self.assertEqual(so.taxes[1].total, 480)

		# teardown
		frappe.db.sql(
			"""UPDATE `tabItem Tax` set valid_from = NULL
			where parent = %(item)s and item_tax_template = %(tax)s""",
			{"item": item, "tax": tax_template},
		)
		so.cancel()
		so.delete()
		new_item_with_tax.delete()
		frappe.get_doc("Item Tax Template", "Test Update Items Template - _TC").delete()
		frappe.db.set_value("Company", "_Test Company", "default_warehouse", old_default_warehouse)

	def test_warehouse_user(self):
		test_user = create_user("test_so_warehouse_user@example.com", "Sales User", "Stock User")

		test_user_2 = frappe.get_doc("User", "test2@example.com")
		test_user_2.add_roles("Sales User", "Stock User")
		test_user_2.remove_roles("Sales Manager")

		frappe.permissions.add_user_permission("Warehouse", "_Test Warehouse 1 - _TC", test_user.name)
		frappe.permissions.add_user_permission("Warehouse", "_Test Warehouse 2 - _TC1", test_user_2.name)
		frappe.permissions.add_user_permission("Company", "_Test Company 1", test_user_2.name)

		with self.set_user(test_user.name):
			so = make_sales_order(
				company="_Test Company 1",
				customer="_Test Customer 1",
				warehouse="_Test Warehouse 2 - _TC1",
				do_not_save=True,
			)
			so.conversion_rate = 0.02
			so.plc_conversion_rate = 0.02
			self.assertRaises(frappe.PermissionError, so.insert)

		with self.set_user(test_user_2.name):
			so.insert()

		frappe.permissions.remove_user_permission("Warehouse", "_Test Warehouse 1 - _TC", test_user.name)
		frappe.permissions.remove_user_permission("Warehouse", "_Test Warehouse 2 - _TC1", test_user_2.name)
		frappe.permissions.remove_user_permission("Company", "_Test Company 1", test_user_2.name)

	def test_block_delivery_note_against_cancelled_sales_order(self):
		so = make_sales_order()

		dn = make_delivery_note(so.name)
		dn.insert()

		so.cancel()

		dn.load_from_db()

		self.assertRaises(frappe.CancelledLinkError, dn.submit)

	def test_auto_insert_price(self):
		make_item("_Test Item for Auto Price List", {"is_stock_item": 0})
		make_item("_Test Item for Auto Price List with Discount Percentage", {"is_stock_item": 0})
		frappe.db.set_single_value(
			"Stock Settings",
			{
				"auto_insert_price_list_rate_if_missing": 1,
				"update_price_list_based_on": "Price List Rate",
			},
		)

		item_price = frappe.db.get_value(
			"Item Price", {"price_list": "_Test Price List", "item_code": "_Test Item for Auto Price List"}
		)
		if item_price:
			frappe.delete_doc("Item Price", item_price)

		make_sales_order(
			item_code="_Test Item for Auto Price List", selling_price_list="_Test Price List", rate=100
		)

		# ensure price gets inserted based on rate if price list rate is not defined by user
		self.assertEqual(
			frappe.db.get_value(
				"Item Price",
				{"price_list": "_Test Price List", "item_code": "_Test Item for Auto Price List"},
				"price_list_rate",
			),
			100,
		)

		# ensure price gets insterted based on user-defined *Price List Rate*
		# if update_price_list_based_on is set to Price List Rate
		make_sales_order(
			item_code="_Test Item for Auto Price List with Discount Percentage",
			selling_price_list="_Test Price List",
			price_list_rate=200,
			discount_percentage=20,
		)

		item_price = frappe.db.get_value(
			"Item Price",
			{
				"price_list": "_Test Price List",
				"item_code": "_Test Item for Auto Price List with Discount Percentage",
			},
			("name", "price_list_rate"),
			as_dict=True,
		)

		self.assertEqual(item_price.price_list_rate, 200)
		frappe.delete_doc("Item Price", item_price.name)

		frappe.db.set_single_value("Stock Settings", "update_price_list_based_on", "Rate")

		# ensure price gets insterted based on user-defined *Rate*
		# if update_price_list_based_on is set to Rate
		make_sales_order(
			item_code="_Test Item for Auto Price List with Discount Percentage",
			selling_price_list="_Test Price List",
			price_list_rate=200,
			discount_percentage=20,
		)

		item_price = frappe.db.get_value(
			"Item Price",
			{
				"price_list": "_Test Price List",
				"item_code": "_Test Item for Auto Price List with Discount Percentage",
			},
			("name", "price_list_rate"),
			as_dict=True,
		)

		self.assertEqual(item_price.price_list_rate, 160)
		frappe.delete_doc("Item Price", item_price.name)

		# do not update price list
		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)

		item_price = frappe.db.get_value(
			"Item Price", {"price_list": "_Test Price List", "item_code": "_Test Item for Auto Price List"}
		)
		if item_price:
			frappe.delete_doc("Item Price", item_price)

		make_sales_order(
			item_code="_Test Item for Auto Price List", selling_price_list="_Test Price List", rate=100
		)

		self.assertEqual(
			frappe.db.get_value(
				"Item Price",
				{"price_list": "_Test Price List", "item_code": "_Test Item for Auto Price List"},
				"price_list_rate",
			),
			None,
		)

		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 1)

	def test_update_existing_item_price(self):
		item_code = "_Test Item for Price List Updation"
		price_list = "_Test Price List"

		make_item(item_code, {"is_stock_item": 0})

		frappe.db.set_single_value(
			"Stock Settings",
			{
				"auto_insert_price_list_rate_if_missing": 1,
				"update_existing_price_list_rate": 1,
				"update_price_list_based_on": "Rate",
			},
		)

		# setup: price creation
		make_sales_order(item_code=item_code, selling_price_list=price_list, rate=100)

		# test price updation based on Rate
		make_sales_order(item_code=item_code, selling_price_list=price_list, rate=90)

		self.assertEqual(
			frappe.db.get_value(
				"Item Price",
				{"price_list": price_list, "item_code": item_code},
				"price_list_rate",
			),
			90,
		)

		frappe.db.set_single_value(
			"Stock Settings",
			{
				"update_price_list_based_on": "Price List Rate",
			},
		)

		# test price updation based on Price List Rate
		make_sales_order(
			item_code=item_code,
			selling_price_list=price_list,
			price_list_rate=200,
			discount_percentage=20,
		)

		self.assertEqual(
			frappe.db.get_value(
				"Item Price",
				{"price_list": price_list, "item_code": item_code},
				"price_list_rate",
			),
			200,
		)

		# reset `update_existing_price_list_rate` to 0
		frappe.db.set_single_value("Stock Settings", "update_existing_price_list_rate", 0)

	def test_drop_shipping(self):
		from hisaabdari.buying.doctype.purchase_order.purchase_order import update_status
		from hisaabdari.selling.doctype.sales_order.sales_order import update_status as so_update_status

		# make items
		po_item = make_item("_Test Item for Drop Shipping", {"is_stock_item": 1, "delivered_by_supplier": 1})
		dn_item = make_item("_Test Regular Item", {"is_stock_item": 1})

		so_items = [
			{
				"item_code": po_item.item_code,
				"warehouse": "",
				"qty": 2,
				"rate": 400,
				"delivered_by_supplier": 1,
				"supplier": "_Test Supplier",
			},
			{
				"item_code": dn_item.item_code,
				"warehouse": "_Test Warehouse - _TC",
				"qty": 2,
				"rate": 300,
				"conversion_factor": 1.0,
			},
		]

		if frappe.db.get_value("Item", "_Test Regular Item", "is_stock_item") == 1:
			make_stock_entry(item="_Test Regular Item", target="_Test Warehouse - _TC", qty=2, rate=100)

		# create so, po and dn
		so = make_sales_order(item_list=so_items, do_not_submit=True)
		so.submit()

		po = make_purchase_order(so.name, selected_items=[so_items[0]])[0]
		po.submit()

		dn = create_dn_against_so(so.name, delivered_qty=2)

		self.assertEqual(so.customer, po.customer)
		self.assertEqual(po.items[0].sales_order, so.name)
		self.assertEqual(po.items[0].item_code, po_item.item_code)
		self.assertEqual(dn.items[0].item_code, dn_item.item_code)
		# test po_item length
		self.assertEqual(len(po.items), 1)

		# test ordered_qty and reserved_qty for drop ship item
		bin_po_item = frappe.get_all(
			"Bin",
			filters={"item_code": po_item.item_code, "warehouse": "_Test Warehouse - _TC"},
			fields=["ordered_qty", "reserved_qty"],
		)

		ordered_qty = bin_po_item[0].ordered_qty if bin_po_item else 0.0
		reserved_qty = bin_po_item[0].reserved_qty if bin_po_item else 0.0

		# drop ship PO should not impact bin, test the same
		self.assertEqual(abs(flt(ordered_qty)), 0)
		self.assertEqual(abs(flt(reserved_qty)), 0)

		# test per_delivered status
		self.assertEqual(po.status, "To Receive and Bill")
		self.assertEqual(so.status, "To Deliver and Bill")
		po.update_dropship_received_qty([{"name": po.items[0].name, "qty_change": 2}])
		self.assertEqual(flt(frappe.db.get_value("Sales Order", so.name, "per_delivered"), 2), 100.00)
		po.load_from_db()
		so.reload()
		self.assertEqual(po.status, "To Bill")
		self.assertEqual(so.status, "To Bill")

		# test after closing so
		so.db_set("status", "Closed")
		so.update_reserved_qty()

		# test ordered_qty and reserved_qty for drop ship item after closing so
		bin_po_item = frappe.get_all(
			"Bin",
			filters={"item_code": po_item.item_code, "warehouse": "_Test Warehouse - _TC"},
			fields=["ordered_qty", "reserved_qty"],
		)

		ordered_qty = bin_po_item[0].ordered_qty if bin_po_item else 0.0
		reserved_qty = bin_po_item[0].reserved_qty if bin_po_item else 0.0

		self.assertEqual(abs(flt(ordered_qty)), 0)
		self.assertEqual(abs(flt(reserved_qty)), 0)

		# teardown
		so_update_status("Draft", so.name)
		dn.load_from_db()
		dn.cancel()
		po.cancel()
		so.load_from_db()
		so.cancel()

	def test_drop_shipping_partial_order(self):
		from hisaabdari.selling.doctype.sales_order.sales_order import update_status as so_update_status

		# make items
		po_item1 = make_item(
			"_Test Item for Drop Shipping 1", {"is_stock_item": 1, "delivered_by_supplier": 1}
		)
		po_item2 = make_item(
			"_Test Item for Drop Shipping 2", {"is_stock_item": 1, "delivered_by_supplier": 1}
		)

		so_items = [
			{
				"item_code": po_item1.item_code,
				"warehouse": "",
				"qty": 2,
				"rate": 400,
				"delivered_by_supplier": 1,
				"supplier": "_Test Supplier",
			},
			{
				"item_code": po_item2.item_code,
				"warehouse": "",
				"qty": 2,
				"rate": 400,
				"delivered_by_supplier": 1,
				"supplier": "_Test Supplier",
			},
		]

		# create so and po
		so = make_sales_order(item_list=so_items, do_not_submit=True)
		so.submit()

		# create po for only one item
		po1 = make_purchase_order(so.name, selected_items=[so_items[0]])[0]
		po1.submit()

		self.assertEqual(so.customer, po1.customer)
		self.assertEqual(po1.items[0].sales_order, so.name)
		self.assertEqual(po1.items[0].item_code, po_item1.item_code)
		# test po item length
		self.assertEqual(len(po1.items), 1)

		# create po for remaining item
		po2 = make_purchase_order(so.name, selected_items=[so_items[1]])[0]
		po2.submit()

		# teardown
		so_update_status("Draft", so.name)

		po1.cancel()
		po2.cancel()
		so.load_from_db()
		so.cancel()

	@ERPNextTestSuite.change_settings("Stock Settings", {"allow_to_edit_stock_uom_qty_for_purchase": 1})
	def test_purchase_order_for_rest_of_row_ordered_in_parts(self):
		item = make_item(
			properties={"stock_uom": "Kg"}, uoms=[{"uom": "Box", "conversion_factor": 0.666666667}]
		)
		so = make_sales_order(item_code=item.name, qty=3, do_not_submit=True)
		so.items[0].update({"uom": "Box", "conversion_factor": 0.666666667})
		so.submit()

		selected_items = [{"name": so.items[0].name, "item_code": item.name}]
		for _ in range(2):
			po = make_purchase_order(so.name, selected_items=selected_items)[0]
			po.supplier = "_Test Supplier"
			po.items[0].qty = 1
			po.submit()

		po = make_purchase_order(so.name, selected_items=selected_items)[0]
		self.assertEqual(po.items[0].qty, 1)
		po.supplier = "_Test Supplier"
		po.submit()

		so.reload()
		self.assertEqual(so.items[0].ordered_qty, so.items[0].stock_qty)

	def test_drop_shipping_full_for_default_suppliers(self):
		"""Test if multiple POs are generated in one go against different default suppliers."""
		if not frappe.db.exists("Item", "_Test Item for Drop Shipping 1"):
			make_item("_Test Item for Drop Shipping 1", {"is_stock_item": 1, "delivered_by_supplier": 1})

		if not frappe.db.exists("Item", "_Test Item for Drop Shipping 2"):
			make_item("_Test Item for Drop Shipping 2", {"is_stock_item": 1, "delivered_by_supplier": 1})

		so_items = [
			{
				"item_code": "_Test Item for Drop Shipping 1",
				"warehouse": "",
				"qty": 2,
				"rate": 400,
				"delivered_by_supplier": 1,
				"supplier": "_Test Supplier",
			},
			{
				"item_code": "_Test Item for Drop Shipping 2",
				"warehouse": "",
				"qty": 2,
				"rate": 400,
				"delivered_by_supplier": 1,
				"supplier": "_Test Supplier 1",
			},
		]

		# create so and po
		so = make_sales_order(item_list=so_items, do_not_submit=True)
		so.submit()

		purchase_orders = make_purchase_order(so.name, selected_items=so_items)

		self.assertEqual(len(purchase_orders), 2)
		supplier_list = sorted([purchase_orders[0].supplier, purchase_orders[1].supplier])
		self.assertEqual(supplier_list, ["_Test Supplier", "_Test Supplier 1"])

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_multiple_items": 1})
	@ERPNextTestSuite.change_settings("Buying Settings", {"allow_multiple_items": 0})
	def test_purchase_order_supplier_selection_uses_sales_order_rows(self):
		so = make_sales_order(
			item_list=[
				{"item_code": "_Test Item", "qty": 2, "rate": 100, "warehouse": "_Test Warehouse - _TC"},
				{"item_code": "_Test Item", "qty": 3, "rate": 100, "warehouse": "_Test Warehouse - _TC"},
			]
		)
		selected_items = [
			{"name": row.name, "item_code": row.item_code, "supplier": supplier}
			for row, supplier in zip(so.items, ["_Test Supplier", "_Test Supplier 1"], strict=True)
		]

		purchase_orders = make_purchase_order(so.name, selected_items=selected_items)

		self.assertEqual(len(purchase_orders), 2)
		for purchase_order in purchase_orders:
			row = so.items[0] if purchase_order.supplier == "_Test Supplier" else so.items[1]
			self.assertEqual(len(purchase_order.items), 1)
			self.assertEqual(purchase_order.items[0].sales_order_item, row.name)
			self.assertEqual(purchase_order.items[0].qty, row.qty)

		purchase_orders = make_purchase_order(so.name, selected_items=selected_items[:1])
		self.assertEqual(len(purchase_orders), 1)
		self.assertEqual(len(purchase_orders[0].items), 1)
		self.assertEqual(purchase_orders[0].items[0].sales_order_item, so.items[0].name)

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_multiple_items": 1})
	def test_purchase_order_rejects_ambiguous_or_foreign_rows(self):
		so = make_sales_order(
			item_list=[
				{"item_code": "_Test Item", "qty": 2, "rate": 100, "warehouse": "_Test Warehouse - _TC"},
				{"item_code": "_Test Item", "qty": 3, "rate": 100, "warehouse": "_Test Warehouse - _TC"},
			]
		)
		other_so = make_sales_order()
		for row_name in (None, other_so.items[0].name):
			with self.subTest(row_name=row_name):
				with self.assertRaisesRegex(frappe.ValidationError, "Select a valid Sales Order row"):
					make_purchase_order(
						so.name,
						selected_items=[
							{"name": row_name, "item_code": "_Test Item", "supplier": "_Test Supplier"}
						],
					)

	def test_ordered_qty_is_reset_when_cancelled_sales_order_is_unlinked(self):
		"""Cancelling a Sales Order unlinks its Purchase Orders, so `ordered_qty` must be recomputed."""
		for workflow_name in frappe.get_all(
			"Workflow", filters={"document_type": "Sales Order", "is_active": 1}, pluck="name"
		):
			workflow = frappe.get_doc("Workflow", workflow_name)
			workflow.is_active = 0
			workflow.save()

		selected_items = [{"item_code": "_Test Item", "supplier": "_Test Supplier"}]
		so = make_sales_order(item_code="_Test Item", qty=10)

		purchase_order = make_purchase_order(so.name, selected_items=selected_items)[0]
		purchase_order.schedule_date = add_days(nowdate(), 1)
		purchase_order.submit()

		so.reload()
		self.assertEqual(so.items[0].ordered_qty, 10)

		so.cancel()
		so.reload()
		self.assertEqual(so.items[0].ordered_qty, 0)

		amended_so = frappe.copy_doc(so)
		amended_so.amended_from = so.name
		amended_so.docstatus = 0
		amended_so.insert()
		amended_so.submit()

		self.assertEqual(amended_so.items[0].ordered_qty, 0)

		new_purchase_order = make_purchase_order(amended_so.name, selected_items=selected_items)[0]
		self.assertEqual(new_purchase_order.items[0].qty, 10)

	def test_reserved_qty_for_closing_so(self):
		bin = frappe.get_all(
			"Bin",
			filters={"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"},
			fields=["reserved_qty"],
		)

		existing_reserved_qty = bin[0].reserved_qty if bin else 0.0

		so = make_sales_order(item_code="_Test Item", qty=1)

		self.assertEqual(
			get_reserved_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"),
			existing_reserved_qty + 1,
		)

		so.update_status("Closed")

		self.assertEqual(
			get_reserved_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"),
			existing_reserved_qty,
		)

	def test_create_so_with_margin(self):
		so = make_sales_order(item_code="_Test Item", qty=1, do_not_submit=True)
		so.items[0].price_list_rate = price_list_rate = 100
		so.items[0].margin_type = "Percentage"
		so.items[0].margin_rate_or_amount = 25
		# set rate to zero, so that it is recalculated on save
		so.items[0].rate = 0
		so.save()

		new_so = frappe.copy_doc(so)
		new_so.save(ignore_permissions=True)

		self.assertEqual(new_so.get("items")[0].rate, flt((price_list_rate * 25) / 100 + price_list_rate))
		new_so.items[0].margin_rate_or_amount = 25
		new_so.payment_schedule = []
		new_so.save()
		new_so.submit()

		self.assertEqual(new_so.get("items")[0].rate, flt((price_list_rate * 25) / 100 + price_list_rate))

	def test_terms_auto_added(self):
		so = make_sales_order(do_not_save=1)

		self.assertFalse(so.get("payment_schedule"))

		so.insert()

		self.assertTrue(so.get("payment_schedule"))

	def test_terms_not_copied(self):
		so = make_sales_order()
		self.assertTrue(so.get("payment_schedule"))

		si = make_sales_invoice(so.name)
		self.assertFalse(si.get("payment_schedule"))

	def test_terms_copied(self):
		so = make_sales_order(do_not_copy=1, do_not_save=1)
		so.payment_terms_template = "_Test Payment Term Template"
		so.insert()
		so.submit()
		self.assertTrue(so.get("payment_schedule"))

		si = make_sales_invoice(so.name)
		si.insert()
		self.assertTrue(si.get("payment_schedule"))

	def test_update_status_endpoint_rejects_invalid_status(self):
		from hisaabdari.selling.doctype.sales_order.sales_order import update_status

		so = make_sales_order()
		# only Draft / On Hold / Closed are allowed, and only on a submitted order
		self.assertRaises(frappe.ValidationError, update_status, "Cancelled", so.name)

		draft = make_sales_order(do_not_submit=1)
		self.assertRaises(frappe.ValidationError, update_status, "Closed", draft.name)

	def test_update_child_keeps_paid_payment_term_outstanding(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import (
			create_payment_terms_template,
			get_payment_entry,
		)

		create_payment_terms_template()
		for invoice_portion in (100, 0):
			with self.subTest(invoice_portion=invoice_portion):
				so = make_sales_order(qty=1, rate=1000, do_not_save=True)
				so.payment_terms_template = "Test Receivable Template"
				so.set("payment_schedule", [])
				so.append(
					"payment_schedule",
					{
						"payment_term": "Basic Amount Receivable",
						"due_date": so.delivery_date,
						"invoice_portion": invoice_portion,
						"payment_amount": 1000,
					},
				)
				so.insert()
				so.submit()

				pe = get_payment_entry("Sales Order", so.name, party_amount=400)
				pe.reference_no = "1"
				pe.reference_date = nowdate()
				pe.references[0].allocated_amount = 400
				pe.insert()
				pe.submit()

				item = so.items[0]
				trans_item = json.dumps(
					[{"item_code": item.item_code, "qty": 1, "rate": 1000, "docname": item.name}]
				)
				update_child_qty_rate("Sales Order", trans_item, so.name)

				term = frappe.get_doc("Sales Order", so.name).payment_schedule[0]
				self.assertEqual(term.paid_amount, 400)
				self.assertEqual(term.outstanding, 600)
				self.assertEqual(term.base_outstanding, 600)

	def test_advance_payment_entry_unlink_against_sales_order(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		frappe.db.set_single_value("Accounts Settings", "unlink_advance_payment_on_cancelation_of_order", 0)

		so = make_sales_order()

		pe = get_payment_entry("Sales Order", so.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.paid_from_account_currency = so.currency
		pe.paid_to_account_currency = so.currency
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.paid_amount = so.grand_total
		pe.save(ignore_permissions=True)
		pe.submit()

		so_doc = frappe.get_doc("Sales Order", so.name)

		self.assertRaises(frappe.LinkExistsError, so_doc.cancel)

	@ERPNextTestSuite.change_settings(
		"Accounts Settings", {"unlink_advance_payment_on_cancelation_of_order": 1}
	)
	def test_advance_paid_upon_payment_cancellation(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		so = make_sales_order()

		pe = get_payment_entry("Sales Order", so.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.paid_from_account_currency = so.currency
		pe.paid_to_account_currency = so.currency
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.paid_amount = so.grand_total
		pe.save(ignore_permissions=True)
		pe.submit()
		so.reload()

		self.assertEqual(so.advance_paid, so.base_grand_total)

		# cancel advance payment
		pe.reload()
		pe.cancel()

		so.reload()
		self.assertEqual(so.advance_paid, 0)

	def test_cancel_sales_order_after_cancel_payment_entry(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		# make a sales order
		so = make_sales_order()

		# disable unlinking of payment entry
		frappe.db.set_single_value("Accounts Settings", "unlink_advance_payment_on_cancelation_of_order", 0)

		# create a payment entry against sales order
		pe = get_payment_entry("Sales Order", so.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.paid_from_account_currency = so.currency
		pe.paid_to_account_currency = so.currency
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.paid_amount = so.grand_total
		pe.save(ignore_permissions=True)
		pe.submit()

		# Cancel payment entry
		po_doc = frappe.get_doc("Payment Entry", pe.name)
		po_doc.cancel()

		# Cancel sales order
		try:
			so_doc = frappe.get_doc("Sales Order", so.name)
			so_doc.cancel()
		except Exception:
			self.fail("Can not cancel sales order with linked cancelled payment entry")

	def test_so_cancellation_when_si_drafted(self):
		"""
		Test to check if Sales Order gets cancelled if Sales Invoice is in Draft state
		Expected result: sales order should not get cancelled
		"""
		so = make_sales_order()
		so.submit()
		si = make_sales_invoice(so.name)
		si.save()

		self.assertRaises(frappe.ValidationError, so.cancel)

	def test_so_cancellation_after_si_submission(self):
		"""
		Test to check if Sales Order gets cancelled when linked Sales Invoice has been Submitted
		Expected result: Sales Order should not get cancelled
		"""
		so = make_sales_order()
		so.submit()
		si = make_sales_invoice(so.name)
		si.submit()

		so.load_from_db()
		self.assertRaises(frappe.LinkExistsError, so.cancel)

	def test_so_cancellation_after_dn_submission(self):
		"""
		Test to check if Sales Order gets cancelled when linked Delivery Note has been Submitted
		Expected result: Sales Order should not get cancelled
		"""
		so = make_sales_order()
		so.submit()
		dn = make_delivery_note(so.name)
		dn.submit()

		so.load_from_db()
		self.assertRaises(frappe.LinkExistsError, so.cancel)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"automatically_fetch_payment_terms": 1})
	def test_payment_terms_are_fetched_when_creating_sales_invoice(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import (
			create_payment_terms_template,
		)
		from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		so = make_sales_order(uom="_Test UOM", do_not_save=1)
		create_payment_terms_template()
		so.payment_terms_template = "Test Receivable Template"
		so.submit()

		si = create_sales_invoice(qty=10, uom="_Test UOM", do_not_save=1)
		si.items[0].sales_order = so.name
		si.items[0].so_detail = so.items[0].name
		si.insert()

		self.assertEqual(so.payment_terms_template, si.payment_terms_template)
		compare_payment_schedules(self, so, si)

	def test_zero_amount_sales_order_billing_status(self):
		from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		so = make_sales_order(uom="_Test UOM", do_not_save=1)
		so.items[0].rate = so.items[0].price_list_rate = 0
		so.save()
		so.submit()

		self.assertEqual(so.net_total, 0)
		self.assertEqual(so.billing_status, "Not Billed")

		si = create_sales_invoice(qty=10, uom="_Test UOM", do_not_save=1)
		si.price_list = "_Test Price List"
		si.items[0].rate = 0
		si.items[0].price_list_rate = 0
		si.items[0].sales_order = so.name
		si.items[0].so_detail = so.items[0].name
		si.save()
		si.submit()

		self.assertEqual(si.net_total, 0)
		so.load_from_db()
		self.assertEqual(so.billing_status, "Fully Billed")

	def test_so_billing_status_with_crnote_against_sales_return(self):
		"""
		| Step | Document creation                    |                               |
		|------+--------------------------------------+-------------------------------|
		|    1 | SO -> DN -> SI                       | SO Fully Billed and Completed |
		|    2 | DN -> Sales Return(Partial)          | SO 50% Delivered, 100% billed |
		|    3 | Sales Return(Partial) -> Credit Note | SO 50% Delivered, 50% billed  |

		"""
		from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		so = make_sales_order(uom="_Test UOM", do_not_save=1)
		so.save()
		so.submit()

		self.assertEqual(so.billing_status, "Not Billed")

		dn1 = make_delivery_note(so.name)
		dn1.taxes_and_charges = ""
		dn1.taxes.clear()
		dn1.save().submit()

		si = create_sales_invoice(qty=10, uom="_Test UOM", do_not_save=1)
		si.items[0].sales_order = so.name
		si.items[0].so_detail = so.items[0].name
		si.items[0].delivery_note = dn1.name
		si.items[0].dn_detail = dn1.items[0].name
		si.save()
		si.submit()

		so.reload()
		self.assertEqual(so.billing_status, "Fully Billed")
		self.assertEqual(so.status, "Completed")

		from hisaabdari.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		dn1.reload()
		dn_ret = create_delivery_note(is_return=1, return_against=dn1.name, qty=-5, do_not_submit=True)
		dn_ret.items[0].against_sales_order = so.name
		dn_ret.items[0].so_detail = so.items[0].name
		dn_ret.submit()

		so.reload()
		self.assertEqual(so.per_billed, 100)
		self.assertEqual(so.per_delivered, 50)

		cr_note = create_sales_invoice(is_return=1, qty=-1, uom="_Test UOM", do_not_submit=True)
		cr_note.items[0].qty = -5
		cr_note.items[0].sales_order = so.name
		cr_note.items[0].so_detail = so.items[0].name
		cr_note.items[0].delivery_note = dn_ret.name
		cr_note.items[0].dn_detail = dn_ret.items[0].name
		cr_note.update_billed_amount_in_sales_order = True
		cr_note.submit()

		so.reload()
		self.assertEqual(so.per_billed, 50)
		self.assertEqual(so.per_delivered, 50)

	def test_sales_order_partial_advance_payment(self):
		from hisaabdari.accounts.doctype.payment_entry.test_payment_entry import (
			create_payment_entry,
			get_payment_entry,
		)
		from hisaabdari.selling.doctype.customer.test_customer import get_customer_dict

		# Make a customer
		customer = get_customer_dict("QA Logistics")
		frappe.get_doc(customer).insert()

		# Make a Sales Order
		so = make_sales_order(
			customer="QA Logistics",
			item_list=[
				{"item_code": "_Test Item", "qty": 1, "rate": 200},
				{"item_code": "_Test Item 2", "qty": 1, "rate": 300},
			],
		)

		# Create a advance payment against that Sales Order
		pe = get_payment_entry("Sales Order", so.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.paid_from_account_currency = so.currency
		pe.paid_to_account_currency = so.currency
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.paid_amount = so.grand_total
		pe.save(ignore_permissions=True)
		pe.submit()

		# Make standalone advance payment entry
		create_payment_entry(
			payment_type="Receive",
			party_type="Customer",
			party="QA Logistics",
			paid_from="Debtors - _TC",
			paid_to="_Test Bank - _TC",
			save=1,
			submit=1,
		)

		si = make_sales_invoice(so.name)

		item = si.get("items")[1]
		si.remove(item)

		si.allocate_advances_automatically = 1
		si.save()

		self.assertEqual(len(si.get("advances")), 1)
		self.assertEqual(si.get("advances")[0].allocated_amount, 200)
		self.assertEqual(si.get("advances")[0].reference_name, pe.name)

		si.submit()
		pe.load_from_db()

		self.assertEqual(pe.references[0].reference_name, so.name)
		self.assertEqual(pe.references[0].allocated_amount, 300)
		self.assertEqual(pe.references[1].reference_name, si.name)
		self.assertEqual(pe.references[1].allocated_amount, 200)

	def test_auto_update_price_list(self):
		item = make_item(
			"_Test Auto Update Price List Item",
		)

		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 1)
		so = make_sales_order(
			item_code=item.name, currency="INR", qty=1, rate=100, price_list_rate=100, do_not_submit=True
		)
		so.save()

		item_price = frappe.db.get_value("Item Price", {"item_code": item.name}, "price_list_rate")
		self.assertEqual(item_price, 100)

		so = make_sales_order(
			item_code=item.name, currency="INR", qty=1, rate=200, price_list_rate=100, do_not_submit=True
		)
		so.save()

		item_price = frappe.db.get_value("Item Price", {"item_code": item.name}, "price_list_rate")
		self.assertEqual(item_price, 100)

		frappe.db.set_single_value("Stock Settings", "update_existing_price_list_rate", 1)
		so = make_sales_order(
			item_code=item.name, currency="INR", qty=1, rate=200, price_list_rate=200, do_not_submit=True
		)
		so.save()

		item_price = frappe.db.get_value("Item Price", {"item_code": item.name}, "price_list_rate")
		self.assertEqual(item_price, 200)

		frappe.db.set_single_value("Stock Settings", "update_existing_price_list_rate", 0)
		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)

	def test_delivery_note_rate_on_change_of_warehouse(self):
		from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

		item = make_item(
			"_Test Batch Item for Delivery Note Rate",
			{
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_number_series": "BH-SDDTBIFRM-.#####",
			},
		)

		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 1)
		so = make_sales_order(
			item_code=item.name, rate=27648.00, price_list_rate=27648.00, qty=1, do_not_submit=True
		)

		so.items[0].rate = 90
		so.save()
		self.assertTrue(so.items[0].discount_amount == 27558.0)
		so.submit()

		warehouse = create_warehouse("NW Warehouse FOR Rate", company=so.company)

		make_stock_entry(
			item_code=item.name,
			qty=2,
			target=warehouse,
			basic_rate=100,
			company=so.company,
			use_serial_batch_fields=1,
		)

		dn = make_delivery_note(so.name)
		dn.items[0].warehouse = warehouse
		dn.save()

		self.assertEqual(dn.items[0].rate, 90)

	def test_credit_limit_on_so_reopning(self):
		# set credit limit
		company = "_Test Company"
		customer = frappe.get_doc("Customer", "_Test Customer")
		customer.credit_limits = []
		customer.append(
			"credit_limits", {"company": company, "credit_limit": 1000, "bypass_credit_limit_check": False}
		)
		customer.save()

		so1 = make_sales_order(qty=9, rate=100, do_not_submit=True)
		so1.customer = customer.name
		so1.save().submit()

		so1.update_status("Closed")

		so2 = make_sales_order(qty=9, rate=100, do_not_submit=True)
		so2.customer = customer.name
		so2.save().submit()

		self.assertRaises(frappe.ValidationError, so1.update_status, "Draft")

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_zero_qty_in_sales_order": 1})
	def test_deliver_zero_qty_purchase_order(self):
		"""
		Test the flow of a Unit Price SO and DN creation against it until completion.
		Flow:
		SO Qty 0 -> Deliver +5 -> Update SO Qty +10 -> Deliver +5 -> SO is 100% delivered
		"""
		so = make_sales_order(qty=0)
		dn = make_delivery_note(so.name)

		self.assertEqual(dn.items[0].qty, 0)
		dn.items[0].qty = 5
		dn.submit()

		# Test SO impact after DN
		so.reload()
		self.assertEqual(so.items[0].delivered_qty, 5)
		self.assertFalse(so.per_delivered)
		self.assertEqual(so.status, "To Deliver and Bill")

		# Update SO Qty to final qty
		first_item_of_so = so.items[0]
		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_so.item_code,
					"rate": first_item_of_so.rate,
					"qty": 10,
					"docname": first_item_of_so.name,
				}
			]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

		# Test: DN maps pending qty from SO
		dn2 = make_delivery_note(so.name)

		so.reload()
		self.assertEqual(so.items[0].qty, 10)
		self.assertEqual(dn2.items[0].qty, 5)

		dn2.submit()

		so.reload()
		self.assertEqual(so.items[0].delivered_qty, 10)
		self.assertEqual(so.per_delivered, 100.0)
		self.assertEqual(so.status, "To Bill")

	@ERPNextTestSuite.change_settings("Selling Settings", {"allow_zero_qty_in_sales_order": 1})
	def test_bill_zero_qty_sales_order(self):
		so = make_sales_order(qty=0)

		self.assertEqual(so.grand_total, 0)
		self.assertFalse(so.per_billed)
		self.assertEqual(so.items[0].qty, 0)
		self.assertEqual(so.items[0].rate, 100)

		si = make_sales_invoice(so.name)
		self.assertEqual(si.items[0].qty, 0)
		self.assertEqual(si.items[0].rate, 100)

		si.items[0].qty = 5
		si.submit()

		so.reload()
		self.assertEqual(so.items[0].amount, 0)
		self.assertEqual(so.items[0].billed_amt, si.grand_total)
		# SO still has qty 0, so billed % should be unset
		self.assertFalse(so.per_billed)
		self.assertEqual(so.status, "To Deliver and Bill")

	def test_item_tax_transfer_from_sales_to_purchase(self):
		item_tax = frappe.new_doc("Item Tax Template")
		item_tax.title = "Test Item Tax Template"
		item_tax.company = "_Test Company"
		item_tax.append("taxes", {"tax_type": "_Test Account Service Tax - _TC", "tax_rate": 2})
		item_tax.save()

		item_group = frappe.get_doc("Item Group", "_Test Item Group")
		item_group.append("taxes", {"item_tax_template": "Test Item Tax Template - _TC"})
		item_group.save()

		so = make_sales_order(item_code="_Test Item", qty=1, do_not_submit=1)
		so.append(
			"taxes",
			{
				"account_head": "_Test Account Service Tax - _TC",
				"charge_type": "On Net Total",
				"description": "TDS",
				"doctype": "Sales Taxes and Charges",
				"rate": 2,
			},
		)
		so.submit()

		po = make_purchase_order(so.name, selected_items=so.items)[0]
		po.supplier = "_Test Supplier"
		po.items[0].rate = 100
		po.submit()
		self.assertEqual(po.taxes[0].tax_amount, 2)

	def test_make_purchase_order_does_not_inherit_party_fields(self):
		"""
		Customer-derived fields must not leak from a drop-ship SO into the PO.
		"""
		so_items = [
			{
				"item_code": "_Test Item",
				"warehouse": "",
				"qty": 1,
				"rate": 100,
				"delivered_by_supplier": 1,
				"supplier": "_Test Supplier",
			}
		]
		so = make_sales_order(item_list=so_items, do_not_submit=True)
		so.language = "ar"
		so.payment_terms_template = "_Test Payment Term Template"
		so.submit()

		po = make_purchase_order(so.name, selected_items=so_items)[0]

		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		self.assertEqual(po.language or None, supplier.language or None)
		self.assertEqual(po.payment_terms_template or None, supplier.payment_terms or None)

	def test_pending_quantity_after_update_item_during_invoice_creation(self):
		so = make_sales_order(qty=30, rate=100)

		si1 = make_sales_invoice(so.name)
		si1.get("items")[0].qty = 10
		si1.insert()
		si1.submit()

		first_item_of_so = so.get("items")[0]
		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_so.item_code,
					"rate": 1000,
					"qty": first_item_of_so.qty,
					"docname": first_item_of_so.name,
				},
			]
		)
		update_child_qty_rate("Sales Order", trans_item, so.name)

		si2 = make_sales_invoice(so.name)
		self.assertEqual(si2.items[0].qty, 20)


def compare_payment_schedules(doc, doc1, doc2):
	for index, schedule in enumerate(doc1.get("payment_schedule")):
		posting_date = doc1.get("bill_date") or doc1.get("posting_date") or doc1.get("transaction_date")
		due_date = schedule.due_date
		if schedule.due_date_based_on:
			due_date = get_due_date(schedule, posting_date=posting_date)
		doc.assertEqual(schedule.payment_term, doc2.payment_schedule[index].payment_term)
		doc.assertEqual(due_date, doc2.payment_schedule[index].due_date)
		doc.assertEqual(schedule.invoice_portion, doc2.payment_schedule[index].invoice_portion)
		doc.assertEqual(schedule.payment_amount, doc2.payment_schedule[index].payment_amount)


def make_sales_order(**args):
	so = frappe.new_doc("Sales Order")
	args = frappe._dict(args)
	if args.transaction_date:
		so.transaction_date = args.transaction_date

	so.set_warehouse = ""  # no need to test set_warehouse permission since it only affects the client
	so.company = args.company or "_Test Company"
	so.customer = args.customer or "_Test Customer"
	so.currency = args.currency or "INR"
	so.po_no = args.po_no or ""
	if args.selling_price_list:
		so.selling_price_list = args.selling_price_list

	if "warehouse" not in args:
		args.warehouse = "_Test Warehouse - _TC"

	if args.item_list:
		for item in args.item_list:
			so.append("items", item)

	else:
		so.append(
			"items",
			{
				"item_code": args.item or args.item_code or "_Test Item",
				"warehouse": args.warehouse,
				"qty": args.qty if args.qty is not None else 10,
				"uom": args.uom or None,
				"price_list_rate": args.price_list_rate or None,
				"discount_percentage": args.discount_percentage or None,
				"rate": args.rate or (None if args.price_list_rate else 100),
			},
		)

	so.delivery_date = add_days(so.transaction_date, 10)
	if not args.do_not_save:
		so.insert()
		if not args.do_not_submit:
			so.submit()
		else:
			so.payment_schedule = []
	else:
		so.payment_schedule = []

	return so


def create_dn_against_so(so, delivered_qty=0, do_not_submit=False):
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)

	dn = make_delivery_note(so)
	dn.get("items")[0].qty = delivered_qty or 5
	dn.insert()
	if not do_not_submit:
		dn.submit()
	return dn


def get_reserved_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "reserved_qty"))


def make_sales_order_workflow():
	if frappe.db.exists("Workflow", "SO Test Workflow"):
		doc = frappe.get_doc("Workflow", "SO Test Workflow")
		doc.set("is_active", 1)
		doc.save()
		return doc

	frappe.get_doc(doctype="Role", role_name="Test Junior Approver").insert(ignore_if_duplicate=True)
	frappe.get_doc(doctype="Role", role_name="Test Approver").insert(ignore_if_duplicate=True)
	frappe.cache().hdel("roles", frappe.session.user)

	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": "SO Test Workflow",
			"document_type": "Sales Order",
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			"send_email_alert": 0,
		}
	)
	workflow.append("states", dict(state="Pending", allow_edit="All"))
	workflow.append("states", dict(state="Approved", allow_edit="Test Approver", doc_status=1))
	workflow.append(
		"transitions",
		dict(
			state="Pending",
			action="Approve",
			next_state="Approved",
			allowed="Test Junior Approver",
			allow_self_approval=1,
			condition="doc.grand_total < 200",
		),
	)
	workflow.append(
		"transitions",
		dict(
			state="Pending",
			action="Approve",
			next_state="Approved",
			allowed="Test Approver",
			allow_self_approval=1,
			condition="doc.grand_total > 200",
		),
	)
	workflow.insert(ignore_permissions=True)

	return workflow


def make_sales_order_edit_perm_workflow():
	if frappe.db.exists("Workflow", "SO Edit Perm Workflow"):
		doc = frappe.get_doc("Workflow", "SO Edit Perm Workflow")
		doc.set("is_active", 1)
		doc.save()
		return doc

	frappe.get_doc(doctype="Role", role_name="Test Junior Approver").insert(ignore_if_duplicate=True)
	frappe.get_doc(doctype="Role", role_name="Test Approver").insert(ignore_if_duplicate=True)
	frappe.cache().hdel("roles", frappe.session.user)

	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": "SO Edit Perm Workflow",
			"document_type": "Sales Order",
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			"send_email_alert": 0,
		}
	)
	workflow.append("states", dict(state="Pending", allow_edit="All"))
	workflow.append("states", dict(state="Approved", allow_edit="Test Approver", doc_status=1))
	workflow.append(
		"transitions",
		dict(
			state="Pending",
			action="Approve",
			next_state="Approved",
			allowed="Test Junior Approver",
			allow_self_approval=1,
		),
	)
	workflow.insert(ignore_permissions=True)

	return workflow
