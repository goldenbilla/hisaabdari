// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// render
frappe.listview_settings["Sales Invoice"] = {
	add_fields: [
		"customer",
		"customer_name",
		"base_grand_total",
		"outstanding_amount",
		"due_date",
		"company",
		"currency",
		"is_return",
	],
	get_indicator: function (doc) {
		const status_colors = {
			Draft: "red",
			Unpaid: "orange",
			Paid: "green",
			Return: "gray",
			"Credit Note Issued": "gray",
			Overdue: "red",
			"Partly Paid": "yellow",
			"Internal Transfer": "darkgrey",
		};
		return [__(doc.status), status_colors[doc.status], "status,=," + doc.status];
	},
	right_column: "grand_total",
};
