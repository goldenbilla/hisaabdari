# Copyright (c) 2026, HisaabDari contributors
# License: GNU General Public License v3. See license.txt

"""Stock Settings > "Use Delivery Notes and Purchase Receipts".

The test site keeps the switch on, because the tests carried over from ERPNext expect that.
These tests turn it off, which is how a new install starts.
"""

import frappe

from hisaabdari.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
from hisaabdari.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from hisaabdari.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from hisaabdari.buying.doctype.purchase_order.purchase_order import (
	make_purchase_invoice as make_purchase_invoice_from_order,
)
from hisaabdari.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from hisaabdari.selling.doctype.sales_order.sales_order import (
	make_sales_invoice as make_sales_invoice_from_order,
)
from hisaabdari.selling.doctype.sales_order.test_sales_order import make_sales_order
from hisaabdari.startup.boot import hide_delivery_note_and_purchase_receipt
from hisaabdari.stock.doctype.delivery_note.delivery_note import (
	make_sales_invoice as make_sales_invoice_from_delivery_note,
)
from hisaabdari.stock.doctype.delivery_note.test_delivery_note import create_delivery_note
from hisaabdari.stock.doctype.purchase_receipt.purchase_receipt import (
	make_purchase_invoice as make_purchase_invoice_from_receipt,
)
from hisaabdari.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt
from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from hisaabdari.stock.doctype.stock_settings.stock_settings import (
	hide_delivery_note_and_purchase_receipt_in_dashboard,
	use_delivery_note_and_purchase_receipt,
)
from hisaabdari.tests.utils import ERPNextTestSuite, change_settings

COMPANY = "_Test Company with perpetual inventory"
WAREHOUSE = "Stores - TCP1"


def switch(value):
	return change_settings("Stock Settings", use_delivery_note_and_purchase_receipt=value)


def sales_invoice(**args):
	return create_sales_invoice(
		company=COMPANY,
		debit_to="Debtors - TCP1",
		warehouse=WAREHOUSE,
		income_account="Sales - TCP1",
		expense_account="Cost of Goods Sold - TCP1",
		cost_center="Main - TCP1",
		**args,
	)


def purchase_invoice(**args):
	return make_purchase_invoice(
		company=COMPANY,
		warehouse=WAREHOUSE,
		cost_center="Main - TCP1",
		expense_account="_Test Account Cost for Goods Sold - TCP1",
		**args,
	)


def _rows(doctype, **kwargs):
	return [tuple(row) for row in frappe.get_all(doctype, **kwargs)]


def stock_ledger(doc):
	return _rows(
		"Stock Ledger Entry",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
		fields=["item_code", "warehouse", "actual_qty", "stock_value_difference"],
		order_by="item_code, warehouse",
		as_list=True,
	)


def general_ledger(doc):
	return _rows(
		"GL Entry",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
		fields=["account", "debit", "credit"],
		order_by="account, debit, credit",
		as_list=True,
	)


