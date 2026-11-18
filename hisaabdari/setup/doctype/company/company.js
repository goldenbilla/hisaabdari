// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.company");

// Static filters (is_group / disabled / warehouse_type) live in the fields' link_filters.
const WAREHOUSE_DEFAULT_FIELDS = [
	"default_warehouse",
	"sample_retention_warehouse",
	"default_in_transit_warehouse",
	"default_warehouse_for_sales_return",
];

frappe.ui.form.on("Company", {
	onload: function (frm) {
		if (frm.doc.__islocal && frm.doc.parent_company) {
			frappe.db.get_value("Company", frm.doc.parent_company, "is_group", (r) => {
				if (!r.is_group) {
					frm.set_value("parent_company", "");
				}
			});
		}
		if (!frm.doc.__islocal) {
			frm.call("check_if_transactions_exist").then((r) => {
				frm.toggle_enable("default_currency", !r.message);
			});
		}
		if (frm.doc.__islocal) {
			frm.set_value("reporting_currency", "");
		}
	},
	setup: function (frm) {
		frm.__rename_queue = "long";

		frm.set_query("parent_company", function () {
			return {
				filters: { is_group: 1 },
			};
		});

		frm.set_query("default_selling_terms", function () {
			return { filters: { selling: 1, disabled: 0 } };
		});

		frm.set_query("default_sales_contact", function (doc) {
			return {
				query: "frappe.contacts.doctype.contact.contact.contact_query",
				filters: { link_doctype: "Company", link_name: doc.name },
			};
		});

		frm.set_query("default_buying_terms", function () {
			return { filters: { buying: 1, disabled: 0 } };
		});

		WAREHOUSE_DEFAULT_FIELDS.forEach((fieldname) => {
			frm.set_query(fieldname, function (doc) {
				return { filters: { company: doc.name } };
			});
		});
	},

	company_name: function (frm) {
		if (frm.doc.__islocal) {
			// add missing " " arg in split method
			let parts = frm.doc.company_name.split(" ");
			let abbr = $.map(parts, function (p) {
				return p ? p.substr(0, 1) : null;
			}).join("");
			frm.set_value("abbr", abbr);
		}
	},

	parent_company: function (frm) {
		var bool = frm.doc.parent_company ? true : false;
		frm.set_value("create_chart_of_accounts_based_on", bool ? "Existing Company" : "");
		frm.set_value("existing_company", bool ? frm.doc.parent_company : "");
		disbale_coa_fields(frm, bool);
	},

	date_of_commencement: function (frm) {
		if (frm.doc.date_of_commencement < frm.doc.date_of_incorporation) {
			frappe.throw(__("Date of Commencement should be greater than Date of Incorporation"));
		}
		if (!frm.doc.date_of_commencement) {
			frm.doc.date_of_incorporation = "";
		}
	},

	refresh: function (frm) {
		hisaabdari.company.setup_queries(frm);

		frm.toggle_display("address_html", !frm.is_new());

		if (!frm.is_new()) {
			frm.doc.abbr && frm.set_df_property("abbr", "read_only", 1);
			disbale_coa_fields(frm);
			frappe.contacts.render_address_and_contact(frm);

			if (frappe.perm.has_perm("Cost Center", 0, "read")) {
				frm.add_custom_button(
					__("Cost Centers"),
					function () {
						frappe.set_route("Tree", "Cost Center", { company: frm.doc.name });
					},
					__("View")
				);
			}

			if (frappe.perm.has_perm("Account", 0, "read")) {
				frm.add_custom_button(
					__("Chart of Accounts"),
					function () {
						frappe.set_route("Tree", "Account", { company: frm.doc.name });
					},
					__("View")
				);
			}

			if (frappe.perm.has_perm("Sales Taxes and Charges Template", 0, "read")) {
				frm.add_custom_button(
					__("Sales Tax Template"),
					function () {
						frappe.set_route("List", "Sales Taxes and Charges Template", {
							company: frm.doc.name,
						});
					},
					__("View")
				);
			}

			if (frappe.perm.has_perm("Purchase Taxes and Charges Template", 0, "read")) {
				frm.add_custom_button(
					__("Purchase Tax Template"),
					function () {
						frappe.set_route("List", "Purchase Taxes and Charges Template", {
							company: frm.doc.name,
						});
					},
					__("View")
				);
			}

			if (frm.has_perm("write")) {
				frm.add_custom_button(
					__("Create Tax Template"),
					function () {
						frm.trigger("make_default_tax_template");
					},
					__("Manage")
				);
			}
		}

		if (frm.doc.__islocal) {
			frm.set_value("reporting_currency", "");
		}

		hisaabdari.company.set_chart_of_accounts_options(frm.doc);
	},

	make_default_tax_template: function (frm) {
		frm.call({
			method: "create_default_tax_template",
			doc: frm.doc,
			freeze: true,
			callback: function () {
				frappe.msgprint(__("Default tax templates for sales, purchase and items are created."));
			},
		});
	},

	country: function (frm) {
		hisaabdari.company.set_chart_of_accounts_options(frm.doc);
	},
});

