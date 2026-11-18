// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

const PL_REPORT_NAME = "Profit and Loss Statement";

frappe.query_reports[PL_REPORT_NAME] = $.extend({}, hisaabdari.financial_statements);

hisaabdari.utils.add_dimensions(PL_REPORT_NAME, 10);

frappe.query_reports[PL_REPORT_NAME]["filters"].push(
	{
		fieldname: "group_by_dimension",
		label: __("Group by Dimension"),
		fieldtype: "Select",
		options: hisaabdari.financial_statements.get_accounting_dimension_options(),
	},
	{
		fieldname: "selected_view",
		label: __("Select View"),
		fieldtype: "Select",
		options: [
			{ value: "Report", label: __("Report View") },
			{ value: "Growth", label: __("Growth View") },
			{ value: "Margin", label: __("Margin View") },
		],
		default: "Report",
		reqd: 1,
	},
	{
		fieldname: "accumulated_values",
		label: __("Accumulated Values"),
		fieldtype: "Check",
		default: 0,
	},
	{
		fieldname: "show_zero_values",
		label: __("Show zero values"),
		fieldtype: "Check",
	}
);

frappe.query_reports[PL_REPORT_NAME]["export_hidden_cols"] = true;
