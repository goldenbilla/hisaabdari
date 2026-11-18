// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
frappe.ui.form.on("Bank", {
	refresh: function (frm) {
		frm.toggle_display(["address_html", "contact_html"], !frm.doc.__islocal);

		if (frm.doc.__islocal) {
			frm.set_df_property("address_and_contact", "hidden", 1);
			frappe.contacts.clear_address_and_contact(frm);
		} else {
			frm.set_df_property("address_and_contact", "hidden", 0);
			frappe.contacts.render_address_and_contact(frm);
		}
	},
});
