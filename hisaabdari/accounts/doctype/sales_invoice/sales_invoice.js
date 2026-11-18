// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.accounts");

cur_frm.cscript.tax_table = "Sales Taxes and Charges";

hisaabdari.accounts.taxes.setup_tax_validations("Sales Invoice");
hisaabdari.accounts.payment_triggers.setup("Sales Invoice");
hisaabdari.accounts.taxes.setup_tax_filters("Sales Taxes and Charges");
hisaabdari.sales_common.setup_selling_controller();
hisaabdari.accounts.SalesInvoiceController = class SalesInvoiceController extends (
	hisaabdari.selling.SellingController
) {
	setup(doc) {
		this.setup_posting_date_time_check();
		super.setup(doc);
	}
	onload() {
		var me = this;
		super.onload();

		this.frm.ignore_doctypes_on_cancel_all = [
			"Journal Entry",
			"Payment Entry",
			"Repost Accounting Ledger",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
			"Serial and Batch Bundle",
		];

		if (!this.frm.doc.__islocal && !this.frm.doc.customer && this.frm.doc.debit_to) {
			// show debit_to in print format
			this.frm.set_df_property("debit_to", "print_hide", 0);
		}

		hisaabdari.queries.setup_queries(this.frm, "Warehouse", function () {
			return hisaabdari.queries.warehouse(me.frm.doc);
		});

		hisaabdari.queries.setup_warehouse_query(this.frm);
	}

	refresh(doc, dt, dn) {
		const me = this;
		super.refresh();
		if (this.frm?.msgbox && this.frm.msgbox.$wrapper.is(":visible")) {
			// hide new msgbox
			this.frm.msgbox.hide();
		}

		this.frm.toggle_reqd("due_date", !this.frm.doc.is_return);

		if (this.frm.doc.is_return) {
			this.frm.return_print_format = "Sales Invoice Return";
		}

		this.show_general_ledger();
		hisaabdari.accounts.ledger_preview.show_accounting_ledger_preview(this.frm);

		if (doc.update_stock) {
			this.show_stock_ledger();
			hisaabdari.accounts.ledger_preview.show_stock_ledger_preview(this.frm);
		}

		if (doc.docstatus == 1 && doc.outstanding_amount != 0 && frappe.model.can_create("Payment Entry")) {
			this.frm.add_custom_button(__("Payment"), () => this.make_payment_entry(), __("Create"));
			this.frm.page.set_inner_btn_group_as_primary(__("Create"));
		}

		if (doc.docstatus == 1 && !doc.is_return) {
			var is_delivered_by_supplier = false;

			is_delivered_by_supplier = this.frm.doc.items.some(function (item) {
				return item.is_delivered_by_supplier ? true : false;
			});

			if (
				frappe.model.can_create("Sales Invoice") &&
				(doc.outstanding_amount >= 0 || Math.abs(flt(doc.outstanding_amount)) < flt(doc.grand_total))
			) {
				this.frm.add_custom_button(
					__("Return / Credit Note"),
					this.make_sales_return.bind(this),
					__("Create")
				);
				this.frm.page.set_inner_btn_group_as_primary(__("Create"));
			}

			if (cint(doc.update_stock) != 1 && frappe.model.can_create("Delivery Note")) {
				if (!is_delivered_by_supplier) {
					const should_create_delivery_note = doc.items.some(
						(item) =>
							item.qty - item.delivered_qty > 0 &&
							!item.dn_detail &&
							!item.delivered_by_supplier
					);
					if (should_create_delivery_note) {
						this.frm.add_custom_button(
							__("Delivery Note"),
							this.frm.cscript["Make Delivery Note"],
							__("Create")
						);
					}
				}
			}
		}
		this.toggle_get_items();

		this.set_default_print_format();
		if (doc.docstatus == 1 && frappe.model.can_create("Purchase Invoice")) {
			let internal = me.frm.doc.is_internal_customer;
			if (internal) {
				let button_label =
					me.frm.doc.company === me.frm.doc.represents_company
						? "Internal Purchase Invoice"
						: "Inter Company Purchase Invoice";

				frappe.call({
					method: "hisaabdari.accounts.doctype.sales_invoice.sales_invoice.get_received_items",
					args: {
						reference_name: me.frm.doc.name,
						doctype: "Purchase Invoice",
						reference_fieldname: "sales_invoice_item",
					},
					callback: function (r) {
						if (r.exc) return;
						const received_items = r.message || {};
						// A Sales Invoice made from a Purchase Invoice links it without item references.
						const is_made_from_purchase_invoice =
							doc.inter_company_invoice_reference && $.isEmptyObject(received_items);
						const has_pending_qty = me.frm.doc.items.some(
							(item) =>
								flt(
									item.stock_qty - flt(received_items[item.name]),
									precision("stock_qty", item)
								) > 0
						);
						if (is_made_from_purchase_invoice || !has_pending_qty) return;

						me.frm.add_custom_button(
							__(button_label),
							function () {
								me.make_inter_company_invoice();
							},
							__("Create")
						);
					},
				});
			}
		}

		hisaabdari.accounts.unreconcile_payment.add_unreconcile_btn(me.frm);
	}

	on_submit(doc, dt, dn) {
		var me = this;

		super.on_submit();
		if (frappe.get_route()[0] != "Form") {
			return;
		}

		doc.items.forEach((row) => {
			if (row.delivery_note) frappe.model.clear_doc("Delivery Note", row.delivery_note);
		});
	}

	set_default_print_format() {
		// set default print format to Credit Note
		if (this.frm.doc.is_return && !this.frm.meta.default_print_format) {
			if (this.frm.return_print_format) {
				this.frm.meta._default_print_format = this.frm.meta.default_print_format;
				this.frm.meta.default_print_format = this.frm.return_print_format;
			}
		} else {
			if (this.frm.meta._default_print_format) {
				this.frm.meta.default_print_format = this.frm.meta._default_print_format;
				this.frm.meta._default_print_format = null;
			} else if (this.frm.return_print_format == this.frm.meta.default_print_format) {
				this.frm.meta.default_print_format = null;
				this.frm.meta._default_print_format = null;
			}
		}
	}

	toggle_get_items() {
		const buttons = ["Sales Order", "Quotation", "Delivery Note"];

		buttons.forEach((label) => {
			this.frm.remove_custom_button(label, "Get Items From");
		});

		if (cint(this.frm.doc.docstatus) !== 0) {
			return;
		}

		if (!this.frm.doc.is_return) {
			this.frm.cscript.sales_order_btn();
			this.frm.cscript.quotation_btn();
		}

		this.frm.cscript.delivery_note_btn();
	}

	sales_order_btn() {
		var me = this;

		let filters = {
			docstatus: 1,
			status: ["not in", ["Closed", "On Hold"]],
			company: me.frm.doc.company,
		};

		this.$sales_order_btn = this.frm.add_custom_button(
			__("Sales Order"),
			function () {
				hisaabdari.utils.map_current_doc({
					method: "hisaabdari.selling.doctype.sales_order.sales_order.make_sales_invoice",
					source_doctype: "Sales Order",
					target: me.frm,
					setters: {
						customer: me.frm.doc.customer || undefined,
					},
					get_query_filters: filters,
					get_query_method:
						"hisaabdari.selling.doctype.sales_order.sales_order.get_potentially_billable_sales_orders",
					allow_child_item_selection: true,
					child_fieldname: "items",
					child_columns: ["item_code", "item_name", "qty", "amount", "billed_amt"],
				});
			},
			__("Get Items From")
		);
	}

	quotation_btn() {
		var me = this;
		this.$quotation_btn = this.frm.add_custom_button(
			__("Quotation"),
			function () {
				hisaabdari.utils.map_current_doc({
					method: "hisaabdari.selling.doctype.quotation.quotation.make_sales_invoice",
					source_doctype: "Quotation",
					target: me.frm,
					setters: [
						{
							fieldtype: "Link",
							label: __("Customer"),
							options: "Customer",
							fieldname: "party_name",
							default: me.frm.doc.customer,
						},
					],
					get_query_filters: {
						docstatus: 1,
						status: ["not in", ["Lost", "Expired"]],
						company: me.frm.doc.company,
					},
					allow_child_item_selection: true,
					child_fieldname: "items",
					child_columns: ["item_code", "item_name", "qty", "rate", "amount"],
				});
			},
			__("Get Items From")
		);
	}

	delivery_note_btn() {
		var me = this;
		this.$delivery_note_btn = this.frm.add_custom_button(
			__("Delivery Note"),
			function () {
				if (!me.frm.doc.customer) {
					frappe.throw({
						title: __("Mandatory"),
						message: __("Please Select a Customer"),
					});
				}
				hisaabdari.utils.map_current_doc({
					method: "hisaabdari.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
					source_doctype: "Delivery Note",
					target: me.frm,
					date_field: "posting_date",
					setters: {
						customer: me.frm.doc.customer || undefined,
					},
					get_query: function () {
						var filters = {
							docstatus: 1,
							company: me.frm.doc.company,
							is_return: me.frm.doc.is_return,
						};
						if (me.frm.doc.customer) filters["customer"] = me.frm.doc.customer;
						return {
							query: "hisaabdari.controllers.queries.get_delivery_notes_to_be_billed",
							filters: filters,
						};
					},
					allow_child_item_selection: true,
					child_fieldname: "items",
					child_columns: ["item_code", "item_name", "qty", "amount", "billed_amt"],
				});
			},
			__("Get Items From")
		);
	}

	tc_name() {
		this.get_terms();
	}
	customer() {
		var me = this;
		if (this.frm.updating_party_details) return;

		if (this.frm.doc.__onload && this.frm.doc.__onload.load_after_mapping) return;

		hisaabdari.utils.get_party_details(this.frm, "hisaabdari.accounts.party.get_party_details", {
			posting_date: this.frm.doc.posting_date,
			party: this.frm.doc.customer,
			party_type: "Customer",
			account: this.frm.doc.debit_to,
			price_list: this.frm.doc.selling_price_list,
			fetch_payment_terms_template: cint(
				(this.frm.doc.is_return == 0) & !this.frm.doc.ignore_default_payment_terms_template
			),
		});
	}

	make_inter_company_invoice() {
		let me = this;
		frappe.model.open_mapped_doc({
			method: "hisaabdari.accounts.doctype.sales_invoice.sales_invoice.make_inter_company_purchase_invoice",
			frm: me.frm,
		});
	}

	debit_to() {
		var me = this;
		if (this.frm.doc.debit_to) {
			me.frm.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Account",
					fieldname: "account_currency",
					filters: { name: me.frm.doc.debit_to },
				},
				callback: function (r, rt) {
					if (r.message) {
						me.frm.set_value("party_account_currency", r.message.account_currency);
						me.set_dynamic_labels();
					}
				},
			});
		}
	}

	allocated_amount() {
		this.calculate_total_advance();
		this.frm.refresh_fields();
	}

	items_add(doc, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		const field_copy = ["income_account", "discount_account", "cost_center"];
		this.frm.script_manager.copy_from_first_row("items", row, field_copy);
	}

	set_dynamic_labels() {
		super.set_dynamic_labels();
		this.frm.events.hide_fields(this.frm);
	}

	items_on_form_rendered() {
		hisaabdari.setup_serial_or_batch_no();
	}

	packed_items_on_form_rendered(doc, grid_row) {
		hisaabdari.setup_serial_or_batch_no();
	}

	make_sales_return() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
			frm: this.frm,
		});
	}

	is_cash_or_non_trade_discount() {
		this.frm.set_df_property(
			"additional_discount_account",
			"hidden",
			1 - this.frm.doc.is_cash_or_non_trade_discount
		);
		this.frm.set_df_property(
			"additional_discount_account",
			"reqd",
			this.frm.doc.is_cash_or_non_trade_discount
		);

		if (this.frm.doc.is_cash_or_non_trade_discount) {
			this.clear_mapped_discounts();
		} else {
			this.frm.set_value("additional_discount_account", "");
		}

		this.calculate_taxes_and_totals();
	}

	is_return() {
		this.toggle_get_items();
	}
};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new hisaabdari.accounts.SalesInvoiceController({ frm: cur_frm }));