hisaabdari.company.set_chart_of_accounts_options = function (doc) {
	var selected_value = doc.chart_of_accounts;
	if (doc.country) {
		return frappe.call({
			method: "hisaabdari.accounts.doctype.account.chart_of_accounts.chart_of_accounts.get_charts_for_country",
			args: {
				country: doc.country,
				with_standard: true,
			},
			callback: function (r) {
				if (!r.exc) {
					set_field_options("chart_of_accounts", [""].concat(r.message).join("\n"));
					if (r.message.includes(selected_value))
						cur_frm.set_value("chart_of_accounts", selected_value);
				}
			},
		});
	}
};

hisaabdari.company.setup_queries = function (frm) {
	$.each(
		[
			["default_bank_account", { account_type: "Bank" }],
			["default_cash_account", { account_type: "Cash" }],
			["default_receivable_account", { root_type: "Asset", account_type: "Receivable" }],
			["default_payable_account", { root_type: "Liability", account_type: "Payable" }],
			["default_expense_account", { root_type: "Expense" }],
			["default_income_account", { root_type: "Income" }],
			["round_off_account", { root_type: ["in", ["Expense", "Income"]] }],
			["round_off_for_opening", { root_type: "Liability", account_type: "Round Off for Opening" }],
			["write_off_account", { root_type: "Expense" }],
			["default_discount_account", {}],
			["discount_allowed_account", { root_type: "Expense" }],
			["discount_received_account", { root_type: "Income" }],
			["exchange_gain_loss_account", { root_type: ["in", ["Expense", "Income"]] }],
			[
				"unrealized_exchange_gain_loss_account",
				{ root_type: ["in", ["Expense", "Income", "Equity", "Liability"]] },
			],
			["default_inventory_account", { account_type: "Stock" }],
			["purchase_expense_account", { root_type: "Expense" }],
			["purchase_expense_contra_account", { root_type: "Expense" }],
			["cost_center", {}],
			["round_off_cost_center", {}],
			["unrealized_profit_loss_account", { root_type: ["in", ["Liability", "Asset"]] }],
			["default_provisional_account", { root_type: ["in", ["Liability", "Asset"]] }],
			["default_advance_received_account", { root_type: "Liability", account_type: "Receivable" }],
			["default_advance_paid_account", { root_type: "Asset", account_type: "Payable" }],
			["service_expense_account", { root_type: "Expense" }],
			["expenses_added_to_stock_account", { root_type: "Expense" }],
			["expenses_added_to_stock_contra_account", { root_type: "Expense" }],
		],
		function (i, v) {
			hisaabdari.company.set_custom_query(frm, v);
		}
	);

	if (frm.doc.enable_perpetual_inventory) {
		$.each(
			[
				["stock_adjustment_account", { root_type: "Expense", account_type: "Stock Adjustment" }],
				[
					"stock_received_but_not_billed",
					{ root_type: "Liability", account_type: "Stock Received But Not Billed" },
				],
				[
					"service_received_but_not_billed",
					{ root_type: "Liability", account_type: "Service Received But Not Billed" },
				],
			],
			function (i, v) {
				hisaabdari.company.set_custom_query(frm, v);
			}
		);
	}
};

hisaabdari.company.set_custom_query = function (frm, v) {
	var filters = {
		company: frm.doc.name,
		is_group: 0,
	};

	for (var key in v[1]) {
		filters[key] = v[1][key];
	}

	frm.set_query(v[0], function () {
		return {
			filters: filters,
		};
	});
};

var disbale_coa_fields = function (frm, bool = true) {
	frm.set_df_property("create_chart_of_accounts_based_on", "read_only", bool);
	frm.set_df_property("chart_of_accounts", "read_only", bool);
	frm.set_df_property("existing_company", "read_only", bool);
};
