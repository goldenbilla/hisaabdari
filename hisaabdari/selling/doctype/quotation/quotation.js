// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.cscript.tax_table = "Sales Taxes and Charges";

hisaabdari.accounts.taxes.setup_tax_validations("Sales Taxes and Charges Template");
hisaabdari.accounts.taxes.setup_tax_filters("Sales Taxes and Charges");
hisaabdari.pre_sales.set_as_lost("Quotation");
hisaabdari.sales_common.setup_selling_controller();

frappe.ui.form.on("Quotation", {
	setup: function (frm) {
		(frm.custom_make_buttons = {
			"Sales Order": "Sales Order",
		}),
			frm.set_query("quotation_to", function () {
				return {
					filters: {
						name: ["in", ["Customer"]],
					},
				};
			});

		frm.set_df_property("packed_items", "cannot_add_rows", true);
		frm.set_df_property("packed_items", "cannot_delete_rows", true);

		frm.set_query("serial_and_batch_bundle", "packed_items", (doc, cdt, cdn) => {
			let row = locals[cdt][cdn];
			return {
				filters: {
					item_code: row.item_code,
					voucher_type: doc.doctype,
					voucher_no: ["in", [doc.name, ""]],
					is_cancelled: 0,
				},
			};
		});

		frm.set_query("warehouse", "items", (doc, cdt, cdn) => {
			return {
				filters: {
					company: doc.company,
					is_group: 0,
				},
			};
		});

		frm.set_indicator_formatter("item_code", function (doc) {
			return !doc.qty && frm.doc.has_unit_price_items ? "yellow" : "";
		});
	},

	refresh: function (frm) {
		frm.trigger("set_label");
		frm.trigger("set_dynamic_field_label");

		if (frm.doc.docstatus === 0) {
			hisaabdari.set_unit_price_items_note(frm);
		}

		let sbb_field = frm.get_docfield("packed_items", "serial_and_batch_bundle");
		if (sbb_field) {
			sbb_field.get_route_options_for_new_doc = (row) => {
				return {
					item_code: row.doc.item_code,
					warehouse: row.doc.warehouse,
					voucher_type: frm.doc.doctype,
				};
			};
		}
	},

	quotation_to: function (frm) {
		frm.trigger("set_label");
		frm.trigger("toggle_reqd_lead_customer");
		frm.trigger("set_dynamic_field_label");
		// frm.set_value("party_name", ""); // removed to set party_name from url for crm integration
		frm.set_value("customer_name", "");
	},

	set_label: function (frm) {
		frm.fields_dict.customer_address.set_label(__(frm.doc.quotation_to + " Address"));
	},
});

