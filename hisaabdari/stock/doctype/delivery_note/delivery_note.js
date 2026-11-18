// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.add_fetch("customer", "tax_id", "tax_id");

cur_frm.cscript.tax_table = "Sales Taxes and Charges";

frappe.provide("hisaabdari.stock");
frappe.provide("hisaabdari.stock.delivery_note");
frappe.provide("hisaabdari.accounts.dimensions");

hisaabdari.accounts.taxes.setup_tax_filters("Sales Taxes and Charges");
hisaabdari.accounts.taxes.setup_tax_validations("Delivery Note");
hisaabdari.sales_common.setup_selling_controller();

frappe.ui.form.on("Delivery Note", {
	setup: function (frm) {
		(frm.custom_make_buttons = {
			"Sales Invoice": "Sales Invoice",
			"Stock Entry": "Return",
		}),
			frm.set_indicator_formatter("item_code", function (doc) {
				return doc.docstatus == 1 || doc.qty <= doc.actual_qty ? "green" : "orange";
			});

		hisaabdari.queries.setup_queries(frm, "Warehouse", function () {
			return hisaabdari.queries.warehouse(frm.doc);
		});
		hisaabdari.queries.setup_warehouse_query(frm);

		frm.set_query("transporter", function () {
			return {
				filters: {
					is_transporter: 1,
				},
			};
		});

		frm.set_query("expense_account", "items", function (doc, cdt, cdn) {
			if (hisaabdari.is_perpetual_inventory_enabled(doc.company)) {
				return {
					filters: {
						report_type: "Profit and Loss",
						company: doc.company,
						is_group: 0,
					},
				};
			}
		});

		frm.set_query("cost_center", "items", function (doc, cdt, cdn) {
			if (hisaabdari.is_perpetual_inventory_enabled(doc.company)) {
				return {
					filters: {
						company: doc.company,
						is_group: 0,
					},
				};
			}
		});

		frm.set_df_property("packed_items", "cannot_add_rows", true);
		frm.set_df_property("packed_items", "cannot_delete_rows", true);
	},

	print_without_amount: function (frm) {
		hisaabdari.stock.delivery_note.set_print_hide(frm.doc);
	},

	refresh: function (frm) {
		if (
			frm.doc.docstatus === 1 &&
			frm.doc.is_return === 1 &&
			frm.doc.per_billed !== 100 &&
			frappe.model.can_create("Sales Invoice")
		) {
			frm.add_custom_button(
				__("Credit Note"),
				function () {
					frappe.model.open_mapped_doc({
						method: "hisaabdari.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
						frm: cur_frm,
					});
				},
				__("Create")
			);
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}

		if (
			frm.doc.docstatus == 1 &&
			!frm.doc.inter_company_reference &&
			frappe.model.can_create("Purchase Receipt")
		) {
			let internal = frm.doc.is_internal_customer;
			if (internal) {
				let button_label =
					frm.doc.company === frm.doc.represents_company
						? "Internal Purchase Receipt"
						: "Inter Company Purchase Receipt";

				frm.add_custom_button(
					__(button_label),
					function () {
						frappe.model.open_mapped_doc({
							method: "hisaabdari.stock.doctype.delivery_note.delivery_note.make_inter_company_purchase_receipt",
							frm: frm,
						});
					},
					__("Create")
				);
			}
		}
	},
});

frappe.ui.form.on("Delivery Note Item", {
	expense_account: function (frm, dt, dn) {
		var d = locals[dt][dn];
		frm.update_in_all_rows("items", "expense_account", d.expense_account);
	},
});

