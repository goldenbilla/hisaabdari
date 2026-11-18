// Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const CF_REPORT_NAME = "Cash Flow";

frappe.query_reports[CF_REPORT_NAME] = $.extend({}, hisaabdari.financial_statements, {
	name_field: "section",
	parent_field: "parent_section",
});

hisaabdari.utils.add_dimensions(CF_REPORT_NAME, 10);

// The last item in the array is the definition for Presentation Currency
// filter. It won't be used in cash flow for now so we pop it. Please take
// of this if you are working here.

frappe.query_reports[CF_REPORT_NAME]["filters"].splice(
	frappe.query_reports[CF_REPORT_NAME]["filters"].findIndex((f) => f.fieldname == "presentation_currency"),
	1
);

frappe.query_reports[CF_REPORT_NAME]["filters"].push(
	{
		fieldname: "group_by_dimension",
		label: __("Group by Dimension"),
		fieldtype: "Select",
		options: hisaabdari.financial_statements.get_accounting_dimension_options(),
	},
	{
		fieldname: "accumulated_values",
		label: __("Accumulated Values"),
		fieldtype: "Check",
		default: 0,
	},
	{
		fieldname: "show_opening_and_closing_balance",
		label: __("Show Opening and Closing Balance"),
		fieldtype: "Check",
		depends_on: "eval:!doc.group_by_dimension",
	}
);

frappe.query_reports[CF_REPORT_NAME]["export_hidden_cols"] = true;
