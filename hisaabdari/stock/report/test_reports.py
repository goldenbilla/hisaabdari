from frappe.utils.make_random import get_random

from hisaabdari.tests.utils import ERPNextTestSuite, ReportFilters, ReportName, execute_script_report

DEFAULT_FILTERS = {
	"company": "_Test Company",
	"from_date": "2010-01-01",
	"to_date": "2030-01-01",
}


batch = get_random("Batch")

REPORT_FILTER_TEST_CASES: list[tuple[ReportName, ReportFilters]] = [
	("Stock Ledger", {"_optional": True}),
	("Stock Ledger", {"batch_no": batch}),
	("Stock Ledger", {"item_code": ["_Test Item"], "warehouse": ["_Test Warehouse - _TC"]}),
	(
		"Stock Balance",
		{
			"item_code": ["_Test Item"],
			"warehouse": ["_Test Warehouse - _TC"],
			"item_group": "_Test Item Group",
		},
	),
	("Stock Projected Qty", {"_optional": True}),
	("Batch-Wise Balance History", {}),
	("Itemwise Recommended Reorder Level", {"item_group": "All Item Groups"}),
	("COGS By Item Group", {}),
	(
		"Stock Analytics",
		{
			"from_date": "2021-01-01",
			"to_date": "2021-12-31",
			"value_quantity": "Quantity",
			"_optional": True,
		},
	),
	("Warehouse wise Item Balance Age and Value", {"_optional": True}),
	(
		"Total Stock Summary",
		{
			"group_by": "warehouse",
		},
	),
	("Item Wise Consumption", {}),
	("Item Prices", {"items": "Enabled Items only"}),
	("Delayed Item Report", {"based_on": "Sales Invoice"}),
	("Delayed Item Report", {"based_on": "Delivery Note"}),
	("Stock Ageing", {"range": "30, 60, 90", "_optional": True}),
]

OPTIONAL_FILTERS = {
	"warehouse": "_Test Warehouse - _TC",
	"item": "_Test Item",
	"item_group": "_Test Item Group",
}


class TestReports(ERPNextTestSuite):
	def test_execute_all_stock_reports(self):
		"""Test that all script report in stock modules are executable with supported filters"""
		for report, filter in REPORT_FILTER_TEST_CASES:
			with self.subTest(report=report):
				execute_script_report(
					report_name=report,
					module="Stock",
					filters=filter,
					default_filters=DEFAULT_FILTERS,
					optional_filters=OPTIONAL_FILTERS if filter.get("_optional") else None,
				)