hisaabdari.selling.QuotationController = class QuotationController extends hisaabdari.selling.SellingController {
	onload(doc, dt, dn) {
		super.onload(doc, dt, dn);
	}
	party_name() {
		var me = this;
		hisaabdari.utils.get_party_details(this.frm, null, null, function () {
			me.apply_price_list();
		});
	}
	refresh(doc, dt, dn) {
		super.refresh(doc, dt, dn);
		frappe.dynamic_link = {
			doc: this.frm.doc,
			fieldname: "party_name",
			doctype: doc.quotation_to,
		};

		var me = this;

		if (doc.__islocal && !doc.valid_till) {
			if (frappe.boot.sysdefaults.quotation_valid_till) {
				this.frm.set_value(
					"valid_till",
					frappe.datetime.add_days(
						doc.transaction_date,
						frappe.boot.sysdefaults.quotation_valid_till
					)
				);
			} else {
				this.frm.set_value("valid_till", frappe.datetime.add_months(doc.transaction_date, 1));
			}
		}

		if (doc.docstatus == 1 && !["Lost", "Ordered"].includes(doc.status)) {
			if (
				frappe.model.can_create("Sales Order") &&
				(frappe.boot.sysdefaults.allow_sales_order_creation_for_expired_quotation ||
					!doc.valid_till ||
					frappe.datetime.get_diff(doc.valid_till, frappe.datetime.get_today()) >= 0)
			) {
				this.frm.add_custom_button(__("Sales Order"), () => this.make_sales_order(), __("Create"));
				cur_frm.page.set_inner_btn_group_as_primary(__("Create"));
				this.frm.add_custom_button(__("Update Items"), () => {
					hisaabdari.utils.update_child_items({
						frm: this.frm,
						child_docname: "items",
						cannot_add_row: false,
					});
				});
			}

			if (doc.status !== "Ordered" && this.frm.has_perm("write")) {
				this.frm.add_custom_button(__("Set as Lost"), () => {
					this.frm.trigger("set_as_lost_dialog");
				});
			}
		}

		this.toggle_reqd_lead_customer();
	}

	make_sales_order() {
		var me = this;

		let has_alternative_item = this.frm.doc.items.some((item) => item.is_alternative);
		if (has_alternative_item) {
			this.show_alternative_items_dialog();
		} else {
			frappe.model.open_mapped_doc({
				method: "hisaabdari.selling.doctype.quotation.quotation.make_sales_order",
				frm: me.frm,
			});
		}
	}

	set_dynamic_field_label() {
		if (this.frm.doc.quotation_to == "Customer") {
			this.frm.set_df_property("party_name", "label", "Customer");
			this.frm.fields_dict.party_name.get_query = hisaabdari.queries.customer;
		}
	}

	toggle_reqd_lead_customer() {
		var me = this;

		// to overwrite the customer_filter trigger from queries.js
		this.frm.toggle_reqd("party_name", this.frm.doc.quotation_to);
		this.frm.set_query("customer_address", this.address_query);
		this.frm.set_query("shipping_address_name", this.address_query);
	}

	tc_name() {
		this.get_terms();
	}

	address_query(doc) {
		return {
			query: "frappe.contacts.doctype.address.address.address_query",
			filters: {
				link_doctype: frappe.dynamic_link.doctype,
				link_name: doc.party_name,
			},
		};
	}

	validate_company_and_party(party_field) {
		if (!this.frm.doc.quotation_to) {
			frappe.msgprint(
				__("Please select a value for {0} quotation_to {1}", [
					this.frm.doc.doctype,
					this.frm.doc.name,
				])
			);
			return false;
		} else {
			return super.validate_company_and_party(party_field);
		}
	}

	show_alternative_items_dialog() {
		let me = this;

		const table_fields = [
			{
				fieldtype: "Data",
				fieldname: "name",
				label: __("Name"),
				read_only: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "item_code",
				options: "Item",
				label: __("Item Code"),
				read_only: 1,
				in_list_view: 1,
				columns: 2,
				formatter: (value, df, options, doc) => {
					return doc.is_alternative ? `<span class="indicator yellow">${value}</span>` : value;
				},
			},
			{
				fieldtype: "Text Editor",
				fieldname: "description",
				label: __("Description"),
				in_list_view: 1,
				read_only: 1,
			},
			{
				fieldtype: "Currency",
				fieldname: "amount",
				label: __("Amount"),
				options: "currency",
				in_list_view: 1,
				read_only: 1,
			},
			{
				fieldtype: "Check",
				fieldname: "is_alternative",
				label: __("Is Alternative"),
				read_only: 1,
			},
		];

		this.data = this.frm.doc.items
			.filter((item) => item.is_alternative || item.has_alternative_item)
			.map((item) => {
				return {
					name: item.name,
					item_code: item.item_code,
					description: item.description,
					amount: item.amount,
					is_alternative: item.is_alternative,
				};
			});

		const dialog = new frappe.ui.Dialog({
			title: __("Select Alternative Items for Sales Order"),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					read_only: 1,
				},
				{
					fieldname: "alternative_items",
					fieldtype: "Table",
					cannot_add_rows: true,
					cannot_delete_rows: true,
					in_place_edit: true,
					reqd: 1,
					data: this.data,
					description: __("Select an item from each set to be used in the Sales Order."),
					get_data: () => {
						return this.data;
					},
					fields: table_fields,
				},
			],
			primary_action: function () {
				frappe.model.open_mapped_doc({
					method: "hisaabdari.selling.doctype.quotation.quotation.make_sales_order",
					frm: me.frm,
					args: {
						selected_items: dialog.fields_dict.alternative_items.grid.get_selected_children(),
					},
				});
				dialog.hide();
			},
			primary_action_label: __("Continue"),
		});

		dialog.fields_dict.info.$wrapper.html(
			`<p class="small text-muted">
				<span class="indicator yellow"></span>
				${__("Alternative Items")}
			</p>`
		);
		dialog.show();
	}
};

cur_frm.script_manager.make(hisaabdari.selling.QuotationController);

frappe.ui.form.on(
	"Quotation Item",
	"items_on_form_rendered",
	"packed_items_on_form_rendered",
	function (frm, cdt, cdn) {
		// enable tax_amount field if Actual
	}
);

frappe.ui.form.on("Quotation Item", "stock_balance", function (frm, cdt, cdn) {
	var d = frappe.model.get_doc(cdt, cdn);
	frappe.route_options = { item_code: d.item_code };
	frappe.set_route("query-report", "Stock Balance");
});
