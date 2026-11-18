frappe.listview_settings["Delivery Note"] = {
	add_fields: [
		"customer",
		"customer_name",
		"base_grand_total",
		"per_billed",
		"transporter_name",
		"grand_total",
		"is_return",
		"status",
		"currency",
	],
	get_indicator: function (doc) {
		if (cint(doc.is_return) == 1 && doc.status == "Return") {
			return [__("Return"), "gray", "is_return,=,1"];
		} else if (doc.status === "Closed") {
			return [__("Closed"), "green", "status,=,Closed"];
		} else if (doc.status === "Return Issued") {
			return [__("Return Issued"), "grey", "status,=,Return Issued"];
		} else if (flt(doc.per_billed) == 0) {
			return [__("To Bill"), "orange", "status,=,To Bill"];
		} else if (flt(doc.per_billed, 2) > 0 && flt(doc.per_billed, 2) < 100) {
			return [__("Partially Billed"), "yellow", "status,=,Partially Billed"];
		} else if (flt(doc.per_billed, 2) === 100) {
			return [__("Completed"), "green", "status,=,Completed"];
		}
	},
	onload: function (doclist) {
	},
};