cur_frm.cscript["Make Delivery Note"] = function () {
	frappe.model.open_mapped_doc({
		method: "hisaabdari.accounts.doctype.sales_invoice.sales_invoice.make_delivery_note",
		frm: cur_frm,
	});
};

cur_frm.cscript.income_account = function (doc, cdt, cdn) {
	hisaabdari.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "income_account");
};

cur_frm.cscript.expense_account = function (doc, cdt, cdn) {
	hisaabdari.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "expense_account");
};

frappe.ui.form.on("Sales Invoice", {
	setup: function (frm) {
		frm.add_fetch("customer", "tax_id", "tax_id");
		frm.add_fetch("payment_term", "invoice_portion", "invoice_portion");
		frm.add_fetch("payment_term", "description", "description");

		frm.set_df_property("packed_items", "cannot_add_rows", true);
		frm.set_df_property("packed_items", "cannot_delete_rows", true);

		frm.set_query("cost_center", "items", function (doc) {
			return {
				filters: {
					company: doc.company,
					is_group: 0,
				},
			};
		});

		frm.set_query("debit_to", function (doc) {
			return {
				filters: {
					account_type: "Receivable",
					is_group: 0,
					company: doc.company,
				},
			};
		});

		frm.set_query("unrealized_profit_loss_account", function (doc) {
			return {
				filters: {
					company: doc.company,
					is_group: 0,
					root_type: "Liability",
				},
			};
		});

		frm.set_query("adjustment_against", function (doc) {
			return {
				filters: {
					company: doc.company,
					customer: doc.customer,
					docstatus: 1,
				},
			};
		});

		frm.set_query("additional_discount_account", function (doc) {
			return {
				filters: {
					company: doc.company,
					is_group: 0,
					report_type: "Profit and Loss",
				},
			};
		});

		frm.set_query("income_account", "items", function (doc) {
			return {
				query: "hisaabdari.controllers.queries.get_income_account",
				filters: {
					company: doc.company,
					disabled: 0,
				},
			};
		});

		frm.custom_make_buttons = {
			"Delivery Note": "Delivery",
			"Sales Invoice": "Return / Credit Note",
			"Payment Entry": "Payment",
		};

		frm.set_query("discount_account", "items", function (doc) {
			return {
				filters: {
					report_type: "Profit and Loss",
					company: doc.company,
					is_group: 0,
				},
			};
		});
	},

	update_stock: function (frm, dt, dn) {
		frm.events.hide_fields(frm);
		frm.trigger("reset_posting_time");
	},

	hide_fields: function (frm) {
		let doc = frm.doc;
		var parent_fields = [
			"due_date",
			"is_opening",
			"utm_source",
			"utm_campaign",
			"utm_medium",
			"total_advance",
			"get_advances",
			"advances",
			"from_date",
			"to_date",
		];

		for (var i in parent_fields) {
			var docfield = frappe.meta.docfield_map[doc.doctype][parent_fields[i]];
			if (!docfield.hidden) unhide_field(parent_fields[i]);
		}

		frm.refresh_fields();
	},

	refresh: function (frm) {
		if (frm.doc.is_debit_note) {
			frm.set_df_property("return_against", "label", __("Adjustment Against"));
		}
	},
});