class TestDeliveryReceiptSwitch(ERPNextTestSuite):
	def setUp(self):
		# documents left on the site by other test modules must not stop the switch from being turned off
		for doctype in ("Delivery Note", "Purchase Receipt"):
			frappe.db.set_value(doctype, {"docstatus": 1, "status": "To Bill"}, "status", "Closed")

		make_stock_entry(item_code="_Test Item", target=WAREHOUSE, qty=50, basic_rate=100)

	def test_test_site_keeps_the_switch_on(self):
		self.assertEqual(use_delivery_note_and_purchase_receipt(), 1)

	def test_sales_invoice_moves_stock_when_off(self):
		expected = sales_invoice(update_stock=1, qty=2, rate=150)
		self.assertEqual(stock_ledger(expected), [("_Test Item", WAREHOUSE, -2.0, -200.0)])

		with switch(0):
			si = sales_invoice(update_stock=0, qty=2, rate=150)

		self.assertEqual(si.update_stock, 1)
		self.assertEqual(stock_ledger(si), stock_ledger(expected))
		self.assertEqual(general_ledger(si), general_ledger(expected))
		self.assertIn(("Stock In Hand - TCP1", 0.0, 200.0), general_ledger(si))
		self.assertIn(("Cost of Goods Sold - TCP1", 200.0, 0.0), general_ledger(si))

	def test_purchase_invoice_moves_stock_when_off(self):
		expected = purchase_invoice(update_stock=1, qty=5, rate=50)
		self.assertEqual(stock_ledger(expected), [("_Test Item", WAREHOUSE, 5.0, 250.0)])

		with switch(0):
			pi = purchase_invoice(update_stock=0, qty=5, rate=50)

		self.assertEqual(pi.update_stock, 1)
		self.assertEqual(stock_ledger(pi), stock_ledger(expected))
		self.assertEqual(general_ledger(pi), general_ledger(expected))
		self.assertIn(("Stock In Hand - TCP1", 250.0, 0.0), general_ledger(pi))

	def test_purchase_invoice_row_without_item_code_when_off(self):
		with switch(0):
			pi = purchase_invoice(update_stock=0, qty=5, rate=50, do_not_save=True)
			pi.append(
				"items",
				{
					"item_name": "Electricity bill",
					"description": "Electricity bill",
					"qty": 1,
					"rate": 300,
					"uom": "Nos",
					"expense_account": "_Test Account Cost for Goods Sold - TCP1",
					"cost_center": "Main - TCP1",
				},
			)
			pi.insert()
			pi.submit()

		self.assertEqual(pi.update_stock, 1)
		self.assertEqual(stock_ledger(pi), [("_Test Item", WAREHOUSE, 5.0, 250.0)])
		self.assertIn(("_Test Account Cost for Goods Sold - TCP1", 300.0, 0.0), general_ledger(pi))

	def test_invoices_without_any_item_code_when_off(self):
		with switch(0):
			pi = purchase_invoice(update_stock=0, do_not_save=True)
			pi.items = []
			pi.append(
				"items",
				{
					"item_name": "Electricity bill",
					"description": "Electricity bill",
					"qty": 1,
					"rate": 300,
					"uom": "Nos",
					"expense_account": "_Test Account Cost for Goods Sold - TCP1",
					"cost_center": "Main - TCP1",
				},
			)
			pi.insert()
			pi.submit()

			si = sales_invoice(update_stock=0, do_not_save=True)
			si.items = []
			si.append(
				"items",
				{
					"item_name": "Repair work",
					"description": "Repair work",
					"qty": 1,
					"rate": 300,
					"uom": "Nos",
					"income_account": "Sales - TCP1",
					"cost_center": "Main - TCP1",
				},
			)
			si.insert()
			si.submit()

		self.assertEqual(stock_ledger(pi), [])
		self.assertCountEqual(
			general_ledger(pi),
			[("Creditors - TCP1", 0.0, 300.0), ("_Test Account Cost for Goods Sold - TCP1", 300.0, 0.0)],
		)
		self.assertEqual(stock_ledger(si), [])
		self.assertCountEqual(general_ledger(si), [("Debtors - TCP1", 300.0, 0.0), ("Sales - TCP1", 0.0, 300.0)])

	def test_opening_invoices_keep_their_value(self):
		with switch(0):
			si = sales_invoice(update_stock=0, do_not_save=True)
			si.is_opening = "Yes"
			si.items[0].income_account = "Temporary Opening - TCP1"
			si.insert()
			si.submit()

			pi = purchase_invoice(update_stock=0, do_not_save=True)
			pi.is_opening = "Yes"
			pi.items[0].expense_account = "Temporary Opening - TCP1"
			pi.insert()
			pi.submit()

		for doc in (si, pi):
			self.assertEqual(doc.update_stock, 0)
			self.assertEqual(stock_ledger(doc), [])

	def test_drop_shipped_sales_invoice_keeps_its_value(self):
		# ERPNext refuses to move stock for goods the supplier delivers directly
		with switch(0):
			si = sales_invoice(update_stock=0, do_not_save=True)
			si.items[0].delivered_by_supplier = 1
			si.insert()

		self.assertEqual(si.update_stock, 0)

	def test_invoice_made_from_delivery_note_keeps_its_value(self):
		with switch(0):
			# the doctype is hidden from users but still works for code
			dn = create_delivery_note(
				company=COMPANY,
				warehouse=WAREHOUSE,
				expense_account="Cost of Goods Sold - TCP1",
				cost_center="Main - TCP1",
				qty=3,
			)
			self.assertEqual(stock_ledger(dn), [("_Test Item", WAREHOUSE, -3.0, -300.0)])

			si = make_sales_invoice_from_delivery_note(dn.name)
			si.insert()
			si.submit()

		self.assertEqual(si.items[0].delivery_note, dn.name)
		self.assertEqual(si.update_stock, 0)
		self.assertEqual(stock_ledger(si), [])

	def test_invoice_made_from_purchase_receipt_keeps_its_value(self):
		with switch(0):
			pr = make_purchase_receipt(company=COMPANY, warehouse=WAREHOUSE, qty=4, rate=50)
			self.assertEqual(stock_ledger(pr), [("_Test Item", WAREHOUSE, 4.0, 200.0)])

			pi = make_purchase_invoice_from_receipt(pr.name)
			pi.insert()
			pi.submit()

		self.assertEqual(pi.items[0].purchase_receipt, pr.name)
		self.assertEqual(pi.update_stock, 0)
		self.assertEqual(stock_ledger(pi), [])

	def test_sales_return_follows_its_invoice(self):
		without_stock = sales_invoice(update_stock=0, qty=2)
		self.assertEqual(stock_ledger(without_stock), [])

		with switch(0):
			credit_note = make_sales_return(without_stock.name)
			credit_note.insert()
			credit_note.submit()
			self.assertEqual(credit_note.update_stock, 0)
			self.assertEqual(stock_ledger(credit_note), [])

			with_stock = sales_invoice(qty=2)
			credit_note = make_sales_return(with_stock.name)
			credit_note.insert()
			credit_note.submit()
			self.assertEqual(credit_note.update_stock, 1)
			self.assertEqual(stock_ledger(credit_note), [("_Test Item", WAREHOUSE, 2.0, 200.0)])

	def test_purchase_return_follows_its_invoice(self):
		without_stock = purchase_invoice(update_stock=0, qty=5, rate=50)
		self.assertEqual(stock_ledger(without_stock), [])

		with switch(0):
			debit_note = make_debit_note(without_stock.name)
			debit_note.insert()
			debit_note.submit()
			self.assertEqual(debit_note.update_stock, 0)
			self.assertEqual(stock_ledger(debit_note), [])

			with_stock = purchase_invoice(qty=5, rate=50)
			debit_note = make_debit_note(with_stock.name)
			debit_note.insert()
			debit_note.submit()
			self.assertEqual(debit_note.update_stock, 1)
			self.assertEqual(stock_ledger(debit_note), [("_Test Item", WAREHOUSE, -5.0, -250.0)])

	def test_sales_order_is_delivered_by_the_invoice(self):
		make_stock_entry(item_code="_Test Item", target="_Test Warehouse - _TC", qty=10, basic_rate=100)

		with switch(0):
			so = make_sales_order(qty=10)
			self.assertEqual(so.status, "To Deliver and Bill")

			si = make_sales_invoice_from_order(so.name)
			si.items[0].qty = 4
			si.insert()
			si.submit()
			self.assertEqual(si.update_stock, 1)

			so.reload()
			self.assertEqual(so.items[0].delivered_qty, 4)
			self.assertEqual(so.per_delivered, 40)
			self.assertEqual(so.per_billed, 40)
			self.assertEqual(so.status, "To Deliver and Bill")

			si = make_sales_invoice_from_order(so.name)
			si.insert()
			si.submit()

			so.reload()
			self.assertEqual(so.items[0].delivered_qty, 10)
			self.assertEqual(so.per_delivered, 100)
			self.assertEqual(so.per_billed, 100)
			self.assertEqual(so.status, "Completed")

	def test_purchase_order_is_received_by_the_invoice(self):
		with switch(0):
			po = create_purchase_order(qty=10)
			self.assertEqual(po.status, "To Receive and Bill")

			pi = make_purchase_invoice_from_order(po.name)
			pi.insert()
			pi.submit()
			self.assertEqual(pi.update_stock, 1)
			self.assertEqual(
				[row[:3] for row in stock_ledger(pi)], [("_Test Item", "_Test Warehouse - _TC", 10.0)]
			)

			po.reload()
			self.assertEqual(po.items[0].received_qty, 10)
			self.assertEqual(po.per_received, 100)
			self.assertEqual(po.per_billed, 100)
			self.assertEqual(po.status, "Completed")

	def test_turning_it_on_restores_erpnext_behaviour(self):
		with switch(0):
			self.assertEqual(sales_invoice(update_stock=0).update_stock, 1)

		with switch(1):
			si = sales_invoice(update_stock=0)
			pi = purchase_invoice(update_stock=0)

			for doc in (si, pi):
				self.assertEqual(doc.update_stock, 0)
				self.assertEqual(stock_ledger(doc), [])

			# a row without an item code is refused again on an invoice that moves stock
			pi = purchase_invoice(update_stock=1, do_not_save=True)
			pi.append("items", {"item_name": "Electricity bill", "qty": 1, "rate": 300})
			self.assertRaises(frappe.ValidationError, pi.insert)

	def test_cannot_turn_off_while_documents_are_not_invoiced(self):
		create_delivery_note(
			company=COMPANY,
			warehouse=WAREHOUSE,
			expense_account="Cost of Goods Sold - TCP1",
			cost_center="Main - TCP1",
		)
		make_purchase_receipt(company=COMPANY, warehouse=WAREHOUSE)
		make_purchase_receipt(company=COMPANY, warehouse=WAREHOUSE)

		settings = frappe.get_doc("Stock Settings")
		settings.use_delivery_note_and_purchase_receipt = 0
		with self.assertRaises(frappe.ValidationError) as error:
			settings.save()

		self.assertIn("1 Delivery Note", str(error.exception))
		self.assertIn("2 Purchase Receipt", str(error.exception))
		self.assertEqual(use_delivery_note_and_purchase_receipt(), 1)

	def test_hidden_from_boot_and_dashboards_when_off(self):
		def boot():
			return frappe._dict(
				user={
					"can_read": ["Delivery Note", "Purchase Receipt", "Sales Invoice"],
					"can_create": ["Delivery Note", "Purchase Receipt", "Sales Invoice"],
					"can_search": ["Delivery Note", "Purchase Receipt", "Sales Invoice"],
				},
				allowed_reports={"Delivery Note Trends": {}, "Stock Ledger": {}},
				module_sidebars={
					"Stock": {
						"items": [
							{"link_to": "Delivery Note"},
							{"link_to": "Purchase Receipt Trends"},
							{"link_to": "Item"},
							{"type": "Section Break"},
						]
					}
				},
			)

		bootinfo = boot()
		hide_delivery_note_and_purchase_receipt(bootinfo)
		# reading stays allowed, so existing documents still open
		self.assertEqual(len(bootinfo.user["can_read"]), 3)
		self.assertEqual(bootinfo.user["can_create"], ["Sales Invoice"])
		self.assertEqual(bootinfo.user["can_search"], ["Sales Invoice"])
		self.assertEqual(list(bootinfo.allowed_reports), ["Stock Ledger"])
		self.assertEqual(
			bootinfo.module_sidebars["Stock"]["items"], [{"link_to": "Item"}, {"type": "Section Break"}]
		)

		def dashboard():
			return frappe._dict(
				transactions=[
					{"label": "Fulfillment", "items": ["Sales Invoice", "Delivery Note"]},
					{"label": "Receipt", "items": ["Purchase Receipt"]},
				]
			)

		self.assertEqual(
			hide_delivery_note_and_purchase_receipt_in_dashboard(dashboard()).transactions, dashboard().transactions
		)
		with switch(0):
			self.assertEqual(
				hide_delivery_note_and_purchase_receipt_in_dashboard(dashboard()).transactions,
				[{"label": "Fulfillment", "items": ["Sales Invoice"]}],
			)
