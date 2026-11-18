# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
from frappe import qb
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import add_days, today

from hisaabdari.stock.doctype.item.item import (
	DataValidationError,
	InvalidBarcode,
	get_timeline_data,
	get_uom_conv_factor,
	set_item_default,
	validate_is_stock_item,
)
from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from hisaabdari.stock.get_item_details import ItemDetailsCtx, get_item_details, get_item_tax_template
from hisaabdari.tests.utils import ERPNextTestSuite


def make_item(item_code=None, properties=None, uoms=None, barcode=None):
	if not item_code:
		item_code = frappe.generate_hash(length=16)

	if frappe.db.exists("Item", item_code):
		return frappe.get_doc("Item", item_code)

	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"description": item_code,
			"item_group": "Products",
		}
	)

	if properties:
		item.update(properties)

	if item.is_stock_item:
		for item_default in [doc for doc in item.get("item_defaults") if not doc.default_warehouse]:
			item_default.default_warehouse = "_Test Warehouse - _TC"
			item_default.company = "_Test Company"

	if uoms:
		for uom in uoms:
			item.append("uoms", uom)

	if barcode:
		item.append(
			"barcodes",
			{
				"barcode": barcode,
			},
		)

	item.insert()

	return item


class TestItem(ERPNextTestSuite):
	def setUp(self):
		super().setUp()
		frappe.flags.attribute_values = None

	def get_item(self, idx):
		item_code = self.globalTestRecords["Item"][idx].get("item_code")
		if not frappe.db.exists("Item", item_code):
			item = frappe.copy_doc(self.globalTestRecords["Item"][idx])
			item.insert()
		else:
			item = frappe.get_doc("Item", item_code)
		return item

	def make_bin(self, records):
		for x in records:
			x = frappe._dict(x)
			bin = qb.DocType("Bin")
			filters = {
				"item_code": x.get("item_code"),
				"warehouse": x.get("warehouse"),
				"reserved_qty": x.get("reserved_qty"),
				"actual_qty": x.get("actual_qty"),
				"ordered_qty": x.get("ordered_qty"),
				"projected_qty": x.get("projected_qty"),
			}
			if not frappe.db.exists("Bin", filters):
				qb.from_(bin).delete().where(
					bin.item_code.eq(x.item_code) & bin.warehouse.eq(x.warehouse)
				).run()
				frappe.get_doc(x).insert()

	def test_get_item_details(self):
		to_check = {
			"item_code": "_Test Item",
			"item_name": "_Test Item",
			"description": "_Test Item 1",
			"warehouse": "_Test Warehouse - _TC",
			"income_account": "Sales - _TC",
			"expense_account": "_Test Account Cost for Goods Sold - _TC",
			"cost_center": "_Test Cost Center - _TC",
			"qty": 1.0,
			"price_list_rate": 100.0,
			"base_price_list_rate": 0.0,
			"discount_percentage": 0.0,
			"rate": 0.0,
			"base_rate": 0.0,
			"amount": 0.0,
			"base_amount": 0.0,
			"batch_no": None,
			"uom": "_Test UOM",
			"conversion_factor": 1.0,
			"reserved_qty": 1,
			"actual_qty": 5,
			"projected_qty": 14,
		}

		self.make_bin(
			[
				{
					"doctype": "Bin",
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse - _TC",
					"reserved_qty": 1,
					"actual_qty": 5,
					"ordered_qty": 10,
					"projected_qty": 14,
				}
			],
		)

		company = "_Test Company"
		currency = frappe.get_cached_value("Company", company, "default_currency")

		details = get_item_details(
			ItemDetailsCtx(
				{
					"item_code": "_Test Item",
					"company": company,
					"price_list": "_Test Price List",
					"currency": currency,
					"doctype": "Sales Order",
					"conversion_rate": 1,
					"price_list_currency": currency,
					"plc_conversion_rate": 1,
					"order_type": "Sales",
					"customer": "_Test Customer",
					"conversion_factor": 1,
					"price_list_uom_dependant": 1,
					"ignore_pricing_rule": 1,
					"qty": 1,
				}
			)
		)

		for key, value in to_check.items():
			self.assertEqual(value, details.get(key), key)

	def test_item_tax_template(self):
		expected_item_tax_template = [
			{
				"item_code": "_Test Item With Item Tax Template",
				"item_tax_template": "_Test Account Excise Duty @ 10 - _TC",
			},
			{
				"item_code": "_Test Item Inherit Group Item Tax Template 1",
				"item_tax_template": "_Test Account Excise Duty @ 10 - _TC",
			},
			{
				"item_code": "_Test Item Inherit Group Item Tax Template 2",
				"item_tax_template": "_Test Account Excise Duty @ 15 - _TC",
			},
			{
				"item_code": "_Test Item Override Group Item Tax Template",
				"item_tax_template": "_Test Account Excise Duty @ 20 - _TC",
			},
		]

		expected_item_tax_map = {
			None: {},
			"_Test Account Excise Duty @ 10 - _TC": {"_Test Account Excise Duty - _TC": 10},
			"_Test Account Excise Duty @ 12 - _TC": {"_Test Account Excise Duty - _TC": 12},
			"_Test Account Excise Duty @ 15 - _TC": {"_Test Account Excise Duty - _TC": 15},
			"_Test Account Excise Duty @ 20 - _TC": {"_Test Account Excise Duty - _TC": 20},
			"_Test Item Tax Template 1 - _TC": {
				"_Test Account Excise Duty - _TC": 5,
				"_Test Account Education Cess - _TC": 10,
				"_Test Account S&H Education Cess - _TC": 15,
			},
		}

		for data in expected_item_tax_template:
			details = get_item_details(
				ItemDetailsCtx(
					{
						"item_code": data["item_code"],
						"company": "_Test Company",
						"price_list": "_Test Price List",
						"currency": "INR",
						"doctype": "Sales Order",
						"conversion_rate": 1,
						"price_list_currency": "INR",
						"plc_conversion_rate": 1,
						"order_type": "Sales",
						"customer": "_Test Customer",
						"conversion_factor": 1,
						"price_list_uom_dependant": 1,
					}
				)
			)

			self.assertEqual(details.item_tax_template, data["item_tax_template"])
			self.assertEqual(
				json.loads(details.item_tax_rate), expected_item_tax_map[details.item_tax_template]
			)

	def test_item_follows_item_group_tax_changes(self):
		item_group = frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": f"_Test Tax Group {frappe.generate_hash(length=6)}",
				"parent_item_group": "All Item Groups",
				"taxes": [{"item_tax_template": "_Test Account Excise Duty @ 10 - _TC"}],
			}
		).insert()
		item = make_item(properties={"item_group": item_group.name})
		self.assertFalse(item.taxes)

		item_group.taxes[0].item_tax_template = "_Test Account Excise Duty @ 12 - _TC"
		item_group.save()

		ctx = frappe._dict(item_code=item.name, company="_Test Company")
		self.assertEqual(get_item_tax_template(ctx), "_Test Account Excise Duty @ 12 - _TC")

	def test_item_defaults(self):
		frappe.delete_doc_if_exists("Item", "Test Item With Defaults", force=1)
		make_item(
			"Test Item With Defaults",
			{
				"item_group": "_Test Item Group",
				"item_defaults": [
					{
						"company": "_Test Company",
						"default_warehouse": "_Test Warehouse 2 - _TC",  # no override
						"expense_account": "_Test Account Stock Expenses - _TC",  # override brand default
						"default_cogs_account": "_Test Account Cost for Goods Sold - _TC",  # override brand default
						"buying_cost_center": "_Test Write Off Cost Center - _TC",  # override item group default
					}
				],
			},
		)

		sales_item_check = {
			"item_code": "Test Item With Defaults",
			"warehouse": "_Test Warehouse 2 - _TC",  # from item
			"expense_account": "_Test Account Cost for Goods Sold - _TC",  # from item
		}
		sales_item_details = get_item_details(
			ItemDetailsCtx(
				{
					"item_code": "Test Item With Defaults",
					"company": "_Test Company",
					"price_list": "_Test Price List",
					"currency": "INR",
					"doctype": "Sales Invoice",
					"conversion_rate": 1,
					"price_list_currency": "INR",
					"plc_conversion_rate": 1,
					"customer": "_Test Customer",
				}
			)
		)
		for key, value in sales_item_check.items():
			self.assertEqual(value, sales_item_details.get(key))

		purchase_item_check = {
			"item_code": "Test Item With Defaults",
			"warehouse": "_Test Warehouse 2 - _TC",  # from item
			"expense_account": "_Test Account Stock Expenses - _TC",  # from item
			"cost_center": "_Test Write Off Cost Center - _TC",  # from item
		}
		purchase_item_details = get_item_details(
			ItemDetailsCtx(
				{
					"item_code": "Test Item With Defaults",
					"company": "_Test Company",
					"price_list": "_Test Price List",
					"currency": "INR",
					"doctype": "Purchase Invoice",
					"conversion_rate": 1,
					"price_list_currency": "INR",
					"plc_conversion_rate": 1,
					"supplier": "_Test Supplier",
				}
			)
		)
		for key, value in purchase_item_check.items():
			self.assertEqual(value, purchase_item_details.get(key))

	def test_set_item_default_refreshes_cached_item(self):
		item = make_item(
			properties={
				"item_defaults": [{"default_warehouse": "_Test Warehouse - _TC", "company": "_Test Company"}]
			}
		)

		set_item_default(item.name, "_Test Company", "income_account", "_Test Account Sales - _TC")

		cached_item = frappe.get_cached_doc("Item", item.name)
		self.assertEqual(cached_item.item_defaults[0].income_account, "_Test Account Sales - _TC")

	def test_item_default_validations(self):
		with self.assertRaises(frappe.ValidationError) as ve:
			make_item(
				"Bad Item defaults",
				{
					"item_group": "_Test Item Group",
					"item_defaults": [
						{
							"company": "_Test Company 1",
							"default_warehouse": "_Test Warehouse - _TC",
							"expense_account": "Stock In Hand - _TC",
							"buying_cost_center": "_Test Cost Center - _TC",
							"selling_cost_center": "_Test Cost Center - _TC",
						}
					],
				},
			)

		self.assertTrue(
			"belong to company" in str(ve.exception).lower(),
			msg="Mismatching company entities in item defaults should not be allowed.",
		)

	def test_standard_rate_price_goes_to_a_selling_list(self):
		item = make_item(
			properties={
				"is_stock_item": 1,
				"standard_rate": 500,
				"item_defaults": [{"company": "_Test Company", "default_price_list": "Standard Buying"}],
			}
		).name
		self.assertFalse(frappe.db.exists("Item Price", {"item_code": item, "price_list": "Standard Buying"}))
		self.assertTrue(frappe.db.exists("Item Price", {"item_code": item, "selling": 1}))

		if not frappe.db.exists("Price List", "_Test Second Buying List"):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": "_Test Second Buying List",
					"buying": 1,
					"currency": "INR",
				}
			).insert()
		shared = make_item(
			properties={
				"is_stock_item": 0,
				"standard_rate": 300,
				"item_defaults": [
					{"company": "_Test Company", "default_price_list": "Standard Buying"},
					{"company": "_Test Company 1", "default_price_list": "_Test Second Buying List"},
				],
			}
		).name
		self.assertEqual(frappe.db.count("Item Price", {"item_code": shared}), 1)

	@ERPNextTestSuite.change_settings("Global Defaults", {"default_company": "_Test Company"})
	@ERPNextTestSuite.change_settings("Accounts Settings", {"allow_stale": 1})
	def test_standard_rate_price_uses_the_selling_exchange_rate(self):
		from frappe.utils import add_days, today

		if not frappe.db.exists("Currency", "TSR"):
			frappe.get_doc({"doctype": "Currency", "currency_name": "TSR", "enabled": 1}).insert()

		if not frappe.db.exists("Price List", "_Test Selling TSR Standard Rate List"):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": "_Test Selling TSR Standard Rate List",
					"selling": 1,
					"currency": "TSR",
				}
			).insert()

		for days, rate, for_buying, for_selling in ((-5, 80, 0, 1), (-1, 90, 1, 0)):
			frappe.get_doc(
				{
					"doctype": "Currency Exchange",
					"date": add_days(today(), days),
					"from_currency": "TSR",
					"to_currency": "INR",
					"exchange_rate": rate,
					"for_buying": for_buying,
					"for_selling": for_selling,
				}
			).insert()

		item = make_item(
			properties={
				"is_stock_item": 1,
				"standard_rate": 800,
				"item_defaults": [
					{"company": "_Test Company", "default_price_list": "_Test Selling TSR Standard Rate List"}
				],
			}
		).name
		price = frappe.db.get_value(
			"Item Price",
			{"item_code": item, "price_list": "_Test Selling TSR Standard Rate List"},
			"price_list_rate",
		)
		self.assertEqual(price, 10)

	@ERPNextTestSuite.change_settings("Global Defaults", {"default_company": "_Test Company"})
	@ERPNextTestSuite.change_settings("Accounts Settings", {"allow_stale": 1})
	def test_standard_rate_price_in_another_currency_is_rounded(self):
		from frappe.utils import add_days, today

		if not frappe.db.exists("Currency", "TPR"):
			frappe.get_doc({"doctype": "Currency", "currency_name": "TPR", "enabled": 1}).insert()

		price_list = frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": "_Test Selling TPR Standard Rate List",
				"selling": 1,
				"currency": "TPR",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"date": add_days(today(), -1),
				"from_currency": "TPR",
				"to_currency": "INR",
				"exchange_rate": 1.1,
				"for_selling": 1,
			}
		).insert()

		item = make_item(
			properties={
				"is_stock_item": 1,
				"standard_rate": 100,
				"item_defaults": [{"company": "_Test Company", "default_price_list": price_list.name}],
			}
		).name
		price = frappe.db.get_value(
			"Item Price", {"item_code": item, "price_list": price_list.name}, "price_list_rate"
		)
		self.assertEqual(price, 90.91)

	@ERPNextTestSuite.change_settings("Global Defaults", {"default_company": "_Test Company"})
	@ERPNextTestSuite.change_settings("Accounts Settings", {"allow_stale": 1})
	@ERPNextTestSuite.change_settings(
		"System Settings", {"currency_precision": "", "use_number_format_from_currency": 1}
	)
	def test_standard_rate_price_is_rounded_to_its_currency_precision(self):
		if not frappe.db.exists("Currency", "TPT"):
			frappe.get_doc(
				{"doctype": "Currency", "currency_name": "TPT", "enabled": 1, "number_format": "#,###.###"}
			).insert()

		price_list = frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": "_Test Selling TPT Standard Rate List",
				"selling": 1,
				"currency": "TPT",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"date": add_days(today(), -1),
				"from_currency": "TPT",
				"to_currency": "INR",
				"exchange_rate": 1.1,
				"for_selling": 1,
			}
		).insert()

		item = make_item(
			properties={
				"is_stock_item": 1,
				"standard_rate": 100,
				"item_defaults": [{"company": "_Test Company", "default_price_list": price_list.name}],
			}
		).name
		price = frappe.db.get_value(
			"Item Price", {"item_code": item, "price_list": price_list.name}, "price_list_rate"
		)
		self.assertEqual(price, 90.909)

	def test_maintain_stock_cannot_be_turned_on_after_an_invoice(self):
		from hisaabdari.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice

		item = make_item(properties={"is_stock_item": 0})
		make_purchase_invoice(item_code=item.name, qty=4, rate=250)

		item.reload()
		item.is_stock_item = 1
		self.assertRaises(frappe.ValidationError, item.save)

	def test_item_default_accounts_follow_the_company_and_type(self):
		for field, account in (
			("default_cogs_account", "Cost of Goods Sold - _TC1"),
			("default_inventory_account", "Sales - _TC"),
		):
			item = make_item(properties={"is_stock_item": 1})
			item.append("item_defaults", {"company": "_Test Company", field: account})
			self.assertRaises(frappe.ValidationError, item.save)

	def test_merge_keeps_the_source_demand_in_other_warehouses(self):
		from hisaabdari.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
		from hisaabdari.stock.utils import get_bin

		old_item = make_item(properties={"is_stock_item": 1}).name
		target_item = make_item(properties={"is_stock_item": 1}).name
		make_stock_entry(item_code=target_item, target="_Test Warehouse - _TC", qty=5, basic_rate=300)
		create_purchase_order(item_code=old_item, warehouse="_Test Warehouse 1 - _TC", qty=7)

		frappe.rename_doc("Item", old_item, target_item, merge=True)

		self.assertEqual(get_bin(target_item, "_Test Warehouse 1 - _TC").ordered_qty, 7)

	def test_item_merging(self):
		old = create_item(frappe.generate_hash(length=20)).name
		new = create_item(frappe.generate_hash(length=20)).name

		make_stock_entry(item_code=old, target="_Test Warehouse - _TC", qty=1, rate=100)
		make_stock_entry(item_code=old, target="_Test Warehouse 1 - _TC", qty=1, rate=100)
		make_stock_entry(item_code=new, target="_Test Warehouse 1 - _TC", qty=1, rate=100)

		frappe.rename_doc("Item", old, new, merge=True)

		self.assertFalse(frappe.db.exists("Item", old))

		self.assertTrue(frappe.db.get_value("Bin", {"item_code": new, "warehouse": "_Test Warehouse - _TC"}))
		self.assertTrue(
			frappe.db.get_value("Bin", {"item_code": new, "warehouse": "_Test Warehouse 1 - _TC"})
		)

	def test_invalid_uom_conversion_factor(self):
		for conversion_factor in (0, -1):
			with self.subTest(conversion_factor=conversion_factor), self.assertRaisesRegex(
				frappe.ValidationError, "Conversion Factor must be greater than zero"
			):
				make_item(uoms=[{"uom": "Box", "conversion_factor": conversion_factor}])

	def test_preserve_explicit_uom_conversion_factor(self):
		item = make_item(properties={"stock_uom": "Gram"}, uoms=[{"uom": "Kg", "conversion_factor": 950}])
		self.assertEqual(item.uoms[0].conversion_factor, 950)

	def test_disabled_uom_cannot_be_used_by_item(self):
		disabled_uom = frappe.get_doc(
			{"doctype": "UOM", "uom_name": frappe.generate_hash(length=12), "enabled": 0}
		).insert()

		self.assertRaises(frappe.ValidationError, make_item, properties={"stock_uom": disabled_uom.name})
		self.assertRaises(
			frappe.ValidationError,
			make_item,
			uoms=[{"uom": disabled_uom.name, "conversion_factor": 2}],
		)

	def test_item_uom_conversion_factor_overrides_global_factor(self):
		custom_factor = 10.76
		global_factor = get_uom_conv_factor("Square Meter", "Square Foot")
		self.assertNotEqual(custom_factor, global_factor)

		item = make_item(
			properties={"stock_uom": "Square Foot"},
			uoms=[{"uom": "Square Meter", "conversion_factor": custom_factor}],
		)
		item.reload()

		conversion_factor = next(row.conversion_factor for row in item.uoms if row.uom == "Square Meter")
		self.assertEqual(conversion_factor, custom_factor)

	def test_uom_conv_base_case(self):
		factor = get_uom_conv_factor("m", "m")
		self.assertEqual(factor, 1.0)

	def test_invalid_upc_a_barcode_is_refused(self):
		from hisaabdari.stock.doctype.item.item import InvalidBarcode

		item = make_item(properties={"is_stock_item": 1})
		item.append("barcodes", {"barcode": "036000291453", "barcode_type": "UPC-A"})
		self.assertRaises(InvalidBarcode, item.save)

	def test_reorder_group_change_is_checked(self):
		from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

		other_group = create_warehouse("_Test Reorder Other Group", {"is_group": 1})
		item = make_item(
			properties={
				"is_stock_item": 1,
				"reorder_levels": [
					{
						"warehouse_group": "_Test Warehouse Group - _TC",
						"warehouse": "_Test Warehouse Group-C1 - _TC",
						"warehouse_reorder_level": 10,
						"warehouse_reorder_qty": 5,
						"material_request_type": "Purchase",
					}
				],
			}
		)

		item.reorder_levels[0].warehouse_group = other_group
		self.assertRaises(frappe.ValidationError, item.save)

	def test_add_item_barcode(self):
		# Clean up
		item_code = "Test Item Barcode"
		if frappe.db.exists("Item", item_code):
			frappe.delete_doc("Item", item_code)

		# Create new item and add barcodes
		barcode_properties_list = [
			{"barcode": "0012345678905", "barcode_type": "EAN"},
			{"barcode": "012345678905", "barcode_type": "UAN"},
			{
				"barcode": "ARBITRARY_TEXT",
			},
			{"barcode": "036000291452", "barcode_type": "UPC-A"},
			{"barcode": "123456", "barcode_type": "CODE-39"},
			{"barcode": "401268452363", "barcode_type": "EAN"},
			{"barcode": "90311017", "barcode_type": "EAN"},
			{"barcode": "73513537", "barcode_type": "EAN"},
			{"barcode": "0123456789012", "barcode_type": "GS1"},
			{"barcode": "2211564566668", "barcode_type": "GTIN"},
			{"barcode": "0256480249", "barcode_type": "ISBN"},
			{"barcode": "0192552570", "barcode_type": "ISBN-10"},
			{"barcode": "9781234567897", "barcode_type": "ISBN-13"},
			{"barcode": "9771234567898", "barcode_type": "ISSN"},
			{"barcode": "4581171967072", "barcode_type": "JAN"},
			{"barcode": "12345678", "barcode_type": "PZN"},
			{"barcode": "725272730706", "barcode_type": "UPC"},
		]
		create_item(item_code)
		for barcode_properties in barcode_properties_list:
			item_doc = frappe.get_doc("Item", item_code)
			new_barcode = item_doc.append("barcodes")
			new_barcode.update(barcode_properties)
			item_doc.save()

		# Check values saved correctly
		barcodes = frappe.get_all(
			"Item Barcode", fields=["barcode", "barcode_type"], filters={"parent": item_code}
		)

		for barcode_properties in barcode_properties_list:
			barcode_to_find = barcode_properties["barcode"]
			matching_barcodes = [x for x in barcodes if x["barcode"] == barcode_to_find]
		self.assertEqual(len(matching_barcodes), 1)
		details = matching_barcodes[0]

		for key, value in barcode_properties.items():
			self.assertEqual(value, details.get(key))

		# Add barcode again - should cause DuplicateEntryError
		item_doc = frappe.get_doc("Item", item_code)
		new_barcode = item_doc.append("barcodes")
		new_barcode.update(barcode_properties_list[0])
		self.assertRaises(frappe.UniqueValidationError, item_doc.save)

		# Add invalid barcode - should cause InvalidBarcode
		item_doc = frappe.get_doc("Item", item_code)
		new_barcode = item_doc.append("barcodes")
		new_barcode.barcode = "9999999999999"
		new_barcode.barcode_type = "EAN"
		self.assertRaises(InvalidBarcode, item_doc.save)

	def test_heatmap_data(self):
		import time

		data = get_timeline_data("Item", "_Test Item")
		self.assertTrue(isinstance(data, dict))

		now = time.time()
		one_year_ago = now - 366 * 24 * 60 * 60

		for timestamp, count in data.items():
			self.assertIsInstance(timestamp, int)
			self.assertTrue(one_year_ago <= timestamp <= now)
			self.assertIsInstance(count, int)
			self.assertTrue(count >= 0)

	def test_index_creation(self):
		"check if index is getting created in db"

		indices = frappe.db.sql("show index from tabItem", as_dict=1)
		expected_columns = {"item_code", "item_name", "item_group"}
		for index in indices:
			expected_columns.discard(index.get("Column_name"))

		if expected_columns:
			self.fail(f"Expected db index on these columns: {', '.join(expected_columns)}")

	def test_check_stock_uom_with_bin(self):
		# this item has opening stock and stock_uom set in self.globalTestRecords["Item"].
		item = frappe.get_doc("Item", "_Test Item")
		item.stock_uom = "Gram"
		self.assertRaises(frappe.ValidationError, item.save)

	def test_check_stock_uom_with_bin_no_sle(self):
		from hisaabdari.stock.stock_balance import update_bin_qty

		item = create_item("_Item with bin qty")
		item.stock_uom = "Gram"
		item.save()

		update_bin_qty(item.item_code, "_Test Warehouse - _TC", {"reserved_qty": 10})

		item.stock_uom = "Kilometer"
		self.assertRaises(frappe.ValidationError, item.save)

		update_bin_qty(item.item_code, "_Test Warehouse - _TC", {"reserved_qty": 0})

		item.load_from_db()
		item.stock_uom = "Kilometer"
		try:
			item.save()
		except frappe.ValidationError as e:
			self.fail(f"UoM change not allowed even though no SLE / BIN with positive qty exists: {e}")

	def test_stock_uom_can_change_after_stock_is_cancelled(self):
		item = create_item(frappe.generate_hash(length=20))
		make_stock_entry(item_code=item.name, target="_Test Warehouse - _TC", qty=5, basic_rate=10).cancel()

		item.reload()
		item.stock_uom = "Gram"
		item.save()

		self.assertEqual(frappe.db.get_value("Bin", {"item_code": item.name}, "stock_uom"), "Gram")

	def test_erasure_of_old_conversions(self):
		item = create_item("_item change uom")
		item.stock_uom = "Gram"
		item.append("uoms", frappe._dict(uom="Box", conversion_factor=2))
		item.save()
		item.reload()
		item.stock_uom = "Nos"
		item.save()
		self.assertEqual(
			[(row.uom, row.conversion_factor) for row in item.uoms],
			[("Nos", 1)],
		)

	def test_validate_stock_item(self):
		self.assertRaises(frappe.ValidationError, validate_is_stock_item, "_Test Non Stock Item")

		try:
			validate_is_stock_item("_Test Item")
		except frappe.ValidationError as e:
			self.fail(f"stock item considered non-stock item: {e}")

	def test_serial_and_batch_flags_blocked_when_not_activated(self):
		serial_item = make_item("_Test Serial Activation Item", {"has_serial_no": 1})
		batch_item = make_item("_Test Batch Activation Item", {"has_batch_no": 1, "create_new_batch": 1})
		plain_item = make_item("_Test Serial Batch Plain Item")

		# set directly as test data already has serial / batch records blocking the settings save
		frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 0)
		self.addCleanup(
			frappe.db.set_single_value, "Stock Settings", "enable_serial_and_batch_no_for_item", 1
		)

		for fieldname in ("has_serial_no", "has_batch_no"):
			with self.assertRaisesRegex(frappe.ValidationError, "Activate Serial / Batch No for Item"):
				make_item(f"_Test New {fieldname} Item", {fieldname: 1})

			item = frappe.get_doc("Item", plain_item.name)
			item.set(fieldname, 1)
			with self.assertRaisesRegex(frappe.ValidationError, "Activate Serial / Batch No for Item"):
				item.save()

		# items already tracking serial / batch stay editable
		for item in (serial_item, batch_item):
			item.reload()
			item.description = "Updated after deactivation"
			item.save()

	@ERPNextTestSuite.change_settings("Stock Settings", {"item_naming_by": "Naming Series"})
	def test_autoname_series(self):
		item = frappe.new_doc("Item")
		item.item_group = "All Item Groups"
		item.save()  # if item code saved without item_code then series worked

	@ERPNextTestSuite.change_settings("Stock Settings", {"allow_negative_stock": 0})
	def test_item_wise_negative_stock(self):
		"""When global settings are disabled check that item that allows
		negative stock can still consume material in all known stock
		transactions that consume inventory."""
		from hisaabdari.stock.stock_ledger import is_negative_stock_allowed

		item = make_item("_TestNegativeItemSetting", {"allow_negative_stock": 1, "valuation_rate": 100})
		self.assertTrue(is_negative_stock_allowed(item_code=item.name))

		self.consume_item_code_with_differet_stock_transactions(item_code=item.name)

	@ERPNextTestSuite.change_settings("Stock Settings", {"allow_negative_stock": 0})
	def test_backdated_negative_stock(self):
		"""same as test above but backdated entries"""
		from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		item = make_item("_TestNegativeItemSetting", {"allow_negative_stock": 1, "valuation_rate": 100})

		# create a future entry so all new entries are backdated
		make_stock_entry(
			qty=1, item_code=item.name, target="_Test Warehouse - _TC", posting_date=add_days(today(), 5)
		)
		self.consume_item_code_with_differet_stock_transactions(item_code=item.name)

	def test_retain_sample(self):
		frappe.db.set_value("Company", "_Test Company", "sample_retention_warehouse", "_Test Warehouse - _TC")
		item = make_item("_TestRetainSample", {"has_batch_no": 1, "retain_sample": 1, "sample_quantity": 1})

		self.assertEqual(item.has_batch_no, 1)
		self.assertEqual(item.retain_sample, 1)
		self.assertEqual(item.sample_quantity, 1)

		item.has_batch_no = None
		item.save()
		self.assertEqual(item.retain_sample, False)
		self.assertEqual(item.sample_quantity, 0)
		item.delete()

	def consume_item_code_with_differet_stock_transactions(
		self, item_code, warehouse="_Test Warehouse - _TC"
	):
		from hisaabdari.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
		from hisaabdari.stock.doctype.delivery_note.test_delivery_note import create_delivery_note
		from hisaabdari.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt
		from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		typical_args = {"item_code": item_code, "warehouse": warehouse}

		create_delivery_note(**typical_args)
		create_sales_invoice(update_stock=1, **typical_args)
		make_stock_entry(item_code=item_code, source=warehouse, qty=1, purpose="Material Issue")
		make_stock_entry(item_code=item_code, source=warehouse, target="Stores - _TC", qty=1)
		# standalone return
		make_purchase_receipt(is_return=True, qty=-1, **typical_args)

	def test_item_dashboard(self):
		from hisaabdari.stock.dashboard.item_dashboard import get_data

		self.assertTrue(get_data(item_code="_Test Item"))
		self.assertTrue(get_data(warehouse="_Test Warehouse - _TC"))
		self.assertTrue(get_data(item_group="All Item Groups"))

	def test_item_dashboard_applies_item_user_permissions(self):
		from frappe.permissions import add_user_permission

		from hisaabdari.stock.dashboard.item_dashboard import get_data

		allowed, restricted = (make_item(properties={"is_stock_item": 1}).name for _ in range(2))
		for item_code in (allowed, restricted):
			make_stock_entry(item_code=item_code, target="_Test Warehouse - _TC", qty=1, basic_rate=100)

		user = frappe.get_doc("User", "test@example.com")
		user.add_roles("Stock User")
		add_user_permission("Item", allowed, user.name)

		with self.set_user(user.name):
			self.assertTrue(get_data(item_code=allowed))
			self.assertFalse(get_data(item_code=restricted))

	def test_item_dashboard_group_warehouse_includes_children(self):
		from hisaabdari.stock.dashboard.item_dashboard import get_data
		from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

		group = create_warehouse("_Test Dashboard Group", {"is_group": 1})
		child = create_warehouse("_Test Dashboard Child", {"parent_warehouse": group})
		item_code = make_item(properties={"is_stock_item": 1}).name
		make_stock_entry(item_code=item_code, target=child, qty=1, basic_rate=100)

		rows = get_data(item_code=item_code, warehouse=group)
		self.assertEqual([row.warehouse for row in rows], [child])

	def test_item_type_field_change(self):
		"""Check if critical fields like `is_stock_item`, `has_batch_no` are not changed if transactions exist."""
		from hisaabdari.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
		from hisaabdari.stock.doctype.delivery_note.test_delivery_note import create_delivery_note
		from hisaabdari.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt
		from hisaabdari.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		transaction_creators = [
			lambda i: make_purchase_receipt(item_code=i),
			lambda i: make_purchase_invoice(item_code=i, update_stock=1),
			lambda i: make_stock_entry(item_code=i, qty=1, target="_Test Warehouse - _TC"),
			lambda i: create_delivery_note(item_code=i),
		]

		properties = {"has_batch_no": 0, "allow_negative_stock": 1, "valuation_rate": 10}
		for transaction_creator in transaction_creators:
			item = make_item(properties=properties)
			transaction = transaction_creator(item.name)
			item.has_batch_no = 1
			self.assertRaises(frappe.ValidationError, item.save)

			transaction.cancel()
			# should be allowed now
			item.reload()
			item.has_batch_no = 1
			item.save()

	def test_customer_codes_length(self):
		"""Check if item code with special characters are allowed."""
		item = make_item(properties={"item_code": "Test Item Code With Special Characters"})
		for _row in range(3):
			item.append("customer_items", {"ref_code": frappe.generate_hash("", 120)})
		item.save()
		self.assertTrue(len(item.customer_code) > 140)

	def test_search_fields_for_item(self):
		from hisaabdari.controllers.queries import item_query

		make_property_setter("Item", None, "search_fields", "item_name", "Data", for_doctype="Doctype")

		item = make_item(properties={"item_name": "Test Item", "description": "Test Description"})
		data = item_query("Item", "Test Item", "", 0, 20, filters={"item_name": "Test Item"}, as_dict=True)
		self.assertEqual(data[0].name, item.name)
		self.assertEqual(data[0].item_name, item.item_name)
		self.assertTrue("description" not in data[0])

		make_property_setter(
			"Item", None, "search_fields", "item_name, description", "Data", for_doctype="Doctype"
		)
		data = item_query("Item", "Test Item", "", 0, 20, filters={"item_name": "Test Item"}, as_dict=True)
		self.assertEqual(data[0].name, item.name)
		self.assertEqual(data[0].item_name, item.item_name)
		self.assertEqual(data[0].description, item.description)
		self.assertTrue("description" in data[0])

	def test_group_warehouse_for_reorder_item(self):
		from hisaabdari.stock.doctype.warehouse.test_warehouse import create_warehouse

		item_doc = make_item("_Test Group Warehouse For Reorder Item", {"is_stock_item": 1})
		warehouse = create_warehouse("_Test Warehouse - _TC")
		warehouse_doc = frappe.get_doc("Warehouse", warehouse)
		warehouse_doc.db_set("parent_warehouse", "")

		item_doc.append(
			"reorder_levels",
			{
				"warehouse": warehouse,
				"warehouse_reorder_level": 10,
				"warehouse_reorder_qty": 100,
				"material_request_type": "Purchase",
				"warehouse_group": "_Test Warehouse Group - _TC",
			},
		)

		self.assertRaises(frappe.ValidationError, item_doc.save)

	def test_cannot_unset_serialized_while_bundle_exists(self):
		from hisaabdari.stock.doctype.serial_and_batch_bundle.test_serial_and_batch_bundle import (
			make_serial_batch_bundle,
		)

		item = make_item(
			properties={"has_serial_no": 1, "is_stock_item": 1, "serial_no_series": "TSN-UNSET-.####"}
		).name

		serial_no = f"{item}-SN-01"
		frappe.get_doc(
			{"doctype": "Serial No", "serial_no": serial_no, "item_code": item, "company": "_Test Company"}
		).insert()

		# A draft (unsubmitted) Serial and Batch Bundle for the item must block the change.
		bundle = make_serial_batch_bundle(
			{
				"item_code": item,
				"warehouse": "_Test Warehouse - _TC",
				"company": "_Test Company",
				"qty": 1,
				"rate": 100,
				"voucher_type": "Stock Entry",
				"serial_nos": [serial_no],
				"type_of_transaction": "Inward",
				"do_not_submit": True,
				"ignore_sabb_validation": True,
			}
		)

		doc = frappe.get_doc("Item", item)
		doc.has_serial_no = 0
		self.assertRaises(frappe.ValidationError, doc.save)

		# Once the bundle is removed, the item can be made non-serialized.
		frappe.delete_doc("Serial and Batch Bundle", bundle.name, force=True)
		doc = frappe.get_doc("Item", item)
		doc.has_serial_no = 0
		doc.save()
		self.assertEqual(frappe.db.get_value("Item", item, "has_serial_no"), 0)

	def test_opening_stock_requires_serial_and_batch_settings(self):
		setups = (
			({"has_serial_no": 1}, "Serial Number Series"),
			({"has_batch_no": 1, "create_new_batch": 0}, "Automatically Create New Batch"),
		)
		for properties, message in setups:
			with self.subTest(properties=properties), self.assertRaisesRegex(frappe.ValidationError, message):
				make_item(
					properties={"is_stock_item": 1, "opening_stock": 5, "valuation_rate": 100, **properties}
				)

	def test_opening_stock_for_batch_without_series(self):
		item = make_item(
			properties={
				"is_stock_item": 1,
				"has_batch_no": 1,
				"create_new_batch": 1,
				"opening_stock": 5,
				"valuation_rate": 100,
				"item_defaults": [{"company": "_Test Company", "default_warehouse": "_Test Warehouse - _TC"}],
			}
		)

		actual_qty = frappe.db.get_value(
			"Stock Ledger Entry", {"item_code": item.name, "is_cancelled": 0}, "actual_qty"
		)
		self.assertEqual(actual_qty, 5)

	@ERPNextTestSuite.change_settings("Global Defaults", {"default_company": "_Test Company"})
	def test_opening_stock_for_serial_batch(self):
		items = {
			"Test Opening Stock for Serial No": {
				"has_serial_no": 1,
				"opening_stock": 5,
				"serial_no_series": "SN-TOPN-.####",
				"valuation_rate": 100,
			},
			"Test Opening Stock for Batch No": {
				"has_batch_no": 1,
				"opening_stock": 5,
				"batch_number_series": "BCH-TOPN-.####",
				"valuation_rate": 100,
				"create_new_batch": 1,
			},
			"Test Opening Stock for Serial and Batch No": {
				"has_serial_no": 1,
				"has_batch_no": 1,
				"opening_stock": 5,
				"batch_number_series": "SN-BCH-TOPN-.####",
				"serial_no_series": "BCH-SN-TOPN-.####",
				"valuation_rate": 100,
				"create_new_batch": 1,
			},
		}

		for item_code, properties in items.items():
			make_item(item_code, properties)

			stock_entry_bundle = frappe.db.get_value(
				"Stock Entry Detail", {"docstatus": 1, "item_code": item_code}, "serial_and_batch_bundle"
			)
			self.assertFalse(stock_entry_bundle)

			serial_and_batch_bundle = frappe.db.get_value(
				"Stock Ledger Entry",
				{
					"voucher_type": "Stock Reconciliation",
					"is_cancelled": 0,
					"item_code": item_code,
				},
				"serial_and_batch_bundle",
			)
			self.assertTrue(serial_and_batch_bundle)

			sabb_qty = frappe.db.get_value("Serial and Batch Bundle", serial_and_batch_bundle, "total_qty")
			self.assertEqual(abs(sabb_qty), properties["opening_stock"])


def create_item(
	item_code,
	is_stock_item=1,
	valuation_rate=0,
	stock_uom="Nos",
	warehouse="_Test Warehouse - _TC",
	is_customer_provided_item=None,
	customer=None,
	is_purchase_item=None,
	opening_stock=0,
	is_fixed_asset=0,
	asset_category=None,
	buying_cost_center=None,
	selling_cost_center=None,
	company="_Test Company",
):
	if not frappe.db.exists("Item", item_code):
		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = item_code
		item.description = item_code
		item.item_group = "All Item Groups"
		item.stock_uom = stock_uom
		item.is_stock_item = is_stock_item
		item.opening_stock = opening_stock
		item.valuation_rate = valuation_rate
		item.is_purchase_item = is_purchase_item
		item.is_customer_provided_item = is_customer_provided_item
		item.customer = customer or ""
		item.append(
			"item_defaults",
			{
				"default_warehouse": warehouse,
				"company": company,
				"selling_cost_center": selling_cost_center,
				"buying_cost_center": buying_cost_center,
			},
		)
		item.save()
	else:
		item = frappe.get_doc("Item", item_code)
	return item
