# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.permissions import add_user_permission, remove_user_permission
from frappe.utils import add_days, cint, cstr, flt, get_time, getdate, nowdate, nowtime, today

from hisaabdari.accounts.doctype.account.test_account import get_inventory_account
from hisaabdari.controllers.accounts_controller import InvalidQtyError
from hisaabdari.stock.doctype.item.test_item import (
	create_item,
	make_item,
)
from hisaabdari.stock.doctype.serial_and_batch_bundle.test_serial_and_batch_bundle import (
	get_batch_from_bundle,
	get_serial_nos_from_bundle,
	make_serial_batch_bundle,
)
from hisaabdari.stock.doctype.serial_no.serial_no import *
from hisaabdari.stock.doctype.stock_entry.stock_entry import (
	FinishedGoodError,
	make_stock_in_entry,
)
from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from hisaabdari.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockFreezeError
from hisaabdari.stock.doctype.stock_reconciliation.stock_reconciliation import (
	OpeningEntryAccountError,
)
from hisaabdari.stock.doctype.stock_reconciliation.test_stock_reconciliation import (
	create_stock_reconciliation,
)
from hisaabdari.stock.serial_batch_bundle import SerialBatchCreation
from hisaabdari.stock.stock_ledger import NegativeStockError, get_previous_sle
from hisaabdari.tests.utils import ERPNextTestSuite


def get_sle(**args):
	condition, values = "", []
	for key, value in args.items():
		condition += " and " if condition else " where "
		condition += f"`{key}`=%s"
		values.append(value)

	return frappe.db.sql(
		"""select * from `tabStock Ledger Entry` %s
		order by timestamp(posting_date, posting_time) desc, creation desc limit 1"""
		% condition,
		values,
		as_dict=1,
	)


def get_in_transit_warehouse(company):
	in_transit_warehouse = frappe.db.exists("Warehouse", {"warehouse_name": "Transit", "company": company})

	if not in_transit_warehouse:
		in_transit_warehouse = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "Transit",
					"company": company,
				}
			)
			.insert()
			.name
		)

	return in_transit_warehouse


def stock_entry_row(item_code, qty, **kwargs):
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	return {
		"item_code": item_code,
		"qty": qty,
		"transfer_qty": qty,
		"uom": stock_uom,
		"stock_uom": stock_uom,
		"conversion_factor": 1,
		**kwargs,
	}


