frappe.listview_settings["Bank Reconciliation"] = {
	add_fields: ["status"],
	get_indicator: function (doc) {
		if (doc.status === "Closed") return [__("Closed"), "green", "status,=,Closed"];
		return [__("Open"), "orange", "status,=,Open"];
	},
};
