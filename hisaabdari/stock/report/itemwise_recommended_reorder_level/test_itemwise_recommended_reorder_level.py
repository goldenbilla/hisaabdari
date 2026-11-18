# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt

from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from hisaabdari.stock.report.itemwise_recommended_reorder_level.itemwise_recommended_reorder_level import (
	execute,
)
from hisaabdari.tests.utils import ERPNextTestSuite

WAREHOUSE = "Stores - _TC"


class TestItemwiseRecommendedReorderLevel(ERPNextTestSuite):
	def run_report(self, **extra):
		filters = frappe._dict({"from_date": "2026-06-01", "to_date": "2026-06-10"})
		filters.update(extra)
		return execute(filters)[1]

	def find_row(self, data, item_code):
		for row in data:
			if row[0] == item_code:
				return row
		return None

	def test_purchase_returns_are_not_consumption(self):
		from hisaabdari.stock.doctype.item.test_item import make_item
		from hisaabdari.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_return
		from hisaabdari.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt

		item = make_item(properties={"is_stock_item": 1}).name
		receipt = make_purchase_receipt(item_code=item, qty=10, rate=10, posting_date="2026-06-02")
		purchase_return = make_purchase_return(receipt.name)
		purchase_return.items[0].qty = -2
		purchase_return.posting_date = "2026-06-03"
		purchase_return.set_posting_time = 1
		purchase_return.submit()

		row = self.find_row(self.run_report(), item)

		self.assertEqual(flt(row[7]), 0)

	def test_stock_reconciliation_is_not_consumption(self):
		from hisaabdari.stock.doctype.item.test_item import make_item
		from hisaabdari.stock.doctype.stock_reconciliation.test_stock_reconciliation import (
			create_stock_reconciliation,
		)

		batch_item = make_item(properties={"has_batch_no": 1}).name
		batch_no = frappe.get_doc(doctype="Batch", item=batch_item, batch_id=f"{batch_item}-01").insert().name
		plain_item = make_item(properties={"is_stock_item": 1}).name
		make_stock_entry(
			item_code=batch_item,
			to_warehouse=WAREHOUSE,
			qty=10,
			rate=10,
			batch_no=batch_no,
			posting_date="2026-06-02",
		)
		make_stock_entry(
			item_code=plain_item, to_warehouse=WAREHOUSE, qty=10, rate=10, posting_date="2026-06-02"
		)

		# a batch row is posted as an outgoing leg for the old qty followed by the new qty
		reco = create_stock_reconciliation(
			item_code=batch_item,
			warehouse=WAREHOUSE,
			qty=12,
			rate=10,
			batch_no=batch_no,
			posting_date="2026-06-05",
		)
		self.assertTrue(
			frappe.db.exists(
				"Stock Ledger Entry", {"voucher_no": reco.name, "actual_qty": -10, "is_cancelled": 0}
			)
		)
		create_stock_reconciliation(
			item_code=plain_item, warehouse=WAREHOUSE, qty=7, rate=10, posting_date="2026-06-05"
		)

		data = self.run_report()
		for item in (batch_item, plain_item):
			row = self.find_row(data, item)
			self.assertEqual((flt(row[7]), flt(row[9])), (0, 0))  # consumed, total outgoing

	def test_from_date_after_to_date_is_refused_with_the_right_message(self):
		self.assertRaisesRegex(
			frappe.ValidationError,
			"From Date must be before To Date",
			self.run_report,
			from_date="2026-06-10",
			to_date="2026-06-01",
		)