class TestStockEntry(ERPNextTestSuite):
	def setUp(self):
		self.load_test_records("Stock Entry")
		frappe.local.flags.dont_execute_stock_reposts = False

	def test_stock_entry_qty(self):
		item_code = "_Test Item 2"
		warehouse = "_Test Warehouse - _TC"
		se = make_stock_entry(item_code=item_code, target=warehouse, qty=0, do_not_save=True)
		with self.assertRaises(InvalidQtyError):
			se.save()

		# No error with qty=1
		se.items[0].qty = 1
		se.save()
		self.assertEqual(se.items[0].qty, 1)

	def test_fifo(self):
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		item_code = "_Test Item 2"
		warehouse = "_Test Warehouse - _TC"

		create_stock_reconciliation(
			item_code="_Test Item 2", warehouse="_Test Warehouse - _TC", qty=0, rate=100
		)

		make_stock_entry(item_code=item_code, target=warehouse, qty=1, basic_rate=10)
		sle = get_sle(item_code=item_code, warehouse=warehouse)[0]

		self.assertEqual([[1, 10]], frappe.safe_eval(sle.stock_queue))

		# negative qty
		make_stock_entry(item_code=item_code, source=warehouse, qty=2, basic_rate=10)
		sle = get_sle(item_code=item_code, warehouse=warehouse)[0]

		self.assertEqual([[-1, 10]], frappe.safe_eval(sle.stock_queue))

		# further negative
		make_stock_entry(item_code=item_code, source=warehouse, qty=1)
		sle = get_sle(item_code=item_code, warehouse=warehouse)[0]

		self.assertEqual([[-2, 10]], frappe.safe_eval(sle.stock_queue))

		# move stock to positive
		make_stock_entry(item_code=item_code, target=warehouse, qty=3, basic_rate=20)
		sle = get_sle(item_code=item_code, warehouse=warehouse)[0]
		self.assertEqual([[1, 20]], frappe.safe_eval(sle.stock_queue))

		# incoming entry with diff rate
		make_stock_entry(item_code=item_code, target=warehouse, qty=1, basic_rate=30)
		sle = get_sle(item_code=item_code, warehouse=warehouse)[0]

		self.assertEqual([[1, 20], [1, 30]], frappe.safe_eval(sle.stock_queue))

		frappe.db.set_default("allow_negative_stock", 0)

	def test_barcode_item_stock_entry(self):
		item_code = make_item("_Test Item Stock Entry For Barcode", barcode="BDD-1234567890")

		se = make_stock_entry(item_code=item_code.name, target="_Test Warehouse - _TC", qty=1, basic_rate=100)
		self.assertEqual(se.items[0].barcode, "BDD-1234567890")

	def test_add_to_transit_entry(self):
		from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

		item_code = "_Test Transit Item"
		company = "_Test Company"

		create_warehouse("Test From Warehouse")
		create_warehouse("Test Transit Warehouse")
		create_warehouse("Test To Warehouse")

		create_item(
			item_code=item_code,
			is_stock_item=1,
			is_purchase_item=1,
			company=company,
		)

		# create inward stock entry
		make_stock_entry(
			item_code=item_code,
			target="Test From Warehouse - _TC",
			qty=10,
			basic_rate=100,
			expense_account="Stock Adjustment - _TC",
			cost_center="Main - _TC",
		)

		transit_entry = make_stock_entry(
			item_code=item_code,
			source="Test From Warehouse - _TC",
			target="Test Transit Warehouse - _TC",
			add_to_transit=1,
			stock_entry_type="Material Transfer",
			purpose="Material Transfer",
			qty=10,
			basic_rate=100,
			expense_account="Stock Adjustment - _TC",
			cost_center="Main - _TC",
		)

		end_transit_entry = make_stock_in_entry(transit_entry.name)

		self.assertEqual(end_transit_entry.stock_entry_type, "Material Transfer")
		self.assertEqual(end_transit_entry.purpose, "Material Transfer")
		self.assertEqual(transit_entry.name, end_transit_entry.outgoing_stock_entry)
		self.assertEqual(transit_entry.name, end_transit_entry.items[0].against_stock_entry)
		self.assertEqual(transit_entry.items[0].name, end_transit_entry.items[0].ste_detail)

		transit_entry.reload()
		self.assertEqual(transit_entry.per_transferred, 0)

		end_transit_entry.to_warehouse = "Test To Warehouse - _TC"
		end_transit_entry.items[0].t_warehouse = "Test To Warehouse - _TC"
		end_transit_entry.save().submit()

		transit_entry.reload()
		self.assertEqual(transit_entry.per_transferred, 100)

	def test_end_transit_qty_with_inexact_uom_conversion(self):
		company = "_Test Company"
		transit_warehouse = get_in_transit_warehouse(company)
		frappe.get_doc({"doctype": "UOM", "uom_name": "_Test Lb"}).insert(ignore_if_duplicate=True)
		item_code = make_item(
			properties={"is_stock_item": 1, "stock_uom": "Kg"},
			uoms=[{"uom": "_Test Lb", "conversion_factor": 0.45359}],
		).name
		make_stock_entry(item_code=item_code, target="_Test Warehouse - _TC", qty=100, basic_rate=100)

		transit_entry = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target=transit_warehouse,
			purpose="Material Transfer",
			add_to_transit=1,
			qty=75,
			basic_rate=100,
			do_not_save=True,
		)
		transit_entry.items[0].uom = "_Test Lb"
		transit_entry.items[0].conversion_factor = 0.45359
		transit_entry.save().submit()

		self.assertEqual(make_stock_in_entry(transit_entry.name).items[0].qty, 75)

	def test_end_transit_after_a_partial_receipt_in_an_inexact_uom(self):
		company = "_Test Company"
		transit_warehouse = get_in_transit_warehouse(company)
		frappe.get_doc({"doctype": "UOM", "uom_name": "_Test Pack"}).insert(ignore_if_duplicate=True)
		item_code = make_item(
			properties={"is_stock_item": 1, "stock_uom": "Kg"},
			uoms=[{"uom": "_Test Pack", "conversion_factor": 2.5004}],
		).name
		make_stock_entry(item_code=item_code, target="_Test Warehouse - _TC", qty=10, basic_rate=100)

		transit_entry = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target=transit_warehouse,
			purpose="Material Transfer",
			add_to_transit=1,
			qty=1,
			basic_rate=100,
			do_not_save=True,
		)
		transit_entry.items[0].update({"uom": "_Test Pack", "conversion_factor": 2.5004})
		transit_entry.save().submit()

		for qty in (0.333, None):
			receipt = make_stock_in_entry(transit_entry.name)
			receipt.items[0].t_warehouse = "_Test Warehouse 1 - _TC"
			if qty:
				receipt.items[0].qty = qty
			receipt.save().submit()

		from hisaabdari.stock.utils import get_stock_balance

		self.assertEqual(get_stock_balance(item_code, transit_warehouse), 0)

	def test_end_transit_qty_with_uom_conversion(self):
		"""transferred_qty is tracked in the stock UOM, so the end transit qty must be converted back."""
		company = "_Test Company"
		source_warehouse = "_Test Warehouse - _TC"
		target_warehouse = "_Test Warehouse 1 - _TC"
		transit_warehouse = get_in_transit_warehouse(company)

		item_code = make_item(
			"_Test Transit UOM Conversion Item",
			{"is_stock_item": 1, "stock_uom": "Nos", "uoms": [{"uom": "Kg", "conversion_factor": 0.5}]},
		).name

		make_stock_entry(item_code=item_code, target=source_warehouse, qty=100, basic_rate=100)

		transit_entry = make_stock_entry(
			item_code=item_code,
			source=source_warehouse,
			target=transit_warehouse,
			purpose="Material Transfer",
			add_to_transit=1,
			qty=10,
			basic_rate=100,
			do_not_save=True,
		)
		transit_entry.items[0].uom = "Kg"
		transit_entry.items[0].conversion_factor = 0.5
		transit_entry.save().submit()
		self.assertEqual(transit_entry.items[0].transfer_qty, 5)

		partial_entry = make_stock_in_entry(transit_entry.name)
		partial_entry.to_warehouse = target_warehouse
		partial_entry.items[0].qty = 4
		partial_entry.items[0].t_warehouse = target_warehouse
		partial_entry.save().submit()

		remaining_entry = make_stock_in_entry(transit_entry.name)
		self.assertEqual(remaining_entry.items[0].uom, "Kg")
		self.assertEqual(remaining_entry.items[0].qty, 6)

		remaining_entry.to_warehouse = target_warehouse
		remaining_entry.items[0].t_warehouse = target_warehouse
		remaining_entry.save().submit()

		self.assertFalse(make_stock_in_entry(transit_entry.name).get("items"))

	def test_end_transit_maps_smallest_remaining_qty(self):
		"""The smallest storable remainder survives binary subtraction, 2.001 - 2 is 0.0009999999999998899."""
		company = "_Test Company"
		source_warehouse = "_Test Warehouse - _TC"
		target_warehouse = "_Test Warehouse 1 - _TC"
		transit_warehouse = get_in_transit_warehouse(company)

		item_code = make_item(
			"_Test Transit Fractional Item", {"is_stock_item": 1, "stock_uom": "Litre"}
		).name
		smallest_qty = 1 / (10 ** frappe.get_precision("Stock Entry Detail", "transfer_qty"))

		make_stock_entry(item_code=item_code, target=source_warehouse, qty=100, basic_rate=100)

		transit_entry = make_stock_entry(
			item_code=item_code,
			source=source_warehouse,
			target=transit_warehouse,
			purpose="Material Transfer",
			add_to_transit=1,
			qty=2 + smallest_qty,
			basic_rate=100,
		)

		partial_entry = make_stock_in_entry(transit_entry.name)
		partial_entry.to_warehouse = target_warehouse
		partial_entry.items[0].qty = 2
		partial_entry.items[0].t_warehouse = target_warehouse
		partial_entry.save().submit()

		remaining_entry = make_stock_in_entry(transit_entry.name)
		self.assertEqual(remaining_entry.items[0].qty, smallest_qty)

	def test_material_receipt_gl_entry(self):
		company = frappe.db.get_value("Warehouse", "Stores - TCP1", "company")

		mr = make_stock_entry(
			item_code="_Test Item",
			target="Stores - TCP1",
			company=company,
			qty=50,
			basic_rate=100,
			expense_account="Stock Adjustment - TCP1",
		)

		stock_in_hand_account = get_inventory_account(mr.company, mr.get("items")[0].t_warehouse)
		self.check_stock_ledger_entries("Stock Entry", mr.name, [["_Test Item", "Stores - TCP1", 50.0]])

		self.check_gl_entries(
			"Stock Entry",
			mr.name,
			sorted([[stock_in_hand_account, 5000.0, 0.0], ["Stock Adjustment - TCP1", 0.0, 5000.0]]),
		)

		mr.cancel()

		self.assertTrue(
			frappe.db.sql(
				"""select * from `tabStock Ledger Entry`
			where voucher_type='Stock Entry' and voucher_no=%s""",
				mr.name,
			)
		)

		self.assertTrue(
			frappe.db.sql(
				"""select * from `tabGL Entry`
			where voucher_type='Stock Entry' and voucher_no=%s""",
				mr.name,
			)
		)

	def test_material_issue_gl_entry(self):
		company = frappe.db.get_value("Warehouse", "Stores - TCP1", "company")
		make_stock_entry(
			item_code="_Test Item",
			target="Stores - TCP1",
			company=company,
			qty=50,
			basic_rate=100,
			expense_account="Stock Adjustment - TCP1",
		)

		mi = make_stock_entry(
			item_code="_Test Item",
			source="Stores - TCP1",
			company=company,
			qty=40,
			expense_account="Stock Adjustment - TCP1",
		)

		self.check_stock_ledger_entries("Stock Entry", mi.name, [["_Test Item", "Stores - TCP1", -40.0]])

		stock_in_hand_account = get_inventory_account(mi.company, "Stores - TCP1")
		stock_value_diff = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": "Stock Entry", "voucher_no": mi.name},
				"stock_value_difference",
			)
		)

		self.check_gl_entries(
			"Stock Entry",
			mi.name,
			sorted(
				[
					[stock_in_hand_account, 0.0, stock_value_diff],
					["Stock Adjustment - TCP1", stock_value_diff, 0.0],
				]
			),
		)
		mi.cancel()

	def test_material_transfer_gl_entry(self):
		company = frappe.db.get_value("Warehouse", "Stores - TCP1", "company")

		item_code = "Hand Sanitizer - 001"
		create_item(
			item_code=item_code,
			is_stock_item=1,
			is_purchase_item=1,
			opening_stock=1000,
			valuation_rate=10,
			company=company,
			warehouse="Stores - TCP1",
		)

		mtn = make_stock_entry(
			item_code=item_code,
			source="Stores - TCP1",
			target="Finished Goods - TCP1",
			qty=45,
			company=company,
		)

		self.check_stock_ledger_entries(
			"Stock Entry",
			mtn.name,
			[[item_code, "Stores - TCP1", -45.0], [item_code, "Finished Goods - TCP1", 45.0]],
		)

		source_warehouse_account = get_inventory_account(mtn.company, mtn.get("items")[0].s_warehouse)

		target_warehouse_account = get_inventory_account(mtn.company, mtn.get("items")[0].t_warehouse)

		if source_warehouse_account == target_warehouse_account:
			# no gl entry as both source and target warehouse has linked to same account.
			self.assertFalse(
				frappe.db.sql(
					"""select * from `tabGL Entry`
				where voucher_type='Stock Entry' and voucher_no=%s""",
					mtn.name,
					as_dict=1,
				)
			)

		else:
			stock_value_diff = abs(
				frappe.db.get_value(
					"Stock Ledger Entry",
					{"voucher_type": "Stock Entry", "voucher_no": mtn.name, "warehouse": "Stores - TCP1"},
					"stock_value_difference",
				)
			)

			self.check_gl_entries(
				"Stock Entry",
				mtn.name,
				sorted(
					[
						[source_warehouse_account, 0.0, stock_value_diff],
						[target_warehouse_account, stock_value_diff, 0.0],
					]
				),
			)

		mtn.cancel()

	def test_material_transfer_on_half_cent_moves_no_value(self):
		item_code = make_item(properties={"is_stock_item": 1, "valuation_method": "Moving Average"}).name
		self.assert_half_cent_transfer_moves_no_value(item_code)

	def test_batch_transfer_on_half_cent_moves_no_value(self):
		item_code = make_item(
			properties={
				"is_stock_item": 1,
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_number_series": "HCBT-.#####",
			}
		).name
		self.assert_half_cent_transfer_moves_no_value(item_code)

	def test_serial_transfer_without_serial_wise_valuation_on_half_cent_moves_no_value(self):
		item_code = make_item(
			properties={
				"is_stock_item": 1,
				"valuation_method": "Moving Average",
				"has_serial_no": 1,
				"serial_no_series": "HCSN-.#####",
				"use_serial_no_wise_valuation": 0,
			}
		).name
		self.assert_half_cent_transfer_moves_no_value(item_code)

	def assert_half_cent_transfer_moves_no_value(self, item_code):
		receipt = make_stock_entry(
			item_code=item_code, target="_Test Warehouse - _TC", qty=2, basic_rate=10.005
		)
		bundle = receipt.items[0].serial_and_batch_bundle
		has_batch_no, has_serial_no = frappe.get_cached_value(
			"Item", item_code, ["has_batch_no", "has_serial_no"]
		)

		transfer = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target="_Test Warehouse 1 - _TC",
			qty=1,
			batch_no=get_batch_from_bundle(bundle) if has_batch_no else None,
			serial_no=get_serial_nos_from_bundle(bundle)[:1] if has_serial_no else None,
		)

		outward, inward = self.get_transfer_leg_values(transfer.name)
		self.assertEqual(flt(inward, 2), -flt(outward, 2))

	def test_half_cent_transfer_moves_no_value_after_target_warehouse_repost(self):
		item_code = make_item(properties={"is_stock_item": 1, "valuation_method": "Moving Average"}).name
		make_stock_entry(
			item_code=item_code,
			target="_Test Warehouse - _TC",
			qty=2,
			basic_rate=10.005,
			posting_date=add_days(today(), -10),
		)
		transfer = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target="_Test Warehouse 1 - _TC",
			qty=1,
			posting_date=add_days(today(), -5),
		)
		make_stock_entry(
			item_code=item_code,
			target="_Test Warehouse 1 - _TC",
			qty=1,
			basic_rate=7,
			posting_date=add_days(today(), -8),
		)

		outward, inward = self.get_transfer_leg_values(transfer.name)
		self.assertEqual(flt(inward, 2), -flt(outward, 2))

	def get_transfer_leg_values(self, voucher_no):
		return tuple(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_no": voucher_no, "warehouse": warehouse, "is_cancelled": 0},
				"stock_value_difference",
			)
			for warehouse in ("_Test Warehouse - _TC", "_Test Warehouse 1 - _TC")
		)

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{"auto_create_serial_and_batch_bundle_for_outward": 1, "do_not_use_batchwise_valuation": 0},
	)
	def test_auto_picked_transfer_batches_keep_their_rates(self):
		transfer = self.make_auto_picked_batch_transfer()

		self.assertEqual((transfer.items[0].basic_amount, transfer.items[0].amount), (300, 320))
		self.assertEqual((transfer.total_outgoing_value, transfer.total_incoming_value), (320, 320))
		inward = self.get_inward_transfer_leg(transfer)
		self.assertEqual(inward.incoming_rate, 160)
		self.assertEqual(self.get_batch_rates(inward.serial_and_batch_bundle), [110, 210])

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{"auto_create_serial_and_batch_bundle_for_outward": 1, "do_not_use_batchwise_valuation": 0},
	)
	def test_repost_restores_flattened_transfer_batch_rates(self):
		from hisaabdari.controllers.stock_controller import create_repost_item_valuation_entry

		transfer = self.make_auto_picked_batch_transfer()
		bundle = self.get_inward_transfer_leg(transfer).serial_and_batch_bundle
		frappe.db.set_value(
			"Serial and Batch Entry",
			{"parent": bundle},
			{"incoming_rate": 160, "stock_value_difference": 160},
		)

		create_repost_item_valuation_entry(
			{
				"voucher_type": transfer.doctype,
				"voucher_no": transfer.name,
				"posting_date": transfer.posting_date,
				"posting_time": transfer.posting_time,
				"company": transfer.company,
			}
		)

		self.assertEqual(self.get_batch_rates(bundle), [110, 210])

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{"auto_create_serial_and_batch_bundle_for_outward": 1, "do_not_use_batchwise_valuation": 0},
	)
	def test_additional_cost_follows_auto_picked_transfer_rows(self):
		from hisaabdari.accounts.doctype.cost_center.test_cost_center import create_cost_center

		create_cost_center(
			cost_center_name="_Test APBT Cost Center", company="_Test Company with perpetual inventory"
		)
		cost_centers = ("Main - TCP1", "_Test APBT Cost Center - TCP1")
		transfer = self.make_auto_picked_batch_transfer(
			rates=(100, 300), row_qtys=(1, 1), additional_cost=40, cost_centers=cost_centers
		)

		self.assertEqual([d.amount for d in transfer.items], [110, 330])
		freight = dict(
			frappe.get_all(
				"GL Entry",
				filters={
					"voucher_no": transfer.name,
					"account": transfer.additional_costs[0].expense_account,
					"is_cancelled": 0,
				},
				fields=["cost_center", "credit"],
				as_list=True,
			)
		)
		self.assertEqual(freight, dict(zip(cost_centers, (10, 30), strict=True)))
		inward_values = dict(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": transfer.name, "actual_qty": (">", 0), "is_cancelled": 0},
				fields=["voucher_detail_no", "stock_value_difference"],
				as_list=True,
			)
		)
		self.assertEqual(inward_values, {d.name: d.amount for d in transfer.items})

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{"auto_create_serial_and_batch_bundle_for_outward": 1, "do_not_use_batchwise_valuation": 0},
	)
	def test_transfer_with_picked_and_auto_picked_rows_keeps_batch_qty(self):
		item_code = self.make_batches_at_rates((100, 300), "_Test Warehouse - _TC")
		batches = frappe.get_all("Batch", filters={"item": item_code}, pluck="name", order_by="creation")
		transfer = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target="_Test Warehouse 1 - _TC",
			qty=1,
			batch_no=batches[0],
			use_serial_batch_fields=1,
			do_not_save=True,
		)
		transfer.append("items", {**transfer.items[0].as_dict(no_default_fields=True), "batch_no": None})
		transfer.insert()
		transfer.submit()

		self.assertEqual(
			frappe.db.count(
				"Serial and Batch Bundle",
				{"voucher_no": transfer.name, "type_of_transaction": "Inward", "is_cancelled": 0},
			),
			2,
		)
		self.assertEqual([frappe.db.get_value("Batch", batch, "batch_qty") for batch in batches], [1, 1])

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{"auto_create_serial_and_batch_bundle_for_outward": 1, "do_not_use_batchwise_valuation": 0},
	)
	def test_auto_picked_repack_values_finished_good_at_consumed_cost(self):
		raw_material = self.make_batches_at_rates((100, 200, 600), "_Test Warehouse - _TC")
		finished_good = make_item(properties={"is_stock_item": 1}).name
		repack = make_stock_entry(
			item_code=raw_material,
			source="_Test Warehouse - _TC",
			qty=2,
			purpose="Repack",
			use_serial_batch_fields=1,
			do_not_save=True,
		)
		repack.append(
			"items",
			{
				"item_code": finished_good,
				"t_warehouse": "_Test Warehouse - _TC",
				"qty": 1,
				"conversion_factor": 1,
				"is_finished_item": 1,
			},
		)
		repack.insert()
		repack.submit()
		repack.reload()

		finished_good_row = repack.items[1]
		self.assertEqual(finished_good_row.amount, 300)
		self.assertEqual(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_detail_no": finished_good_row.name, "is_cancelled": 0},
				"stock_value_difference",
			),
			300,
		)

	def make_batches_at_rates(self, rates, warehouse):
		item_code = make_item(
			properties={
				"is_stock_item": 1,
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_number_series": "APBT-.#####",
				"valuation_method": "Moving Average",
			}
		).name
		for rate in rates:
			make_stock_entry(
				item_code=item_code, target=warehouse, qty=1, rate=rate, use_serial_batch_fields=1
			)

		return item_code

	def make_auto_picked_batch_transfer(
		self, rates=(100, 200, 300), row_qtys=(2,), additional_cost=20, cost_centers=()
	):
		item_code = self.make_batches_at_rates(rates, "Stores - TCP1")
		transfer = make_stock_entry(
			item_code=item_code,
			source="Stores - TCP1",
			target="Finished Goods - TCP1",
			qty=row_qtys[0],
			use_serial_batch_fields=1,
			do_not_save=True,
		)
		for qty in row_qtys[1:]:
			transfer.append("items", {**transfer.items[0].as_dict(no_default_fields=True), "qty": qty})
		for row, cost_center in zip(transfer.items, cost_centers, strict=False):
			row.cost_center = cost_center
		transfer.append(
			"additional_costs",
			{
				"expense_account": frappe.get_value("Company", transfer.company, "default_expense_account"),
				"description": "Freight",
				"amount": additional_cost,
			},
		)
		transfer.insert()
		transfer.submit()
		transfer.reload()
		return transfer

	def get_inward_transfer_leg(self, transfer):
		return frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": transfer.name, "actual_qty": (">", 0), "is_cancelled": 0},
			["incoming_rate", "serial_and_batch_bundle"],
			as_dict=True,
		)

	def get_batch_rates(self, bundle):
		return frappe.get_all(
			"Serial and Batch Entry", filters={"parent": bundle}, pluck="incoming_rate", order_by="idx"
		)

	def test_repack_multiple_fg(self):
		"Test `is_finished_item` for one item repacked into two items."
		make_stock_entry(item_code="_Test Item", target="_Test Warehouse - _TC", qty=100, basic_rate=100)

		repack = frappe.copy_doc(self.globalTestRecords["Stock Entry"][3])
		repack.posting_date = nowdate()
		repack.posting_time = nowtime()

		repack.items[0].qty = 100.0
		repack.items[0].transfer_qty = 100.0
		repack.items[1].qty = 50.0

		repack.append(
			"items",
			{
				"conversion_factor": 1.0,
				"cost_center": "_Test Cost Center - _TC",
				"doctype": "Stock Entry Detail",
				"expense_account": "Stock Adjustment - _TC",
				"basic_rate": 150,
				"item_code": "_Test Item 2",
				"parentfield": "items",
				"qty": 50.0,
				"stock_uom": "_Test UOM",
				"t_warehouse": "_Test Warehouse - _TC",
				"transfer_qty": 50.0,
				"uom": "_Test UOM",
			},
		)
		repack.set_stock_entry_type()
		for row in repack.items:
			if row.t_warehouse:
				row.set_basic_rate_manually = 1

		repack.insert()

		self.assertEqual(repack.items[1].is_finished_item, 1)
		self.assertEqual(repack.items[2].is_finished_item, 1)

		repack.items[1].is_finished_item = 0
		repack.items[2].is_finished_item = 0

		# must raise error if 0 fg in repack entry
		self.assertRaises(FinishedGoodError, repack.validate_finished_goods)

		repack.delete()  # teardown

	def test_repack_no_change_in_valuation(self):
		make_stock_entry(item_code="_Test Item", target="_Test Warehouse - _TC", qty=50, basic_rate=100)
		make_stock_entry(
			item_code="_Test Item Home Desktop 100", target="_Test Warehouse - _TC", qty=50, basic_rate=100
		)

		repack = frappe.copy_doc(self.globalTestRecords["Stock Entry"][3])
		repack.posting_date = nowdate()
		repack.posting_time = nowtime()
		repack.set_stock_entry_type()
		repack.insert()
		repack.submit()

		self.check_stock_ledger_entries(
			"Stock Entry",
			repack.name,
			[
				["_Test Item", "_Test Warehouse - _TC", -50.0],
				["_Test Item Home Desktop 100", "_Test Warehouse - _TC", 1],
			],
		)

		gl_entries = frappe.db.sql(
			"""select account, debit, credit
			from `tabGL Entry` where voucher_type='Stock Entry' and voucher_no=%s
			order by account desc""",
			repack.name,
			as_dict=1,
		)
		self.assertFalse(gl_entries)

	def test_repack_with_additional_costs(self):
		company = frappe.db.get_value("Warehouse", "Stores - TCP1", "company")

		make_stock_entry(
			item_code="_Test Item",
			target="Stores - TCP1",
			company=company,
			qty=50,
			basic_rate=100,
			expense_account="Stock Adjustment - TCP1",
		)

		repack = make_stock_entry(company=company, purpose="Repack", do_not_save=True)
		repack.posting_date = nowdate()
		repack.posting_time = nowtime()

		default_expense_account = frappe.get_value("Company", company, "default_expense_account")

		items = get_multiple_items()
		repack.items = []
		for item in items:
			repack.append("items", item)

		repack.set(
			"additional_costs",
			[
				{
					"expense_account": default_expense_account,
					"description": "Actual Operating Cost",
					"amount": 1000,
				},
				{
					"expense_account": default_expense_account,
					"description": "Additional Operating Cost",
					"amount": 200,
				},
			],
		)

		repack.set_stock_entry_type()
		repack.insert()
		repack.submit()

		stock_in_hand_account = get_inventory_account(repack.company, repack.get("items")[1].t_warehouse)
		rm_stock_value_diff = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": "Stock Entry", "voucher_no": repack.name, "item_code": "_Test Item"},
				"stock_value_difference",
			)
		)

		fg_stock_value_diff = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{
					"voucher_type": "Stock Entry",
					"voucher_no": repack.name,
					"item_code": "_Test Item Home Desktop 100",
				},
				"stock_value_difference",
			)
		)

		stock_value_diff = flt(fg_stock_value_diff - rm_stock_value_diff, 2)

		self.assertEqual(stock_value_diff, 1200)

		self.check_gl_entries(
			"Stock Entry",
			repack.name,
			sorted([[stock_in_hand_account, 1200, 0.0], ["Cost of Goods Sold - TCP1", 0.0, 1200.0]]),
		)

	def test_additional_cost_no_rounding_residual_on_stock_adjustment(self):
		company = frappe.db.get_value("Warehouse", "Stores - TCP1", "company")
		warehouse = "Stores - TCP1"
		items = [
			make_item(f"_Test Addl Cost Rounding {x}", {"is_stock_item": 1}).name for x in ("A", "B", "C")
		]

		for item_code in items:
			make_stock_entry(item_code=item_code, target=warehouse, company=company, qty=100, basic_rate=10)

		transfer = make_stock_entry(company=company, purpose="Material Transfer", do_not_save=True)
		transfer.from_warehouse = warehouse
		transfer.to_warehouse = warehouse
		transfer.items = []
		for item_code in items:
			transfer.append(
				"items",
				{
					"item_code": item_code,
					"qty": 100,
					"s_warehouse": warehouse,
					"t_warehouse": warehouse,
					"uom": "Nos",
					"conversion_factor": 1,
				},
			)
		transfer.append(
			"additional_costs",
			{
				"expense_account": "Expenses Included In Valuation - TCP1",
				"description": "freight",
				"amount": 100,
			},
		)
		transfer.insert()
		transfer.submit()

		gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": transfer.name},
			fields=["account", "debit", "credit"],
		)
		gl_map = {}
		for row in gl_entries:
			account = gl_map.setdefault(row.account, frappe._dict(debit=0.0, credit=0.0))
			account.debit += row.debit
			account.credit += row.credit

		self.assertNotIn("Stock Adjustment - TCP1", gl_map)

		stock_in_hand_account = get_inventory_account(company, warehouse)
		self.assertEqual(flt(gl_map[stock_in_hand_account].debit, 2), 99.99)
		self.assertEqual(flt(gl_map["Expenses Included In Valuation - TCP1"].credit, 2), 99.99)

	def check_stock_ledger_entries(self, voucher_type, voucher_no, expected_sle):
		expected_sle.sort(key=lambda x: x[1])

		# check stock ledger entries
		sle = frappe.db.sql(
			"""select item_code, warehouse, actual_qty
			from `tabStock Ledger Entry` where voucher_type = %s
			and voucher_no = %s order by item_code, warehouse, actual_qty""",
			(voucher_type, voucher_no),
			as_list=1,
		)
		self.assertTrue(sle)
		sle.sort(key=lambda x: x[1])

		for i, sle_value in enumerate(sle):
			self.assertEqual(expected_sle[i][0], sle_value[0])
			self.assertEqual(expected_sle[i][1], sle_value[1])
			self.assertEqual(expected_sle[i][2], sle_value[2])

	def check_gl_entries(self, voucher_type, voucher_no, expected_gl_entries):
		expected_gl_entries.sort(key=lambda x: x[0])

		gl_entries = frappe.db.sql(
			"""select account, debit, credit
			from `tabGL Entry` where voucher_type=%s and voucher_no=%s
			order by account asc, debit asc""",
			(voucher_type, voucher_no),
			as_list=1,
		)

		self.assertTrue(gl_entries)
		gl_entries.sort(key=lambda x: x[0])
		for i, gle in enumerate(gl_entries):
			self.assertEqual(expected_gl_entries[i][0], gle[0])
			self.assertEqual(expected_gl_entries[i][1], gle[1])
			self.assertEqual(expected_gl_entries[i][2], gle[2])

	def test_serial_no_not_reqd(self):
		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		se.get("items")[0].serial_no = "ABCD"

		bundle_id = make_serial_batch_bundle(
			frappe._dict(
				{
					"item_code": se.get("items")[0].item_code,
					"warehouse": se.get("items")[0].t_warehouse,
					"company": se.company,
					"qty": 2,
					"voucher_type": "Stock Entry",
					"serial_nos": ["ABCD"],
					"posting_date": se.posting_date,
					"posting_time": se.posting_time,
					"do_not_save": True,
				}
			)
		)

		self.assertRaises(frappe.ValidationError, bundle_id.make_serial_and_batch_bundle)

	def test_serial_no_reqd(self):
		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		se.get("items")[0].item_code = "_Test Serialized Item"
		se.get("items")[0].qty = 2
		se.get("items")[0].transfer_qty = 2

		bundle_id = make_serial_batch_bundle(
			frappe._dict(
				{
					"item_code": se.get("items")[0].item_code,
					"warehouse": se.get("items")[0].t_warehouse,
					"company": se.company,
					"qty": 2,
					"voucher_type": "Stock Entry",
					"posting_date": se.posting_date,
					"posting_time": se.posting_time,
					"do_not_save": True,
				}
			)
		)

		self.assertRaises(frappe.ValidationError, bundle_id.make_serial_and_batch_bundle)

	def test_serial_no_qty_less(self):
		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		se.get("items")[0].item_code = "_Test Serialized Item"
		se.get("items")[0].qty = 2
		se.get("items")[0].serial_no = "ABCD"
		se.get("items")[0].transfer_qty = 2

		bundle_id = make_serial_batch_bundle(
			frappe._dict(
				{
					"item_code": se.get("items")[0].item_code,
					"warehouse": se.get("items")[0].t_warehouse,
					"company": se.company,
					"qty": 2,
					"serial_nos": ["ABCD"],
					"voucher_type": "Stock Entry",
					"posting_date": se.posting_date,
					"posting_time": se.posting_time,
					"do_not_save": True,
				}
			)
		)

		self.assertRaises(frappe.ValidationError, bundle_id.make_serial_and_batch_bundle)

	def test_serial_no_transfer_in(self):
		serial_nos = ["ABCD1", "EFGH1"]
		for serial_no in serial_nos:
			if not frappe.db.exists("Serial No", serial_no):
				doc = frappe.new_doc("Serial No")
				doc.serial_no = serial_no
				doc.item_code = "_Test Serialized Item"
				doc.company = "_Test Company"
				doc.insert(ignore_permissions=True)

		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		se.get("items")[0].item_code = "_Test Serialized Item"
		se.get("items")[0].qty = 2
		se.get("items")[0].transfer_qty = 2
		se.set_stock_entry_type()

		se.get("items")[0].serial_and_batch_bundle = make_serial_batch_bundle(
			frappe._dict(
				{
					"item_code": se.get("items")[0].item_code,
					"warehouse": se.get("items")[0].t_warehouse,
					"company": se.company,
					"qty": 2,
					"voucher_type": "Stock Entry",
					"serial_nos": serial_nos,
					"posting_date": se.posting_date,
					"posting_time": se.posting_time,
					"do_not_submit": True,
				}
			)
		).name

		se.insert()
		se.submit()

		self.assertTrue(frappe.db.get_value("Serial No", "ABCD1", "warehouse"))
		self.assertTrue(frappe.db.get_value("Serial No", "EFGH1", "warehouse"))

		se.cancel()
		self.assertFalse(frappe.db.get_value("Serial No", "ABCD1", "warehouse"))

	def test_serial_by_series(self):
		se = make_serialized_item(self)

		serial_nos = get_serial_nos_from_bundle(se.get("items")[0].serial_and_batch_bundle)

		self.assertTrue(frappe.db.exists("Serial No", serial_nos[0]))
		self.assertTrue(frappe.db.exists("Serial No", serial_nos[1]))

		return se, serial_nos

	def test_serial_move(self):
		se = make_serialized_item(self)
		serial_no = get_serial_nos_from_bundle(se.get("items")[0].serial_and_batch_bundle)[0]
		frappe.flags.use_serial_and_batch_fields = True

		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		se.purpose = "Material Transfer"
		se.get("items")[0].item_code = "_Test Serialized Item With Series"
		se.get("items")[0].qty = 1
		se.get("items")[0].transfer_qty = 1
		se.get("items")[0].serial_no = [serial_no]
		se.get("items")[0].s_warehouse = "_Test Warehouse - _TC"
		se.get("items")[0].t_warehouse = "_Test Warehouse 1 - _TC"
		se.set_stock_entry_type()
		se.insert()
		se.submit()
		self.assertTrue(frappe.db.get_value("Serial No", serial_no, "warehouse"), "_Test Warehouse 1 - _TC")

		se.cancel()
		self.assertTrue(frappe.db.get_value("Serial No", serial_no, "warehouse"), "_Test Warehouse - _TC")
		frappe.flags.use_serial_and_batch_fields = False

	def test_serial_cancel(self):
		se, serial_nos = self.test_serial_by_series()
		se.load_from_db()
		serial_no = get_serial_nos_from_bundle(se.get("items")[0].serial_and_batch_bundle)[0]

		se.cancel()
		self.assertFalse(frappe.db.get_value("Serial No", serial_no, "warehouse"))

	def test_serial_batch_item_stock_entry(self):
		"""
		Behaviour: 1) Submit Stock Entry (Receipt) with Serial & Batched Item
		2) Cancel same Stock Entry
		Expected Result: 1) Batch is created with Reference in Serial No
		2) Batch is deleted and Serial No is Inactive
		"""
		from hisaabdari.stock.doctype.batch.batch import get_batch_qty

		item = frappe.db.exists("Item", {"item_name": "Batched and Serialised Item"})
		if not item:
			item = create_item("Batched and Serialised Item")
			item.has_batch_no = 1
			item.create_new_batch = 1
			item.has_serial_no = 1
			item.batch_number_series = "B-BATCH-.##"
			item.serial_no_series = "S-.####"
			item.save()
		else:
			item = frappe.get_doc("Item", {"item_name": "Batched and Serialised Item"})

		se = make_stock_entry(item_code=item.item_code, target="_Test Warehouse - _TC", qty=1, basic_rate=100)
		batch_no = get_batch_from_bundle(se.items[0].serial_and_batch_bundle)
		serial_no = get_serial_nos_from_bundle(se.items[0].serial_and_batch_bundle)[0]
		batch_qty = get_batch_qty(batch_no, "_Test Warehouse - _TC", item.item_code)

		batch_in_serial_no = frappe.db.get_value("Serial No", serial_no, "batch_no")
		self.assertEqual(batch_in_serial_no, batch_no)

		self.assertEqual(batch_qty, 1)

		se.cancel()

		batch_in_serial_no = frappe.db.get_value("Serial No", serial_no, "batch_no")
		self.assertEqual(frappe.db.get_value("Serial No", serial_no, "warehouse"), None)

	def test_warehouse_company_validation(self):
		frappe.db.get_value("Warehouse", "_Test Warehouse 2 - _TC1", "company")
		frappe.get_doc("User", "test2@example.com").add_roles(
			"Sales User", "Sales Manager", "Stock User", "Stock Manager"
		)
		with self.set_user("test2@example.com"):
			from hisaabdari.stock.utils import InvalidWarehouseCompany

			st1 = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
			st1.get("items")[0].t_warehouse = "_Test Warehouse 2 - _TC1"
			st1.set_stock_entry_type()
			self.assertRaises(InvalidWarehouseCompany, st1.insert)

	def test_warehouse_of_other_company_is_not_priced(self):
		from hisaabdari.stock.utils import InvalidWarehouseCompany

		item_code = make_item("_Test Steel Rod", {"is_stock_item": 1}).name
		make_stock_entry(item_code=item_code, target="_Test Warehouse - _TC", qty=40, basic_rate=123.45)

		def new_material_issue(warehouse):
			entry = make_stock_entry(
				item_code=item_code, source=warehouse, qty=1, company="_Test Company", do_not_save=True
			)
			entry.items[0].basic_rate = 0
			return entry

		own_entry = new_material_issue("_Test Warehouse - _TC")
		own_entry.get_stock_and_rate()
		self.assertEqual(own_entry.items[0].basic_rate, 123.45)
		own_entry.insert()
		self.assertEqual(own_entry.items[0].basic_rate, 123.45)

		other_entry = new_material_issue("_Test Warehouse 2 - _TC1")
		self.assertRaises(InvalidWarehouseCompany, other_entry.get_stock_and_rate)
		self.assertRaises(InvalidWarehouseCompany, other_entry.insert)

	def test_header_warehouse_of_other_company_is_not_priced(self):
		from hisaabdari.stock.utils import InvalidWarehouseCompany

		item_code = make_item("_Test Steel Bar", {"is_stock_item": 1}).name
		make_stock_entry(
			item_code=item_code,
			target="_Test Warehouse 2 - _TC1",
			qty=40,
			basic_rate=123.45,
			company="_Test Company 1",
		)
		make_stock_entry(item_code=item_code, target="_Test Warehouse - _TC", qty=40, basic_rate=67.89)

		def new_material_issue(header_warehouse):
			entry = make_stock_entry(
				item_code=item_code,
				source="_Test Warehouse - _TC",
				qty=1,
				company="_Test Company",
				do_not_save=True,
			)
			entry.from_warehouse = header_warehouse
			entry.items[0].s_warehouse = None
			entry.items[0].basic_rate = 0
			return entry

		own_entry = new_material_issue("_Test Warehouse - _TC")
		own_entry.insert()
		self.assertEqual(own_entry.items[0].s_warehouse, "_Test Warehouse - _TC")
		self.assertEqual(own_entry.items[0].basic_rate, 67.89)

		other_entry = new_material_issue("_Test Warehouse 2 - _TC1")
		other_entry.get_stock_and_rate()
		self.assertNotEqual(other_entry.items[0].basic_rate, 123.45)
		self.assertRaises(InvalidWarehouseCompany, other_entry.insert)
		self.assertNotEqual(other_entry.items[0].basic_rate, 123.45)

	# permission tests
	def test_warehouse_user(self):
		add_user_permission("Warehouse", "_Test Warehouse 1 - _TC", "test@example.com")
		add_user_permission("Warehouse", "_Test Warehouse 2 - _TC1", "test2@example.com")
		add_user_permission("Company", "_Test Company 1", "test2@example.com")
		test_user = frappe.get_doc("User", "test@example.com")
		test_user.add_roles("Sales User", "Sales Manager", "Stock User")
		test_user.remove_roles("Stock Manager", "System Manager")

		frappe.get_doc("User", "test2@example.com").add_roles(
			"Sales User", "Sales Manager", "Stock User", "Stock Manager"
		)

		st1 = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		st1.company = "_Test Company 1"

		with self.set_user("test@example.com"):
			st1.get("items")[0].t_warehouse = "_Test Warehouse 2 - _TC1"
			self.assertRaises(frappe.PermissionError, st1.insert)

		test_user.add_roles("System Manager")

		with self.set_user("test2@example.com"):
			st1 = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
			st1.company = "_Test Company 1"
			st1.get("items")[0].t_warehouse = "_Test Warehouse 2 - _TC1"
			st1.get("items")[0].expense_account = "Stock Adjustment - _TC1"
			st1.get("items")[0].cost_center = "Main - _TC1"
			st1.set_stock_entry_type()
			st1.insert()
			st1.submit()
			st1.cancel()

		remove_user_permission("Warehouse", "_Test Warehouse 1 - _TC", "test@example.com")
		remove_user_permission("Warehouse", "_Test Warehouse 2 - _TC1", "test2@example.com")
		remove_user_permission("Company", "_Test Company 1", "test2@example.com")

	def test_freeze_stocks(self):
		frappe.db.set_single_value("Stock Settings", "stock_auth_role", "")

		# test freeze_stocks_upto
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", add_days(nowdate(), 5))
		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0]).insert()
		self.assertRaises(StockFreezeError, se.submit)

		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "")

		# test freeze_stocks_upto_days
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto_days", -1)
		se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])
		se.set_posting_time = 1
		se.posting_date = nowdate()
		se.set_stock_entry_type()
		se.insert()
		self.assertRaises(StockFreezeError, se.submit)
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto_days", 0)

	def test_nagative_stock_for_batch(self):
		item = make_item(
			"_Test Batch Negative Item",
			{
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_number_series": "B-BATCH-.##",
				"is_stock_item": 1,
			},
		)

		receipt = make_stock_entry(
			item_code=item.name, target="_Test Warehouse - _TC", qty=50, basic_rate=100
		)
		batch_no = get_batch_from_bundle(receipt.items[0].serial_and_batch_bundle)

		ste = frappe.new_doc("Stock Entry")
		ste.purpose = "Material Issue"
		ste.company = "_Test Company"
		for qty in [50, 20, 30]:
			ste.append(
				"items",
				{
					"item_code": item.name,
					"s_warehouse": "_Test Warehouse - _TC",
					"use_serial_batch_fields": 1,
					"batch_no": batch_no,
					"qty": qty,
					"uom": item.stock_uom,
					"stock_uom": item.stock_uom,
					"conversion_factor": 1,
					"transfer_qty": qty,
				},
			)

		ste.set_stock_entry_type()
		ste.insert()
		make_stock_entry(item_code=item.name, target="_Test Warehouse - _TC", qty=50, basic_rate=100)

		self.assertRaises(frappe.ValidationError, ste.submit)

	def test_valuation_rate_lookup_without_voucher_no(self):
		from hisaabdari.stock.stock_ledger import get_valuation_rate

		item = make_item(properties={"is_stock_item": 1}).name
		make_stock_entry(item_code=item, target="_Test Warehouse - _TC", qty=5, basic_rate=77)

		# unsaved documents pass no voucher_no; the lookup must still find the last SLE
		rate = get_valuation_rate(
			item, "_Test Warehouse - _TC", "Stock Entry", None, raise_error_if_no_rate=False
		)
		self.assertEqual(rate, 77)

	def test_customer_provided_parts_se(self):
		create_item("CUST-0987", is_customer_provided_item=1, customer="_Test Customer", is_purchase_item=0)
		se = make_stock_entry(
			item_code="CUST-0987", purpose="Material Receipt", qty=4, to_warehouse="_Test Warehouse - _TC"
		)
		self.assertEqual(se.get("items")[0].allow_zero_valuation_rate, 1)
		self.assertEqual(se.get("items")[0].amount, 0)

	def test_zero_incoming_rate(self):
		"""Make sure incoming rate of 0 is allowed while consuming.

		qty  | rate | valuation rate
		 1   | 100  | 100
		 1   | 0    | 50
		-1   | 100  | 0
		-1   | 0  <--- assert this
		"""
		item_code = "_TestZeroVal"
		warehouse = "_Test Warehouse - _TC"
		create_item("_TestZeroVal")
		_receipt = make_stock_entry(item_code=item_code, qty=1, to_warehouse=warehouse, rate=100)
		receipt2 = make_stock_entry(
			item_code=item_code, qty=1, to_warehouse=warehouse, rate=0, do_not_save=True
		)
		receipt2.items[0].allow_zero_valuation_rate = 1
		receipt2.save()
		receipt2.submit()

		issue = make_stock_entry(item_code=item_code, qty=1, from_warehouse=warehouse)

		value_diff = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": issue.name, "voucher_type": "Stock Entry"},
			"stock_value_difference",
		)
		self.assertEqual(value_diff, -100)

		issue2 = make_stock_entry(item_code=item_code, qty=1, from_warehouse=warehouse)
		value_diff = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": issue2.name, "voucher_type": "Stock Entry"},
			"stock_value_difference",
		)
		self.assertEqual(value_diff, 0)

	def test_gle_for_opening_stock_entry(self):
		mr = make_stock_entry(
			item_code="_Test Item",
			target="Stores - TCP1",
			company="_Test Company with perpetual inventory",
			qty=50,
			basic_rate=100,
			expense_account="Stock Adjustment - TCP1",
			is_opening="Yes",
			do_not_save=True,
		)

		self.assertRaises(OpeningEntryAccountError, mr.save)

		mr.items[0].expense_account = "Temporary Opening - TCP1"

		mr.save()
		mr.submit()

		is_opening = frappe.db.get_value(
			"GL Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": mr.name},
			fieldname="is_opening",
		)
		self.assertEqual(is_opening, "Yes")

	def test_total_basic_amount_zero(self):
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Material Receipt",
				"stock_entry_type": "Material Receipt",
				"posting_date": nowdate(),
				"company": "_Test Company with perpetual inventory",
				"items": [
					{
						"item_code": "_Test Item",
						"description": "_Test Item",
						"qty": 1,
						"basic_rate": 0,
						"uom": "Nos",
						"t_warehouse": "Stores - TCP1",
						"allow_zero_valuation_rate": 1,
						"cost_center": "Main - TCP1",
					},
					{
						"item_code": "_Test Item",
						"description": "_Test Item",
						"qty": 2,
						"basic_rate": 0,
						"uom": "Nos",
						"t_warehouse": "Stores - TCP1",
						"allow_zero_valuation_rate": 1,
						"cost_center": "Main - TCP1",
					},
				],
				"additional_costs": [
					{
						"expense_account": "Miscellaneous Expenses - TCP1",
						"amount": 100,
						"description": "miscellanous",
					}
				],
			}
		)
		se.insert()
		se.submit()

		self.assertEqual([33.33, 66.67], [flt(d.additional_cost, 2) for d in se.items])

		self.check_gl_entries(
			"Stock Entry",
			se.name,
			sorted([["Stock In Hand - TCP1", 100.0, 0.0], ["Miscellaneous Expenses - TCP1", 0.0, 100.0]]),
		)

	def test_conversion_factor_change(self):
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		repack_entry = frappe.copy_doc(self.globalTestRecords["Stock Entry"][3])
		repack_entry.posting_date = nowdate()
		repack_entry.posting_time = nowtime()
		repack_entry.set_stock_entry_type()
		repack_entry.insert()

		# check current uom and conversion factor
		self.assertTrue(repack_entry.items[0].uom, "_Test UOM")
		self.assertTrue(repack_entry.items[0].conversion_factor, 1)

		# change conversion factor
		repack_entry.items[0].uom = "_Test UOM 1"
		repack_entry.items[0].stock_uom = "_Test UOM 1"
		repack_entry.items[0].conversion_factor = 2
		repack_entry.save()
		repack_entry.submit()

		self.assertEqual(repack_entry.items[0].conversion_factor, 2)
		self.assertEqual(repack_entry.items[0].uom, "_Test UOM 1")
		self.assertEqual(repack_entry.items[0].qty, 50)
		self.assertEqual(repack_entry.items[0].transfer_qty, 100)

		frappe.db.set_default("allow_negative_stock", 0)

	def test_additional_cost_distribution_zero_valued_items(self):
		se = frappe.get_doc(
			doctype="Stock Entry",
			purpose="Material Receipt",
			additional_costs=[frappe._dict(base_amount=100)],
			items=[
				frappe._dict(item_code="RECEIVED_1", basic_amount=0, transfer_qty=20, t_warehouse="X"),
				frappe._dict(item_code="RECEIVED_2", basic_amount=0, transfer_qty=30, t_warehouse="X"),
			],
		)

		se.distribute_additional_costs()

		distributed_costs = [d.additional_cost for d in se.items]
		self.assertEqual([40.0, 60.0], distributed_costs)

	def test_additional_cost_gl_matches_valuation_split(self):
		company = "_Test Company with perpetual inventory"
		cost_center = "_Test Additional Cost CC - TCP1"
		if not frappe.db.exists("Cost Center", cost_center):
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": "_Test Additional Cost CC",
					"company": company,
					"is_group": 0,
					"parent_cost_center": "_Test Company with perpetual inventory - TCP1",
				}
			).insert()

		uoms = [{"uom": "Nos", "conversion_factor": 1}, {"uom": "Box", "conversion_factor": 2}]
		item_a = make_item("_Test Addl Cost CF A", {"is_stock_item": 1, "uoms": uoms}).name
		uoms[1]["conversion_factor"] = 3
		item_b = make_item("_Test Addl Cost CF B", {"is_stock_item": 1, "uoms": uoms}).name

		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Material Receipt",
				"stock_entry_type": "Material Receipt",
				"posting_date": nowdate(),
				"company": company,
				"items": [
					{
						"item_code": item_a,
						"qty": 1,
						"basic_rate": 0,
						"uom": "Box",
						"conversion_factor": 2,
						"t_warehouse": "Stores - TCP1",
						"allow_zero_valuation_rate": 1,
						"cost_center": "Main - TCP1",
					},
					{
						"item_code": item_b,
						"qty": 1,
						"basic_rate": 0,
						"uom": "Box",
						"conversion_factor": 3,
						"t_warehouse": "Stores - TCP1",
						"allow_zero_valuation_rate": 1,
						"cost_center": cost_center,
					},
				],
				"additional_costs": [
					{
						"expense_account": "Miscellaneous Expenses - TCP1",
						"amount": 100,
						"description": "misc",
					}
				],
			}
		)
		se.insert()
		se.submit()

		self.assertEqual([40.0, 60.0], [flt(d.additional_cost, 2) for d in se.items])

		expense_by_cost_center = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": se.name, "account": "Miscellaneous Expenses - TCP1"},
			fields=["cost_center", "credit"],
		)
		self.assertEqual(
			{"Main - TCP1": 40.0, cost_center: 60.0},
			{d.cost_center: d.credit for d in expense_by_cost_center},
		)

	def test_additional_cost_distribution_non_manufacture(self):
		se = frappe.get_doc(
			doctype="Stock Entry",
			purpose="Material Receipt",
			additional_costs=[frappe._dict(base_amount=100)],
			items=[
				frappe._dict(item_code="RECEIVED_1", basic_amount=20, t_warehouse="X"),
				frappe._dict(item_code="RECEIVED_2", basic_amount=30, t_warehouse="X"),
			],
		)

		se.distribute_additional_costs()

		distributed_costs = [d.additional_cost for d in se.items]
		self.assertEqual([40.0, 60.0], distributed_costs)

	@ERPNextTestSuite.change_settings(
		"Stock Settings",
		{
			"auto_create_serial_and_batch_bundle_for_outward": 1,
			"do_not_use_batchwise_valuation": 0,
			"allow_negative_stock": 0,
		},
	)
	def test_auto_picked_batches_differ_across_rows(self):
		item_code = make_item(
			properties={
				"is_stock_item": 1,
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_number_series": "PABR-.#####",
			}
		).name
		for _ in range(3):
			make_stock_entry(item_code=item_code, target="_Test Warehouse - _TC", qty=1, rate=100)

		transfer = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target="_Test Warehouse 1 - _TC",
			qty=1,
			do_not_save=True,
		)
		for _ in range(2):
			transfer.append("items", transfer.items[0].as_dict(no_default_fields=True))
		for row in transfer.items:
			row.use_serial_batch_fields = 0
		transfer.insert()
		transfer.submit()

		picked = [get_batch_from_bundle(row.serial_and_batch_bundle) for row in transfer.items]
		self.assertEqual(len(set(picked)), 3)

	@ERPNextTestSuite.change_settings("Stock Settings", {"allow_negative_stock": 0})
	def test_future_negative_sle(self):
		# Initialize item, batch, warehouse, opening qty
		item_code = "_Test Future Neg Item"
		batch_no = "_Test Future Neg Batch"
		warehouses = ["_Test Future Neg Warehouse Source", "_Test Future Neg Warehouse Destination"]
		warehouse_names = initialize_records_for_future_negative_sle_test(
			item_code, batch_no, warehouses, opening_qty=2, posting_date="2021-07-01"
		)

		# Executing an illegal sequence should raise an error
		sequence_of_entries = [
			dict(
				item_code=item_code,
				qty=2,
				from_warehouse=warehouse_names[0],
				to_warehouse=warehouse_names[1],
				batch_no=batch_no,
				posting_date="2021-07-03",
				purpose="Material Transfer",
			),
			dict(
				item_code=item_code,
				qty=2,
				from_warehouse=warehouse_names[1],
				to_warehouse=warehouse_names[0],
				batch_no=batch_no,
				posting_date="2021-07-04",
				purpose="Material Transfer",
			),
			dict(
				item_code=item_code,
				qty=2,
				from_warehouse=warehouse_names[0],
				to_warehouse=warehouse_names[1],
				batch_no=batch_no,
				posting_date="2021-07-02",  # Illegal SE
				purpose="Material Transfer",
			),
		]

		self.assertRaises(NegativeStockError, create_stock_entries, sequence_of_entries)

	@ERPNextTestSuite.change_settings("Stock Settings", {"allow_negative_stock": 0})
	def test_future_negative_sle_batch(self):
		from hisaabdari.stock.doctype.batch.test_batch import TestBatch

		# Initialize item, batch, warehouse, opening qty
		item_code = "_Test MultiBatch Item"
		TestBatch.make_batch_item(item_code)

		batch_nos = []  # store generate batches
		warehouse = "_Test Warehouse - _TC"

		se1 = make_stock_entry(
			item_code=item_code,
			qty=2,
			to_warehouse=warehouse,
			posting_date="2021-09-01",
			purpose="Material Receipt",
		)
		batch_nos.append(get_batch_from_bundle(se1.items[0].serial_and_batch_bundle))
		se2 = make_stock_entry(
			item_code=item_code,
			qty=2,
			to_warehouse=warehouse,
			posting_date="2021-09-03",
			purpose="Material Receipt",
		)
		batch_nos.append(get_batch_from_bundle(se2.items[0].serial_and_batch_bundle))

		with self.assertRaises(frappe.ValidationError):
			make_stock_entry(
				item_code=item_code,
				qty=1,
				from_warehouse=warehouse,
				batch_no=batch_nos[1],
				posting_date="2021-09-02",  # backdated consumption of 2nd batch
				purpose="Material Issue",
			)

	def test_multi_batch_value_diff(self):
		"""Test value difference on stock entry in case of multi-batch.
		| Stock entry | batch | qty | rate | value diff on SE             |
		| ---         | ---   | --- | ---  | ---                          |
		| receipt     | A     | 1   | 10   | 30                           |
		| receipt     | B     | 1   | 20   |                              |
		| issue       | A     | -1  | 10   | -30 (to assert after submit) |
		| issue       | B     | -1  | 20   |                              |
		"""
		from hisaabdari.stock.doctype.batch.test_batch import TestBatch

		item_code = "_TestMultibatchFifo"
		TestBatch.make_batch_item(item_code)
		warehouse = "_Test Warehouse - _TC"
		receipt = make_stock_entry(
			item_code=item_code,
			qty=1,
			rate=10,
			to_warehouse=warehouse,
			purpose="Material Receipt",
			do_not_save=True,
		)
		receipt.append(
			"items", frappe.copy_doc(receipt.items[0], ignore_no_copy=False).update({"basic_rate": 20})
		)
		receipt.save()
		receipt.submit()
		receipt.load_from_db()

		batches = frappe._dict(
			{get_batch_from_bundle(row.serial_and_batch_bundle): row.qty for row in receipt.items}
		)

		self.assertEqual(receipt.value_difference, 30)

		issue = make_stock_entry(
			item_code=item_code,
			qty=2,
			from_warehouse=warehouse,
			purpose="Material Issue",
			do_not_save=True,
			batches=batches,
		)

		issue.save()
		issue.submit()
		issue.reload()  # reload because reposting current voucher updates rate
		self.assertEqual(issue.value_difference, -30)

	def test_transfer_qty_validation(self):
		se = make_stock_entry(item_code="_Test Item", do_not_save=True, qty=0.001, rate=100)
		se.items[0].uom = "Kg"
		se.items[0].conversion_factor = 0.002

		self.assertRaises(frappe.ValidationError, se.save)

	def test_mapped_stock_entry(self):
		"Check if rate and stock details are populated in mapped SE given warehouse."
		from hisaabdari.stock.doctype.purchase_receipt.purchase_receipt import make_stock_entry
		from hisaabdari.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt

		item_code = "_TestMappedItem"
		create_item(item_code, is_stock_item=True)

		pr = make_purchase_receipt(
			item_code=item_code, qty=2, rate=100, company="_Test Company", warehouse="Stores - _TC"
		)

		mapped_se = make_stock_entry(pr.name)

		self.assertEqual(mapped_se.items[0].s_warehouse, "Stores - _TC")
		self.assertEqual(mapped_se.items[0].actual_qty, 2)
		self.assertEqual(mapped_se.items[0].basic_rate, 100)
		self.assertEqual(mapped_se.items[0].basic_amount, 200)

	def test_stock_entry_item_details(self):
		item = make_item()

		se = make_stock_entry(
			item_code=item.name, qty=1, to_warehouse="_Test Warehouse - _TC", do_not_submit=True
		)

		self.assertEqual(se.items[0].item_name, item.item_name)
		se.items[0].item_name = "wat"
		se.items[0].stock_uom = "Kg"
		se.save()

		self.assertEqual(se.items[0].item_name, item.item_name)
		self.assertEqual(se.items[0].stock_uom, item.stock_uom)

	@ERPNextTestSuite.change_settings("Stock Reposting Settings", {"item_based_reposting": 0})
	def test_reposting_for_depedent_warehouse(self):
		from hisaabdari.stock.doctype.repost_item_valuation.repost_item_valuation import repost_sl_entries
		from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

		# Inward at WH1 warehouse (Component)
		# 1st Repack (Component (WH1) - Subcomponent (WH2))
		# 2nd Repack (Subcomponent (WH2) - FG Item (WH3))
		# Material Transfer of FG Item -> WH 3 -> WH2 -> Wh1 (Two transfer entries)
		# Backdated transction which should update valuation rate in repack as well trasfer entries

		for item_code in ["FG Item 1", "Sub Component 1", "Component 1"]:
			create_item(item_code)

		for warehouse in ["WH 1", "WH 2", "WH 3"]:
			create_warehouse(warehouse)

		make_stock_entry(
			item_code="Component 1",
			rate=100,
			purpose="Material Receipt",
			qty=10,
			to_warehouse="WH 1 - _TC",
			posting_date=add_days(nowdate(), -10),
		)

		repack1 = make_stock_entry(
			item_code="Component 1",
			purpose="Repack",
			do_not_save=True,
			qty=10,
			from_warehouse="WH 1 - _TC",
			posting_date=add_days(nowdate(), -9),
		)

		repack1.append(
			"items",
			{
				"item_code": "Sub Component 1",
				"qty": 10,
				"t_warehouse": "WH 2 - _TC",
				"transfer_qty": 10,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1.0,
			},
		)

		repack1.save()
		repack1.submit()

		self.assertEqual(repack1.items[1].basic_rate, 100)
		self.assertEqual(repack1.items[1].amount, 1000)

		repack2 = make_stock_entry(
			item_code="Sub Component 1",
			purpose="Repack",
			do_not_save=True,
			qty=10,
			from_warehouse="WH 2 - _TC",
			posting_date=add_days(nowdate(), -8),
		)

		repack2.append(
			"items",
			{
				"item_code": "FG Item 1",
				"qty": 10,
				"t_warehouse": "WH 3 - _TC",
				"transfer_qty": 10,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1.0,
			},
		)

		repack2.save()
		repack2.submit()

		self.assertEqual(repack2.items[1].basic_rate, 100)
		self.assertEqual(repack2.items[1].amount, 1000)

		transfer1 = make_stock_entry(
			item_code="FG Item 1",
			purpose="Material Transfer",
			qty=10,
			from_warehouse="WH 3 - _TC",
			to_warehouse="WH 2 - _TC",
			posting_date=add_days(nowdate(), -7),
		)

		self.assertEqual(transfer1.items[0].basic_rate, 100)
		self.assertEqual(transfer1.items[0].amount, 1000)

		transfer2 = make_stock_entry(
			item_code="FG Item 1",
			purpose="Material Transfer",
			qty=10,
			from_warehouse="WH 2 - _TC",
			to_warehouse="WH 1 - _TC",
			posting_date=add_days(nowdate(), -6),
		)

		self.assertEqual(transfer2.items[0].basic_rate, 100)
		self.assertEqual(transfer2.items[0].amount, 1000)

		# Backdated transaction
		receipt2 = make_stock_entry(
			item_code="Component 1",
			rate=200,
			purpose="Material Receipt",
			qty=10,
			to_warehouse="WH 1 - _TC",
			posting_date=add_days(nowdate(), -15),
		)

		self.assertEqual(receipt2.items[0].basic_rate, 200)
		self.assertEqual(receipt2.items[0].amount, 2000)

		repost_name = frappe.db.get_value(
			"Repost Item Valuation", {"voucher_no": receipt2.name, "docstatus": 1}, "name"
		)

		doc = frappe.get_doc("Repost Item Valuation", repost_name)
		repost_sl_entries(doc)

		for obj in [repack1, repack2, transfer1, transfer2]:
			obj.load_from_db()

			index = 1 if obj.purpose == "Repack" else 0
			self.assertEqual(obj.items[index].basic_rate, 200)
			self.assertEqual(obj.items[index].basic_amount, 2000)

	def test_batch_expiry(self):
		from hisaabdari.controllers.stock_controller import BatchExpiredError
		from hisaabdari.stock.doctype.batch.test_batch import make_new_batch

		item_code = "Test Batch Expiry Test Item - 001"
		item_doc = create_item(item_code=item_code, is_stock_item=1, valuation_rate=10)

		item_doc.has_batch_no = 1
		item_doc.save()

		batch = make_new_batch(
			batch_id=frappe.generate_hash("", 5), item_code=item_doc.name, expiry_date=add_days(today(), -1)
		)

		se = make_stock_entry(
			item_code=item_code,
			purpose="Material Receipt",
			qty=4,
			to_warehouse="_Test Warehouse - _TC",
			batch_no=batch.name,
			use_serial_batch_fields=1,
			do_not_save=True,
		)

		self.assertRaises(BatchExpiredError, se.save)

	def test_negative_stock_reco(self):
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 0)

		item_code = "Test Negative Item - 001"
		create_item(item_code=item_code, is_stock_item=1, valuation_rate=10)

		make_stock_entry(
			item_code=item_code,
			posting_date=add_days(today(), -3),
			posting_time="00:00:00",
			target="_Test Warehouse - _TC",
			qty=10,
			to_warehouse="_Test Warehouse - _TC",
		)

		make_stock_entry(
			item_code=item_code,
			posting_date=today(),
			posting_time="00:00:00",
			source="_Test Warehouse - _TC",
			qty=8,
			from_warehouse="_Test Warehouse - _TC",
		)

		sr_doc = create_stock_reconciliation(
			purpose="Stock Reconciliation",
			posting_date=add_days(today(), -3),
			posting_time="00:00:00",
			item_code=item_code,
			warehouse="_Test Warehouse - _TC",
			valuation_rate=10,
			qty=7,
			do_not_submit=True,
		)

		self.assertRaises(frappe.ValidationError, sr_doc.submit)

	def test_negative_batch(self):
		item_code = "Test Negative Batch Item - 001"
		make_item(
			item_code,
			{"has_batch_no": 1, "create_new_batch": 1, "batch_naming_series": "Test-BCH-NNS.#####"},
		)

		se1 = make_stock_entry(
			item_code=item_code,
			purpose="Material Receipt",
			qty=100,
			target="_Test Warehouse - _TC",
		)

		se1.reload()

		batch_no = get_batch_from_bundle(se1.items[0].serial_and_batch_bundle)

		se2 = make_stock_entry(
			item_code=item_code,
			purpose="Material Issue",
			batch_no=batch_no,
			qty=10,
			source="_Test Warehouse - _TC",
		)

		se2.reload()

		se3 = make_stock_entry(
			item_code=item_code,
			purpose="Material Receipt",
			qty=100,
			target="_Test Warehouse - _TC",
		)

		se3.reload()

		self.assertRaises(frappe.ValidationError, se1.cancel)

	def test_use_serial_and_batch_fields(self):
		item = make_item(
			"Test Use Serial and Batch Item SN Item",
			{"has_serial_no": 1, "is_stock_item": 1},
		)

		serial_nos = [
			"Test Use Serial and Batch Item SN Item - SN 001",
			"Test Use Serial and Batch Item SN Item - SN 002",
		]

		se = make_stock_entry(
			item_code=item.name,
			qty=2,
			to_warehouse="_Test Warehouse - _TC",
			use_serial_batch_fields=1,
			serial_no="\n".join(serial_nos),
		)

		self.assertTrue(se.items[0].use_serial_batch_fields)
		self.assertTrue(se.items[0].serial_no)
		self.assertTrue(se.items[0].serial_and_batch_bundle)

		for serial_no in serial_nos:
			self.assertTrue(frappe.db.exists("Serial No", serial_no))
			self.assertEqual(frappe.db.get_value("Serial No", serial_no, "status"), "Active")

		se1 = make_stock_entry(
			item_code=item.name,
			qty=2,
			from_warehouse="_Test Warehouse - _TC",
			use_serial_batch_fields=1,
			serial_no="\n".join(serial_nos),
		)

		se1.reload()

		self.assertTrue(se1.items[0].use_serial_batch_fields)
		self.assertTrue(se1.items[0].serial_no)
		self.assertTrue(se1.items[0].serial_and_batch_bundle)

		for serial_no in serial_nos:
			self.assertTrue(frappe.db.exists("Serial No", serial_no))
			self.assertEqual(frappe.db.get_value("Serial No", serial_no, "status"), "Consumed")

	def test_serial_batch_bundle_type_of_transaction(self):
		item = make_item(
			"Test Use Serial and Batch Item SN Item",
			{
				"has_batch_no": 1,
				"is_stock_item": 1,
				"create_new_batch": 1,
				"batch_naming_series": "Test-SBBTYT-NNS.#####",
			},
		).name

		se = make_stock_entry(
			item_code=item,
			qty=2,
			target="_Test Warehouse - _TC",
			use_serial_batch_fields=1,
		)

		batch_no = get_batch_from_bundle(se.items[0].serial_and_batch_bundle)

		se = make_stock_entry(
			item_code=item,
			qty=2,
			source="_Test Warehouse - _TC",
			target="Stores - _TC",
			use_serial_batch_fields=0,
			batch_no=batch_no,
			do_not_submit=True,
		)

		se.reload()
		sbb = se.items[0].serial_and_batch_bundle
		frappe.db.set_value("Serial and Batch Bundle", sbb, "type_of_transaction", "Inward")
		self.assertRaises(frappe.ValidationError, se.submit)

	def test_stock_entry_for_same_posting_date_and_time(self):
		warehouse = "_Test Warehouse - _TC"
		item_code = "Test Stock Entry For Same Posting Datetime 1"
		make_item(item_code, {"is_stock_item": 1})
		posting_date = nowdate()
		posting_time = nowtime()

		for index in range(25):
			se = make_stock_entry(
				item_code=item_code,
				qty=1,
				to_warehouse=warehouse,
				posting_date=posting_date,
				posting_time=posting_time,
				do_not_submit=True,
				purpose="Material Receipt",
				basic_rate=100,
			)

			se.append(
				"items",
				{
					"item_code": item_code,
					"item_name": se.items[0].item_name,
					"description": se.items[0].description,
					"t_warehouse": se.items[0].t_warehouse,
					"basic_rate": 100,
					"qty": 1,
					"stock_qty": 1,
					"conversion_factor": 1,
					"expense_account": se.items[0].expense_account,
					"cost_center": se.items[0].cost_center,
					"uom": se.items[0].uom,
					"stock_uom": se.items[0].stock_uom,
				},
			)

			se.remarks = f"The current number is {cstr(index)}"

			se.submit()

		sles = frappe.get_all(
			"Stock Ledger Entry",
			fields=[
				"posting_date",
				"posting_time",
				"actual_qty",
				"qty_after_transaction",
				"incoming_rate",
				"stock_value_difference",
				"stock_value",
			],
			filters={"item_code": item_code, "warehouse": warehouse},
			order_by="creation",
		)

		self.assertEqual(len(sles), 50)
		i = 0
		for sle in sles:
			i += 1
			self.assertEqual(getdate(sle.posting_date), getdate(posting_date))
			self.assertEqual(get_time(sle.posting_time), get_time(posting_time))
			self.assertEqual(sle.actual_qty, 1)
			self.assertEqual(sle.qty_after_transaction, i)
			self.assertEqual(sle.incoming_rate, 100)
			self.assertEqual(sle.stock_value_difference, 100)
			self.assertEqual(sle.stock_value, 100 * i)

	def test_stock_entry_amount(self):
		warehouse = "_Test Warehouse - _TC"
		rm_item_code = "Test Stock Entry Amount 1"
		make_item(rm_item_code, {"is_stock_item": 1})

		fg_item_code = "Test Repack Stock Entry Amount 1"
		make_item(fg_item_code, {"is_stock_item": 1})

		make_stock_entry(
			item_code=rm_item_code,
			qty=1,
			to_warehouse=warehouse,
			basic_rate=200,
			posting_date=nowdate(),
		)

		se = make_stock_entry(
			item_code=rm_item_code,
			qty=1,
			purpose="Repack",
			basic_rate=100,
			do_not_save=True,
		)

		se.items[0].s_warehouse = warehouse
		se.append(
			"items",
			{
				"item_code": fg_item_code,
				"qty": 1,
				"t_warehouse": warehouse,
				"uom": "Nos",
				"conversion_factor": 1.0,
			},
		)
		se.set_stock_entry_type()
		se.submit()

		self.assertEqual(se.items[0].amount, 200)
		self.assertEqual(se.items[0].basic_amount, 200)

		make_stock_entry(
			item_code=rm_item_code,
			qty=1,
			to_warehouse=warehouse,
			basic_rate=300,
			posting_date=add_days(nowdate(), -1),
		)

		se.reload()
		self.assertEqual(se.items[0].amount, 300)
		self.assertEqual(se.items[0].basic_amount, 300)

	def test_use_batch_wise_valuation_for_moving_average_item(self):
		item_code = "_Test Use Batch Wise MA Valuation Item"

		make_item(
			item_code,
			{
				"is_stock_item": 1,
				"valuation_method": "Moving Average",
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_naming_series": "Test-UBWVMAV-T-NNS.#####",
			},
		)

		frappe.db.set_single_value("Stock Settings", "do_not_use_batchwise_valuation", 0)

		batches = []
		se = make_stock_entry(
			item_code=item_code,
			qty=10,
			to_warehouse="_Test Warehouse - _TC",
			basic_rate=100,
			posting_date=add_days(nowdate(), -2),
		)

		batches.append(get_batch_from_bundle(se.items[0].serial_and_batch_bundle))

		se = make_stock_entry(
			item_code=item_code,
			qty=10,
			to_warehouse="_Test Warehouse - _TC",
			basic_rate=300,
			posting_date=add_days(nowdate(), -1),
		)

		batches.append(get_batch_from_bundle(se.items[0].serial_and_batch_bundle))

		se = make_stock_entry(
			item_code=item_code,
			qty=5,
			from_warehouse="_Test Warehouse - _TC",
			batch_no=batches[1],
			posting_date=nowdate(),
		)

		self.assertEqual(se.items[0].basic_rate, 300)

	def test_periodic_accounting_entries(self):
		item_code = "_Test Periodic Accounting Item"
		make_item(item_code, {"is_stock_item": 1})

		company = "_Test Periodic Accounting Company"

		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": company,
				"abbr": "_TPC",
				"default_currency": "INR",
				"enable_perpetual_inventory": 0,
				"country": "India",
			}
		).insert(ignore_permissions=True)

		warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")

		make_stock_entry(
			item_code=item_code,
			qty=10,
			to_warehouse=warehouse,
			basic_rate=100,
			posting_date=add_days(nowdate(), -2),
		)

		jv = frappe.new_doc("Journal Entry")
		jv.voucher_type = "Periodic Accounting Entry"
		jv.posting_date = add_days(nowdate(), -1)
		jv.posting_time = nowtime()
		jv.company = company
		jv.for_all_stock_asset_accounts = 1
		jv.periodic_entry_difference_account = "Stock Adjustment - _TPC"
		jv.get_balance_for_periodic_accounting()
		jv.save()
		jv.submit()

		self.assertEqual(len(jv.accounts), 2)
		self.assertEqual(jv.accounts[0].debit_in_account_currency, 1000)
		self.assertEqual(jv.accounts[1].credit_in_account_currency, 1000)
		self.assertEqual(jv.accounts[0].account, "Stock In Hand - _TPC")
		self.assertEqual(jv.accounts[1].account, "Stock Adjustment - _TPC")

		make_stock_entry(
			item_code=item_code,
			qty=5,
			from_warehouse=warehouse,
			company=company,
			posting_date=nowdate(),
			posting_time=nowtime(),
		)

		jv = frappe.new_doc("Journal Entry")
		jv.voucher_type = "Periodic Accounting Entry"
		jv.posting_date = nowdate()
		jv.posting_time = nowtime()
		jv.company = company
		jv.for_all_stock_asset_accounts = 1
		jv.periodic_entry_difference_account = "Stock Adjustment - _TPC"
		jv.get_balance_for_periodic_accounting()
		jv.save()
		jv.submit()

		self.assertEqual(len(jv.accounts), 2)
		self.assertEqual(jv.accounts[0].credit_in_account_currency, 500)
		self.assertEqual(jv.accounts[1].debit_in_account_currency, 500)
		self.assertEqual(jv.accounts[0].account, "Stock In Hand - _TPC")
		self.assertEqual(jv.accounts[1].account, "Stock Adjustment - _TPC")

	def test_batch_item_additional_cost_for_material_transfer_entry(self):
		item_code = "_Test Batch Item Additional Cost MTE"
		make_item(
			item_code,
			{
				"is_stock_item": 1,
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_naming_series": "BT-MTE.#####",
			},
		)

		se = make_stock_entry(
			item_code=item_code,
			target="_Test Warehouse - _TC",
			qty=2,
			basic_rate=100,
			use_serial_batch_fields=1,
		)

		batch_no = get_batch_from_bundle(se.items[0].serial_and_batch_bundle)

		se = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target="_Test Warehouse 1 - _TC",
			batch_no=batch_no,
			use_serial_batch_fields=1,
			qty=2,
			purpose="Material Transfer",
			do_not_save=True,
		)

		se.append(
			"additional_costs",
			{
				"cost_center": "Main - _TC",
				"amount": 50,
				"expense_account": "Stock Adjustment - _TC",
				"description": "Test Additional Cost",
			},
		)
		se.save()
		self.assertEqual(se.additional_costs[0].amount, 50)
		self.assertEqual(se.items[0].basic_rate, 100)
		self.assertEqual(se.items[0].valuation_rate, 125)

		se.submit()
		self.assertEqual(se.items[0].basic_rate, 100)
		self.assertEqual(se.items[0].valuation_rate, 125)

		incoming_rate = frappe.db.get_value(
			"Stock Ledger Entry",
			{
				"item_code": item_code,
				"warehouse": "_Test Warehouse 1 - _TC",
				"voucher_type": "Stock Entry",
				"voucher_no": se.name,
			},
			"incoming_rate",
		)

		self.assertEqual(incoming_rate, 125.0)

	def test_prevent_reuse_delivered_serial_no_in_repack(self):
		from hisaabdari.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		item = "Test Prevent Reuse Delivered Serial No"
		warehouse = "_Test Warehouse - _TC"

		item_doc = make_item(item, {"is_stock_item": 1, "has_serial_no": 1, "serial_no_series": "SHGJ.####"})

		make_stock_entry(item_code="_Test Item", target=warehouse, qty=2, rate=100)
		make_stock_entry(item_code=item, target=warehouse, qty=2, rate=100)

		dn = create_delivery_note(item_code=item, qty=2)
		delivered_serial_no = get_serial_nos_from_bundle(dn.get("items")[0].serial_and_batch_bundle)[0]

		se = make_stock_entry(
			item_code="_Test Item", source=warehouse, qty=1, purpose="Repack", do_not_save=True
		)
		se.append(
			"items",
			{
				"item_code": item_doc.name,
				"item_name": item_doc.item_name,
				"s_warehouse": None,
				"t_warehouse": warehouse,
				"description": item_doc.description,
				"uom": item_doc.stock_uom,
				"qty": 1,
				"use_serial_batch_fields": 1,
				"serial_no": delivered_serial_no,
			},
		)

		se.save()
		status = frappe.db.get_value("Serial No", delivered_serial_no, "status")

		self.assertEqual(status, "Delivered")
		self.assertEqual(se.purpose, "Repack")
		self.assertRaises(frappe.ValidationError, se.submit)

	def test_sample_retention_stock_entry(self):
		from hisaabdari.stock.doctype.stock_entry.stock_entry import move_sample_to_retention_warehouse

		frappe.db.set_value(
			"Company", "_Test Company", "sample_retention_warehouse", "_Test Warehouse 1 - _TC"
		)
		warehouse = "_Test Warehouse - _TC"
		retain_sample_item = make_item(
			"Retain Sample Item",
			properties={
				"is_stock_item": 1,
				"retain_sample": 1,
				"sample_quantity": 2,
				"has_batch_no": 1,
				"has_serial_no": 1,
				"create_new_batch": 1,
				"batch_number_series": "SAMPLE-RET-.#####",
				"serial_no_series": "SAMPLE-RET-SN-.#####",
			},
		)
		material_receipt = make_stock_entry(
			item_code=retain_sample_item.item_code, target=warehouse, qty=10, purpose="Material Receipt"
		)

		source_sabb = frappe.get_doc(
			"Serial and Batch Bundle", material_receipt.items[0].serial_and_batch_bundle
		)
		batch = source_sabb.entries[0].batch_no
		serial_nos = [entry.serial_no for entry in source_sabb.entries]

		sample_entry = frappe.get_doc(
			move_sample_to_retention_warehouse(material_receipt.company, material_receipt.items)
		)
		sample_entry.submit()
		target_sabb = frappe.get_doc("Serial and Batch Bundle", sample_entry.items[0].serial_and_batch_bundle)

		self.assertEqual(sample_entry.items[0].transfer_qty, 2)
		self.assertEqual(target_sabb.entries[0].batch_no, batch)
		self.assertEqual([entry.serial_no for entry in target_sabb.entries], serial_nos[:2])

	def test_validate_sample_quantity_raises_when_company_has_no_retention_warehouse(self):
		"""Item.retain_sample only needs *some* company configured, so the transaction company may not be."""
		from hisaabdari.stock.doctype.stock_entry.stock_entry import validate_sample_quantity

		frappe.db.set_value(
			"Company", "_Test Company", "sample_retention_warehouse", "_Test Warehouse 1 - _TC"
		)
		frappe.db.set_value("Company", "_Test Company 1", "sample_retention_warehouse", None)
		item = make_item(
			"_Sample Qty No Retention Item",
			{"is_stock_item": 1, "retain_sample": 1, "sample_quantity": 2, "has_batch_no": 1},
		)
		self.assertRaises(
			frappe.ValidationError,
			validate_sample_quantity,
			item.name,
			1,
			5,
			"_Test Company 1",
			"_Sample Batch",
		)

	def test_sample_retention_warehouse_denied_for_other_company(self):
		"""`company` comes from whitelisted callers, so it must not read another company's stock."""
		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_sample_retention_warehouse

		frappe.db.set_value(
			"Company", "_Test Company", "sample_retention_warehouse", "_Test Warehouse 1 - _TC"
		)

		user = "test_sample_retention_perm@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "Sample Retention",
					"send_welcome_email": 0,
					"roles": [{"role": "Stock User"}],
				}
			).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Company",
				"for_value": "_Test Company 1",
			}
		).insert(ignore_permissions=True)

		with self.set_user(user):
			self.assertRaises(frappe.PermissionError, get_sample_retention_warehouse, "_Test Company")

	@ERPNextTestSuite.change_settings("Stock Settings", {"use_serial_batch_fields": 1})
	def test_fifo_rate_for_serial_item_without_serial_wise_valuation(self):
		item = make_item(
			properties={
				"valuation_method": "FIFO",
				"has_serial_no": 1,
				"use_serial_no_wise_valuation": 0,
				"serial_no_series": "SNWV-.#####",
			}
		).name
		finished_good = make_item(properties={"valuation_method": "FIFO"}).name
		warehouse = "_Test Warehouse - _TC"

		make_stock_entry(item_code=item, target=warehouse, qty=2, rate=100)
		receipt = make_stock_entry(item_code=item, target=warehouse, qty=2, rate=200)
		serial_no = frappe.db.get_value(
			"Serial No", get_serial_nos_from_bundle(receipt.items[0].serial_and_batch_bundle)[0], "serial_no"
		)

		repack = make_stock_entry(
			item_code=item,
			source=warehouse,
			qty=1,
			purpose="Repack",
			serial_no=serial_no,
			use_serial_batch_fields=1,
			do_not_save=True,
		)
		repack.append(
			"items",
			{
				"item_code": finished_good,
				"t_warehouse": warehouse,
				"qty": 1,
				"transfer_qty": 1,
				"is_finished_item": 1,
			},
		)
		repack.save()
		repack.submit()

		self.assertEqual(repack.items[0].basic_rate, 100)
		self.assertEqual(repack.items[1].amount, 100)

	def test_fifo_batch_rate_when_moving_average_batches_are_pooled(self):
		frappe.db.set_single_value("Stock Settings", "do_not_use_batchwise_valuation", 1)
		item = make_item(properties={"valuation_method": "FIFO", "has_batch_no": 1}).name
		finished_good = make_item(properties={"valuation_method": "FIFO"}).name
		warehouse = "_Test Warehouse - _TC"
		first, second = (
			frappe.get_doc({"doctype": "Batch", "batch_id": frappe.generate_hash(length=10), "item": item})
			.insert()
			.name
			for _ in range(2)
		)

		make_stock_entry(item_code=item, target=warehouse, qty=3, rate=460, batch_no=first)
		make_stock_entry(item_code=item, target=warehouse, qty=10, rate=329, batch_no=second)
		repack = make_stock_entry(
			item_code=item, source=warehouse, qty=3, purpose="Repack", batch_no=second, do_not_save=True
		)
		repack.append(
			"items",
			{
				"item_code": finished_good,
				"t_warehouse": warehouse,
				"qty": 13,
				"transfer_qty": 13,
				"is_finished_item": 1,
			},
		)
		repack.save()
		repack.submit()

		self.assertEqual(repack.items[0].basic_rate, 329)
		self.assertEqual(repack.items[1].amount, 987)

	def test_repack_output_takes_the_consumed_value(self):
		warehouse = "_Test Warehouse - _TC"
		for properties in (
			{},
			{"has_batch_no": 1, "create_new_batch": 1, "batch_number_series": "RPB-.#####"},
			{"has_serial_no": 1, "serial_no_series": "RPS-.#####"},
		):
			raw_material = make_item(properties={"valuation_method": "Moving Average"}).name
			output = make_item(properties={"valuation_method": "Moving Average", **properties}).name
			make_stock_entry(item_code=raw_material, target=warehouse, qty=8, rate=209.416)
			make_stock_entry(item_code=raw_material, target=warehouse, qty=2, rate=19.14)

			repack = self.make_repack(raw_material, 5, warehouse, output, 11)

			self.assertEqual(self.get_value_change(repack, raw_material), -856.81)
			self.assertEqual(self.get_value_change(repack, output), 856.81)

			issue = make_stock_entry(item_code=output, source=warehouse, qty=5)
			self.assertEqual(self.get_value_change(issue, output), -389.46)

	def test_repack_output_stays_non_negative_after_repost(self):
		raw_material, output = (
			make_item(properties={"valuation_method": "Moving Average"}).name for _ in range(2)
		)
		scrap = make_item(properties={"valuation_rate": 80}).name
		warehouse = "_Test Warehouse - _TC"
		make_stock_entry(
			item_code=raw_material, target=warehouse, qty=1, rate=100, posting_date=add_days(today(), -3)
		)
		repack = make_stock_entry(
			item_code=raw_material,
			source=warehouse,
			qty=1,
			purpose="Repack",
			posting_date=add_days(today(), -1),
			do_not_save=True,
		)
		repack.append(
			"items", {"item_code": output, "t_warehouse": warehouse, "qty": 1, "is_finished_item": 1}
		)
		repack.append(
			"items", {"item_code": scrap, "t_warehouse": warehouse, "qty": 1, "secondary_item_type": "Scrap"}
		)
		repack.submit()
		self.assertEqual(self.get_value_change(repack, output), 20)

		make_stock_entry(
			item_code=raw_material,
			target=warehouse,
			qty=1,
			rate=0,
			allow_zero_valuation_rate=1,
			posting_date=add_days(today(), -5),
		)

		self.assertEqual(self.get_value_change(repack, output), 0)

	def make_repack(self, raw_material, qty, warehouse, output, output_qty):
		repack = make_stock_entry(
			item_code=raw_material, source=warehouse, qty=qty, purpose="Repack", do_not_save=True
		)
		repack.append(
			"items", {"item_code": output, "t_warehouse": warehouse, "qty": output_qty, "is_finished_item": 1}
		)
		repack.submit()
		return repack

	def get_value_change(self, stock_entry, item_code):
		return frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": stock_entry.name, "item_code": item_code, "is_cancelled": 0},
			"stock_value_difference",
		)

	def test_repack_takes_manual_finished_good_value_out_of_the_cost(self):
		fg_item = make_item(properties={"is_stock_item": 1}).name
		rm_item = make_item(properties={"is_stock_item": 1}).name
		make_stock_entry(item_code=rm_item, target="_Test Warehouse - _TC", qty=10, basic_rate=100)

		entry = self.make_entry_with_rows(
			"Repack",
			stock_entry_row(rm_item, 10, s_warehouse="_Test Warehouse - _TC"),
			stock_entry_row(
				fg_item,
				5,
				t_warehouse="_Test Warehouse 1 - _TC",
				is_finished_item=1,
				set_basic_rate_manually=1,
				basic_rate=100,
			),
			stock_entry_row(fg_item, 5, t_warehouse="_Test Warehouse 1 - _TC", is_finished_item=1),
		)

		self.assertEqual([d.basic_amount for d in entry.items if d.is_finished_item], [500, 500])

	def test_stock_in_from_transit_must_take_the_sent_item_from_transit(self):
		item_code = make_item(properties={"is_stock_item": 1}).name
		other_item = make_item(properties={"is_stock_item": 1}).name
		for item in (item_code, other_item):
			make_stock_entry(item_code=item, target="_Test Warehouse - _TC", qty=20, basic_rate=100)

		outward = make_stock_entry(
			item_code=item_code,
			source="_Test Warehouse - _TC",
			target="Goods In Transit - _TC",
			add_to_transit=1,
			qty=10,
		)

		for field, value in (("s_warehouse", "_Test Warehouse - _TC"), ("item_code", other_item)):
			stock_in = make_stock_in_entry(outward.name)
			stock_in.items[0].t_warehouse = "_Test Warehouse 1 - _TC"
			stock_in.items[0].set(field, value)
			self.assertRaises(frappe.ValidationError, stock_in.insert)

		plain_transfer = make_stock_entry(
			item_code=item_code, source="_Test Warehouse - _TC", target="_Test Warehouse 1 - _TC", qty=1
		)
		self.assertRaises(frappe.ValidationError, make_stock_in_entry, plain_transfer.name)

	def test_expired_batch_items_need_batch_read_and_leave_out_batches_expiring_today(self):
		from hisaabdari.stock.doctype.batch.test_batch import make_new_batch
		from hisaabdari.stock.doctype.stock_entry.stock_entry import (
			get_expired_batch_items,
			get_expired_batches,
		)

		item = make_item(properties={"is_stock_item": 1, "has_batch_no": 1}).name
		expiring_today = make_new_batch(
			batch_id=frappe.generate_hash("", 8), item_code=item, expiry_date=today()
		).name
		self.assertNotIn(expiring_today, get_expired_batches())

		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertRaises(frappe.PermissionError, get_expired_batch_items)

	def make_entry_with_rows(self, purpose, *rows, **kwargs):
		entry = frappe.new_doc("Stock Entry")
		entry.company = kwargs.pop("company", "_Test Company")
		entry.purpose = purpose
		entry.set_stock_entry_type()
		entry.update(kwargs)
		for row in rows:
			entry.append("items", row)

		entry.insert()
		return entry

	def test_make_stock_entry_needs_stock_entry_permission(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		user = create_user("test_make_stock_entry_perm@example.com", "Delivery User")

		with self.set_user(user.name):
			self.assertRaises(
				frappe.PermissionError,
				make_stock_entry,
				item_code="_Test Item",
				target="_Test Warehouse - _TC",
				qty=1,
				do_not_save=1,
			)

	def test_get_warehouse_details_needs_stock_entry_read(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_warehouse_details

		user = create_user("test_warehouse_details_delivery@example.com", "Delivery User")
		args = {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}

		with self.set_user(user.name):
			self.assertRaises(frappe.PermissionError, get_warehouse_details, args)

	def test_get_warehouse_details_applies_warehouse_user_permission(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_warehouse_details

		make_stock_entry(item_code="_Test Item", target="_Test Warehouse - _TC", qty=10, basic_rate=100)
		user = create_user("test_warehouse_details_stock@example.com", "Stock User")
		add_user_permission("Warehouse", "_Test Warehouse - _TC", user.name)
		self.addCleanup(remove_user_permission, "Warehouse", "_Test Warehouse - _TC", user.name)

		args = {"item_code": "_Test Item", "posting_date": today(), "posting_time": nowtime()}
		own_warehouse_args = {**args, "warehouse": "_Test Warehouse - _TC"}
		expected = get_warehouse_details(own_warehouse_args)

		with self.set_user(user.name):
			self.assertEqual(get_warehouse_details(own_warehouse_args), expected)
			self.assertRaises(
				frappe.PermissionError,
				get_warehouse_details,
				{**args, "warehouse": "_Test Warehouse 1 - _TC"},
			)

	def test_get_warehouse_details_applies_warehouse_user_permission_for_stock_entry(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_warehouse_details

		make_stock_entry(item_code="_Test Item", target="_Test Warehouse 1 - _TC", qty=10, basic_rate=100)
		stock_entry_user = create_user("test_warehouse_details_scoped@example.com", "Stock User")
		for user, applicable_for in ((stock_entry_user.name, "Stock Entry"),):
			add_user_permission("Warehouse", "_Test Warehouse - _TC", user, applicable_for=applicable_for)
			self.addCleanup(remove_user_permission, "Warehouse", "_Test Warehouse - _TC", user)

		args = {"item_code": "_Test Item", "posting_date": today(), "posting_time": nowtime()}
		other_warehouse_args = {**args, "warehouse": "_Test Warehouse 1 - _TC"}
		expected = get_warehouse_details(other_warehouse_args)

		with self.set_user(stock_entry_user.name):
			self.assertRaises(frappe.PermissionError, get_warehouse_details, other_warehouse_args)

	def test_get_warehouse_details_needs_item_select(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user
		from frappe.permissions import add_permission

		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_warehouse_details

		role = "_Test Stock Entry Reader"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 0}).insert()
		add_permission("Stock Entry", role)
		self.addCleanup(frappe.clear_cache, doctype="Stock Entry")
		user = create_user("test_warehouse_details_reader@example.com", role).name
		args = {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}

		with self.set_user(user):
			self.assertTrue(frappe.has_permission("Stock Entry", "read"))
			self.assertFalse(frappe.has_permission("Item", "select"))
			self.assertRaises(frappe.PermissionError, get_warehouse_details, args)

	def test_get_warehouse_details_combines_warehouse_user_permissions_for_stock_entry(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_warehouse_details

		make_stock_entry(item_code="_Test Item", target="_Test Warehouse 1 - _TC", qty=10, basic_rate=100)
		user = create_user("test_warehouse_details_combined@example.com", "Stock User").name
		add_user_permission("Warehouse", "_Test Warehouse - _TC", user)
		add_user_permission("Warehouse", "_Test Warehouse 1 - _TC", user, applicable_for="Stock Entry")
		self.addCleanup(remove_user_permission, "Warehouse", "_Test Warehouse - _TC", user)
		self.addCleanup(remove_user_permission, "Warehouse", "_Test Warehouse 1 - _TC", user)

		args = {"item_code": "_Test Item", "posting_date": today(), "posting_time": nowtime()}
		stock_entry_warehouse_args = {**args, "warehouse": "_Test Warehouse 1 - _TC"}
		expected = get_warehouse_details(stock_entry_warehouse_args)

		with self.set_user(user):
			self.assertEqual(get_warehouse_details(stock_entry_warehouse_args), expected)
			self.assertRaises(
				frappe.PermissionError, get_warehouse_details, {**args, "warehouse": "Stores - _TC"}
			)

	def test_get_warehouse_details_applies_company_user_permission(self):
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		from hisaabdari.stock.doctype.stock_entry.stock_entry import get_warehouse_details

		user = create_user("test_warehouse_details_company@example.com", "Stock User").name
		add_user_permission("Company", "_Test Company", user)
		self.addCleanup(remove_user_permission, "Company", "_Test Company", user)
		args = {"item_code": "_Test Item", "posting_date": today(), "posting_time": nowtime()}

		with self.set_user(user):
			self.assertEqual(
				set(get_warehouse_details({**args, "warehouse": "_Test Warehouse - _TC"})),
				{"actual_qty", "basic_rate"},
			)
			self.assertRaises(
				frappe.PermissionError,
				get_warehouse_details,
				{**args, "warehouse": "_Test Warehouse 2 - _TC1"},
			)


def make_serialized_item(self, **args):
	args = frappe._dict(args)
	se = frappe.copy_doc(self.globalTestRecords["Stock Entry"][0])

	if args.company:
		se.company = args.company

	if args.target_warehouse:
		se.get("items")[0].t_warehouse = args.target_warehouse

	se.get("items")[0].item_code = args.item_code or "_Test Serialized Item With Series"

	if args.serial_no:
		serial_nos = args.serial_no
		if isinstance(serial_nos, str):
			serial_nos = [serial_nos]

		se.get("items")[0].serial_and_batch_bundle = make_serial_batch_bundle(
			frappe._dict(
				{
					"item_code": se.get("items")[0].item_code,
					"warehouse": se.get("items")[0].t_warehouse,
					"company": se.company,
					"qty": 2,
					"voucher_type": "Stock Entry",
					"serial_nos": serial_nos,
					"posting_date": today(),
					"posting_time": nowtime(),
					"do_not_submit": True,
				}
			)
		).name

	if args.cost_center:
		se.get("items")[0].cost_center = args.cost_center

	if args.expense_account:
		se.get("items")[0].expense_account = args.expense_account

	se.get("items")[0].qty = 2
	se.get("items")[0].transfer_qty = 2

	se.set_stock_entry_type()
	se.insert()
	se.submit()

	se.load_from_db()
	return se


def get_qty_after_transaction(**args):
	args = frappe._dict(args)
	last_sle = get_previous_sle(
		{
			"item_code": args.item_code or "_Test Item",
			"warehouse": args.warehouse or "_Test Warehouse - _TC",
			"posting_date": args.posting_date or nowdate(),
			"posting_time": args.posting_time or nowtime(),
		}
	)
	return flt(last_sle.get("qty_after_transaction"))


def get_multiple_items():
	return [
		{
			"conversion_factor": 1.0,
			"cost_center": "Main - TCP1",
			"doctype": "Stock Entry Detail",
			"expense_account": "Stock Adjustment - TCP1",
			"basic_rate": 100,
			"item_code": "_Test Item",
			"qty": 50.0,
			"s_warehouse": "Stores - TCP1",
			"stock_uom": "_Test UOM",
			"transfer_qty": 50.0,
			"uom": "_Test UOM",
		},
		{
			"conversion_factor": 1.0,
			"cost_center": "Main - TCP1",
			"doctype": "Stock Entry Detail",
			"expense_account": "Stock Adjustment - TCP1",
			"basic_rate": 5000,
			"item_code": "_Test Item Home Desktop 100",
			"qty": 1,
			"stock_uom": "_Test UOM",
			"t_warehouse": "Stores - TCP1",
			"transfer_qty": 1,
			"uom": "_Test UOM",
		},
	]


def initialize_records_for_future_negative_sle_test(
	item_code, batch_no, warehouses, opening_qty, posting_date
):
	from hisaabdari.stock.doctype.batch.test_batch import TestBatch, make_new_batch
	from hisaabdari.stock.doctype.stock_reconciliation.test_stock_reconciliation import (
		create_stock_reconciliation,
	)
	from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

	TestBatch.make_batch_item(item_code)
	make_new_batch(item_code=item_code, batch_id=batch_no)
	warehouse_names = [create_warehouse(w) for w in warehouses]
	create_stock_reconciliation(
		purpose="Opening Stock",
		posting_date=posting_date,
		posting_time="20:00:20",
		item_code=item_code,
		warehouse=warehouse_names[0],
		valuation_rate=100,
		qty=opening_qty,
		batch_no=batch_no,
	)
	return warehouse_names


def create_stock_entries(sequence_of_entries):
	for entry_detail in sequence_of_entries:
		make_stock_entry(**entry_detail)