hisaabdari.stock.DeliveryNoteController = class DeliveryNoteController extends (
	hisaabdari.selling.SellingController
) {
	setup(doc) {
		this.setup_accounting_dimension_triggers();
		this.setup_posting_date_time_check();
		super.setup(doc);
	}
	refresh(doc, dt, dn) {
		var me = this;
		super.refresh();
		if (
			!doc.is_return &&
			(doc.status != "Closed" || this.frm.is_new()) &&
			this.frm.has_perm("write") &&
			frappe.model.can_read("Sales Order") &&
			this.frm.doc.docstatus === 0
		) {
			this.frm.add_custom_button(
				__("Sales Order"),
				function () {
					if (!me.frm.doc.customer) {
						frappe.throw({
							title: __("Mandatory"),
							message: __("Please Select a Customer"),
						});
					}
					hisaabdari.utils.map_current_doc({
						method: "hisaabdari.selling.doctype.sales_order.sales_order.make_delivery_note",
						source_doctype: "Sales Order",
						target: me.frm,
						setters: {
							customer: me.frm.doc.customer,
						},
						get_query_filters: {
							docstatus: 1,
							status: ["not in", ["Closed", "On Hold"]],
							per_delivered: ["<", 99.99],
							company: me.frm.doc.company,
						},
						allow_child_item_selection: true,
						child_fieldname: "items",
						child_columns: ["item_code", "item_name", "qty", "delivered_qty"],
					});
				},
				__("Get Items From")
			);
		}

		if (!doc.is_return && doc.status != "Closed") {
			if (doc.docstatus == 1 && this.frm.has_perm("create")) {
				this.frm.add_custom_button(
					__("Sales Return"),
					function () {
						me.make_sales_return();
					},
					__("Create")
				);
			}

			if (!doc.__islocal && doc.docstatus == 1) {
				this.frm.page.set_inner_btn_group_as_primary(__("Create"));
			}
		}

		hisaabdari.accounts.ledger_preview.show_accounting_ledger_preview(this.frm);
		hisaabdari.accounts.ledger_preview.show_stock_ledger_preview(this.frm);

		if (doc.docstatus > 0) {
			this.show_stock_ledger();
			if (hisaabdari.is_perpetual_inventory_enabled(doc.company)) {
				this.show_general_ledger();
			}
			if (this.frm.has_perm("submit") && doc.status !== "Closed") {
				me.frm.add_custom_button(
					__("Close"),
					function () {
						me.close_delivery_note();
					},
					__("Status")
				);
			}
		}

		if (
			doc.docstatus == 1 &&
			!doc.is_return &&
			doc.per_returned != 100 &&
			doc.status != "Closed" &&
			flt(doc.per_billed) < 100 &&
			frappe.model.can_create("Sales Invoice")
		) {
			// show Make Invoice button only if Delivery Note is not created from Sales Invoice
			var from_sales_invoice = false;
			from_sales_invoice = me.frm.doc.items.some(function (item) {
				return item.against_sales_invoice ? true : false;
			});

			if (!from_sales_invoice) {
				this.frm.add_custom_button(
					__("Sales Invoice"),
					function () {
						me.make_sales_invoice();
					},
					__("Create")
				);
			}
		}

		if (doc.docstatus == 1 && doc.status === "Closed" && this.frm.has_perm("submit")) {
			this.frm.add_custom_button(
				__("Reopen"),
				function () {
					me.reopen_delivery_note();
				},
				__("Status")
			);
		}
		hisaabdari.stock.delivery_note.set_print_hide(doc, dt, dn);
	}

	make_sales_invoice() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
			frm: this.frm,
		});
	}

	make_sales_return() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.stock.doctype.delivery_note.delivery_note.make_sales_return",
			frm: this.frm,
		});
	}

	tc_name() {
		this.get_terms();
	}

	items_on_form_rendered(doc, grid_row) {
		hisaabdari.setup_serial_or_batch_no();
	}

	packed_items_on_form_rendered(doc, grid_row) {
		hisaabdari.setup_serial_or_batch_no();
	}

	close_delivery_note(doc) {
		this.update_status("Closed");
	}

	reopen_delivery_note() {
		this.update_status("Submitted");
	}

	update_status(status) {
		var me = this;
		frappe.ui.form.is_saving = true;
		frappe.call({
			method: "hisaabdari.stock.doctype.delivery_note.delivery_note.update_delivery_note_status",
			args: { docname: me.frm.doc.name, status: status },
			callback: function (r) {
				if (!r.exc) me.frm.reload_doc();
			},
			always: function () {
				frappe.ui.form.is_saving = false;
			},
		});
	}
};

extend_cscript(cur_frm.cscript, new hisaabdari.stock.DeliveryNoteController({ frm: cur_frm }));

frappe.ui.form.on("Delivery Note", {
	setup: function (frm) {
		if (frm.doc.company) {
			frm.trigger("unhide_account_head");
		}
	},

	company: function (frm) {
		frm.trigger("unhide_account_head");
		hisaabdari.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	unhide_account_head: function (frm) {
		// unhide expense_account and cost_center if perpetual inventory is enabled in the company
		var aii_enabled = hisaabdari.is_perpetual_inventory_enabled(frm.doc.company);
		frm.fields_dict["items"].grid.set_column_disp(["expense_account", "cost_center"], aii_enabled);
	},
});

hisaabdari.stock.delivery_note.set_print_hide = function (doc, cdt, cdn) {
	var dn_fields = frappe.meta.docfield_map["Delivery Note"];
	var dn_item_fields = frappe.meta.docfield_map["Delivery Note Item"];
	var dn_fields_copy = dn_fields;
	var dn_item_fields_copy = dn_item_fields;
	if (doc.print_without_amount) {
		dn_fields["currency"].print_hide = 1;
		dn_item_fields["rate"].print_hide = 1;
		dn_item_fields["discount_percentage"].print_hide = 1;
		dn_item_fields["price_list_rate"].print_hide = 1;
		dn_item_fields["amount"].print_hide = 1;
		dn_item_fields["discount_amount"].print_hide = 1;
		dn_fields["taxes"].print_hide = 1;
	} else {
		if (dn_fields_copy["currency"].print_hide != 1) dn_fields["currency"].print_hide = 0;
		if (dn_item_fields_copy["rate"].print_hide != 1) dn_item_fields["rate"].print_hide = 0;
		if (dn_item_fields_copy["amount"].print_hide != 1) dn_item_fields["amount"].print_hide = 0;
		if (dn_item_fields_copy["discount_amount"].print_hide != 1)
			dn_item_fields["discount_amount"].print_hide = 0;
		if (dn_fields_copy["taxes"].print_hide != 1) dn_fields["taxes"].print_hide = 0;
	}
};

frappe.tour["Delivery Note"] = [
	{
		fieldname: "customer",
		title: __("Customer"),
		description: __("This field is used to set the 'Customer'."),
	},
	{
		fieldname: "items",
		title: __("Items"),
		description:
			__("This table is used to set details about the 'Item', 'Qty', 'Basic Rate', etc.") +
			" " +
			__("Different 'Source Warehouse' and 'Target Warehouse' can be set for each row."),
	},
	{
		fieldname: "set_posting_time",
		title: __("Edit Posting Date and Time"),
		description: __("This option can be checked to edit the 'Posting Date' and 'Posting Time' fields."),
	},
];
