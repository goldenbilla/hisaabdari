// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Supplier", {
	restrict_to_companies(frm) {
		if (!frm.doc.restrict_to_companies) {
			frm.set_value("allowed_companies", []);
		}
	},

	setup: function (frm) {
		frm.set_query("allowed_companies", () => ({
			query: "hisaabdari.stock.doctype.company_restriction.company_restriction.company_query",
		}));
		frm.set_query("default_price_list", { buying: 1 });
		if (frm.doc.__islocal == 1) {
			frm.set_value("represents_company", "");
		}
		frm.set_query("account", "accounts", function (doc, cdt, cdn) {
			let d = locals[cdt][cdn];
			return {
				filters: {
					account_type: "Payable",
					root_type: "Liability",
					company: d.company,
					is_group: 0,
					account_currency: hisaabdari.utils.get_party_account_currency(doc, d.company),
				},
			};
		});

		frm.set_query("advance_account", "accounts", function (doc, cdt, cdn) {
			let d = locals[cdt][cdn];
			return {
				filters: {
					account_type: "Payable",
					root_type: "Asset",
					company: d.company,
					is_group: 0,
				},
			};
		});

		frm.set_query("default_bank_account", function () {
			return {
				filters: {
					is_company_account: 1,
				},
			};
		});

		frm.set_query("supplier_primary_contact", function (doc) {
			return {
				query: "hisaabdari.buying.doctype.supplier.supplier.get_supplier_primary",
				filters: {
					supplier: doc.name,
					type: "Contact",
				},
			};
		});

		frm.set_query("supplier_primary_address", function (doc) {
			return {
				query: "hisaabdari.buying.doctype.supplier.supplier.get_supplier_primary",
				filters: {
					supplier: doc.name,
					type: "Address",
				},
			};
		});

		frm.make_methods = {
			"Purchase Order": () =>
				frappe.model.with_doctype("Purchase Order", function () {
					const po = frappe.model.get_new_doc("Purchase Order");
					po.supplier = frm.doc.name;
					frappe.set_route("Form", "Purchase Order", po.name);
				}),
			"Purchase Invoice": () =>
				frappe.model.with_doctype("Purchase Invoice", function () {
					const pi = frappe.model.get_new_doc("Purchase Invoice");
					pi.supplier = frm.doc.name;
					frappe.set_route("Form", "Purchase Invoice", pi.name);
				}),
			"Bank Account": () => hisaabdari.utils.make_bank_account(frm.doc.doctype, frm.doc.name),
		};
	},

	supplier_group(frm) {
		if (frm.doc.supplier_group) {
			frm.trigger("get_supplier_group_details");
		}
	},

	refresh: function (frm) {
		if (frappe.defaults.get_default("supp_master_name") != "Naming Series") {
			frm.toggle_display("naming_series", false);
		} else {
			hisaabdari.toggle_naming_series();
		}

		if (frm.doc.__islocal) {
			hide_field(["address_html", "contact_html"]);
			frappe.contacts.clear_address_and_contact(frm);
		} else {
			unhide_field(["address_html", "contact_html"]);
			frappe.contacts.render_address_and_contact(frm);

			// custom buttons
			frm.add_custom_button(
				__("Accounting Ledger"),
				function () {
					frappe.set_route("query-report", "General Ledger", {
						party_type: "Supplier",
						party: frm.doc.name,
						party_name: frm.doc.supplier_name,
					});
				},
				__("View")
			);

			frm.add_custom_button(
				__("Accounts Payable"),
				function () {
					frappe.set_route("query-report", "Accounts Payable", {
						party_type: "Supplier",
						party: frm.doc.name,
					});
				},
				__("View")
			);

			for (const doctype in frm.make_methods) {
				frm.add_custom_button(__(doctype), frm.make_methods[doctype], __("Create"));
			}

			if (frm.doc.supplier_group) {
				frm.add_custom_button(
					__("Get Supplier Group Details"),
					function () {
						frm.trigger("get_supplier_group_details");
					},
					__("Actions")
				);
			}

			// indicators
			hisaabdari.utils.set_party_dashboard_indicators(frm);
		}
	},

	get_supplier_group_details: function (frm) {
		frappe.call({
			method: "get_supplier_group_details",
			doc: frm.doc,
			callback: function () {
				frm.refresh();
			},
		});
	},

	supplier_primary_address: function (frm) {
		if (frm.doc.supplier_primary_address) {
			frappe.call({
				method: "frappe.contacts.doctype.address.address.get_address_display",
				args: {
					address_dict: frm.doc.supplier_primary_address,
				},
				callback: function (r) {
					frm.set_value("primary_address", frappe.utils.html2text(r.message));
				},
			});
		}
		if (!frm.doc.supplier_primary_address) {
			frm.set_value("primary_address", "");
		}
	},

	supplier_primary_contact: function (frm) {
		if (!frm.doc.supplier_primary_contact) {
			frm.set_value("mobile_no", "");
			frm.set_value("email_id", "");
		}
	},

	is_internal_supplier: function (frm) {
		if (frm.doc.is_internal_supplier == 1) {
			frm.toggle_reqd("represents_company", true);
		} else {
			frm.toggle_reqd("represents_company", false);
			frm.set_value("represents_company", "");
			frm.set_value("companies", []);
		}
	},
});
