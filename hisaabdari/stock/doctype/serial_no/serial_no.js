// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Serial No", {
	setup(frm) {
		frm.add_fetch("customer", "customer_name", "customer_name");
		frm.add_fetch("supplier", "supplier_name", "supplier_name");
		frm.add_fetch("item_code", "item_name", "item_name");
		frm.add_fetch("item_code", "description", "description");
		frm.add_fetch("item_code", "item_group", "item_group");

		frm.set_query("item_code", function () {
			return hisaabdari.queries.item({ is_stock_item: 1, has_serial_no: 1 });
		});
	},

	refresh(frm) {
		frm.toggle_enable("item_code", frm.doc.__islocal);
	},
});
