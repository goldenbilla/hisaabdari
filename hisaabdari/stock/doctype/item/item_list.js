frappe.listview_settings["Item"] = {
	add_fields: [
		"item_name",
		"stock_uom",
		"item_group",
		"image",
		"end_of_life",
		"disabled",
		"is_stock_item",
		"is_sales_item",
		"is_purchase_item",
	],
	filters: [["disabled", "=", "0"]],

	formatters: {
		is_stock_item: function (value, df, doc) {
			if (doc.is_stock_item) return __("Stock");
			return __("Service");
		},

		is_sales_item: function (value, df, doc) {
			const sales = cint(doc.is_sales_item);
			const purchases = cint(doc.is_purchase_item);
			if (sales && purchases) return __("Sales & Purchase");
			if (sales) return __("Sales");
			if (purchases) return __("Purchase");
			return "—";
		},
	},

	onload: function (listview) {
		if (listview.view === "List") {
			listview.columns = listview.columns.map((col) => {
				if (!col.df) return col;
				const renames = {
					is_stock_item: __("Item Type"),
					is_sales_item: __("Purpose"),
					stock_uom: __("UOM"),
				};
				if (col.df.fieldname in renames) {
					return { ...col, df: { ...col.df, label: renames[col.df.fieldname] } };
				}
				return col;
			});
			listview.render_header(true);
		}
	},

	get_indicator: function (doc) {
		if (doc.disabled) {
			return [__("Disabled"), "grey", "disabled,=,Yes"];
		} else if (doc.end_of_life && doc.end_of_life < frappe.datetime.get_today()) {
			return [__("Expired"), "grey", "end_of_life,<,Today"];
		}
	},

	reports: [
		{
			name: "Stock Summary",
			route: "/app/stock-balance",
		},
		{
			name: "Stock Ledger",
			report_type: "Script Report",
		},
		{
			name: "Stock Balance",
			report_type: "Script Report",
		},
		{
			name: "Stock Projected Qty",
			report_type: "Script Report",
		},
	],
};

frappe.help.youtube_id["Item"] = "qXaEwld4_Ps";
