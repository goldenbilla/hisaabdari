// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Global Defaults", {
	validate: function (frm) {
		frm.call("get_defaults", null, (r) => {
			frappe.sys_defaults = r.message;
		});
	},
});
