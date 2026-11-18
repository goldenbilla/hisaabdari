// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.buying");
frappe.provide("hisaabdari.accounts.dimensions");

cur_frm.cscript.tax_table = "Purchase Taxes and Charges";

hisaabdari.accounts.taxes.setup_tax_filters("Purchase Taxes and Charges");
hisaabdari.accounts.taxes.setup_tax_validations("Purchase Order");
hisaabdari.buying.setup_buying_controller();

frappe.ui.form.on("Purchase Order", {
	setup: function (frm) {
		frm.set_indicator_formatter("item_code", function (doc) {
			let color;
			if (!doc.qty && frm.doc.has_unit_price_items) {
				color = "yellow";
			} else if (doc.qty <= doc.received_qty) {
				color = "green";
			} else {
				color = "orange";
			}
			return color;
		});

		frm.set_query("expense_account", "items", function () {
			return {
				query: "hisaabdari.controllers.queries.get_expense_account",
				filters: { company: frm.doc.company },
			};
		});
	},

	company: function (frm) {
		hisaabdari.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	schedule_date(frm) {
		if (frm.doc.schedule_date) {
			frm.doc.items.forEach((d) => {
				frappe.model.set_value(d.doctype, d.name, "schedule_date", frm.doc.schedule_date);
			});
		}
	},

	transaction_date(frm) {
		hisaabdari.buying.prevent_past_schedule_dates(frm);
		frm.set_value("schedule_date", "");
	},

	refresh: function (frm) {
		if (frm.doc.docstatus == 0) {
			hisaabdari.set_unit_price_items_note(frm);
		}
		hisaabdari.buying.prevent_past_schedule_dates(frm);
	},

	onload: function (frm) {
		var ignore_list = ["Unreconcile Payment", "Unreconcile Payment Entries"];
		frm.ignore_doctypes_on_cancel_all = Object.hasOwn(frm, "ignore_doctypes_on_cancel_all")
			? frm.ignore_doctypes_on_cancel_all.concat(ignore_list)
			: ignore_list;
		set_schedule_date(frm);
		if (!frm.doc.transaction_date) {
			frm.set_value("transaction_date", frappe.datetime.get_today());
		}

		hisaabdari.queries.setup_queries(frm, "Warehouse", function () {
			return hisaabdari.queries.warehouse(frm.doc);
		});

		// On cancel and amending a purchase order with advance payment, reset advance paid amount
		if (frm.is_new()) {
			frm.set_value("advance_paid", 0);
		}
	},
});

frappe.ui.form.on("Purchase Order Item", {
	schedule_date: function (frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (row.schedule_date) {
			if (!frm.doc.schedule_date) {
				hisaabdari.utils.copy_value_in_all_rows(frm.doc, cdt, cdn, "items", "schedule_date");
			} else {
				set_schedule_date(frm);
			}
		}
	},
});

hisaabdari.buying.PurchaseOrderController = class PurchaseOrderController extends (
	hisaabdari.buying.BuyingController
) {
	setup() {
		this.setup_accounting_dimension_triggers();
		this.frm.custom_make_buttons = {
			"Purchase Receipt": "Purchase Receipt",
			"Purchase Invoice": "Purchase Invoice",
			"Payment Entry": "Payment",
		};

		super.setup();
	}

	refresh(doc, cdt, cdn) {
		var me = this;
		super.refresh();
		var allow_receipt = false;
		var is_drop_ship = false;

		for (var i in this.frm.doc.items) {
			var item = this.frm.doc.items[i];
			if (item.delivered_by_supplier !== 1) {
				allow_receipt = true;
			} else {
				is_drop_ship = true;
			}

			if (is_drop_ship && allow_receipt) {
				break;
			}
		}

		this.frm.set_df_property("drop_ship", "hidden", !is_drop_ship);

		if (doc.docstatus == 1) {
			this.frm.fields_dict.items_section.wrapper.addClass("hide-border");
			if (!this.frm.doc.set_warehouse) {
				this.frm.fields_dict.items_section.wrapper.removeClass("hide-border");
			}

			if (!["Closed", "Delivered"].includes(doc.status)) {
				if (
					this.frm.doc.status !== "Closed" &&
					flt(this.frm.doc.per_received) < 100 &&
					flt(this.frm.doc.per_billed) < 100
				) {
					if (!this.frm.doc.__onload || this.frm.doc.__onload.can_update_items) {
						this.frm.add_custom_button(__("Update Items"), () => {
							hisaabdari.utils.update_child_items({
								frm: this.frm,
								child_docname: "items",
								child_doctype: "Purchase Order Detail",
								cannot_add_row: false,
							});
						});
					}
				}
				if (this.frm.has_perm("submit")) {
					if (flt(doc.per_billed) < 100 || flt(doc.per_received) < 100) {
						if (doc.status != "On Hold") {
							this.frm.add_custom_button(
								__("Hold"),
								() => this.hold_purchase_order(),
								__("Status")
							);
						} else {
							this.frm.add_custom_button(
								__("Resume"),
								() => this.unhold_purchase_order(),
								__("Status")
							);
						}
						this.frm.add_custom_button(
							__("Close"),
							() => this.close_purchase_order(),
							__("Status")
						);
					}
				}

				if (is_drop_ship && !["Completed", "Delivered"].includes(doc.status)) {
					this.frm.add_custom_button(
						__("Deliver (Dropship)"),
						this.delivered_by_supplier.bind(this),
						__("Status")
					);

					this.frm.page.set_inner_btn_group_as_primary(__("Status"));
				}
			} else if (["Closed", "Delivered"].includes(doc.status)) {
				if (this.frm.has_perm("submit")) {
					this.frm.add_custom_button(
						__("Re-open"),
						() => this.unclose_purchase_order(),
						__("Status")
					);
				}
			}
			if (doc.status != "Closed") {
				if (doc.status != "On Hold") {
					if (
						doc.items
							.filter((item) => !item.delivered_by_supplier)
							.some((item) => item.received_qty < item.qty) &&
						allow_receipt
					) {
						this.frm.add_custom_button(
							__("Purchase Receipt"),
							() => {
								me.make_purchase_receipt();
							},
							__("Create")
						);
					}
					// Please do not add precision in the below flt function
					if (flt(doc.per_billed) < 100)
						this.frm.add_custom_button(
							__("Purchase Invoice"),
							() => {
								me.make_purchase_invoice();
							},
							__("Create")
						);

					if (
						frappe.model.can_create("Payment Entry") &&
						flt(doc.per_billed) < 100 &&
						doc.status != "Delivered"
					) {
						this.frm.add_custom_button(
							__("Payment"),
							() => this.make_payment_entry(),
							__("Create")
						);
					}

					if (doc.docstatus === 1 && doc.is_internal_supplier) {
						let button_label =
							doc.company === doc.represents_company
								? __("Internal Sales Order")
								: __("Inter Company Sales Order");

						this.add_inter_company_order_button(
							button_label,
							"Sales Order",
							"purchase_order_item"
						);
					}
				}

				this.frm.page.set_inner_btn_group_as_primary(__("Create"));
			}
		} else if (doc.docstatus === 0) {
			this.frm.cscript.add_from_mappers();
		}
	}

	validate() {
		set_schedule_date(this.frm);
	}

	make_inter_company_order(frm) {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.buying.doctype.purchase_order.purchase_order.make_inter_company_sales_order",
			frm: frm,
		});
	}

	make_purchase_receipt() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
			frm: this.frm,
			freeze_message: __("Creating Purchase Receipt ..."),
		});
	}

	make_purchase_invoice() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.buying.doctype.purchase_order.purchase_order.make_purchase_invoice",
			frm: this.frm,
		});
	}

	add_from_mappers() {
		var me = this;
		this.frm.add_custom_button(
			__("Update Rate as per Last Purchase"),
			function () {
				frappe.call({
					method: "get_last_purchase_rate",
					doc: me.frm.doc,
					callback: function (r, rt) {
						me.frm.dirty();
						me.frm.cscript.calculate_taxes_and_totals();
					},
				});
			},
			__("Tools")
		);
	}

	tc_name() {
		this.get_terms();
	}

	items_add(doc, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		const field_copy = [];
		if (doc.schedule_date) {
			frappe.model.set_value(cdt, cdn, "schedule_date", doc.schedule_date);
		} else {
			field_copy.push("schedule_date");
		}
		if (field_copy.length) {
			this.frm.script_manager.copy_from_first_row("items", row, field_copy);
		}
	}

	unhold_purchase_order() {
		this.frm.cscript.update_status("Resume", "Draft");
	}

	hold_purchase_order() {
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __("Reason for Hold"),
			fields: [
				{
					fieldname: "reason_for_hold",
					fieldtype: "Text",
					reqd: 1,
				},
			],
			primary_action: function (data) {
				let reason_for_hold = "Reason for hold: " + data.reason_for_hold;

				frappe.call({
					method: "frappe.desk.form.utils.add_comment",
					args: {
						reference_doctype: me.frm.doctype,
						reference_name: me.frm.docname,
						content: __(reason_for_hold),
						comment_email: frappe.session.user,
						comment_by: frappe.session.user_fullname,
					},
					callback: function (r) {
						if (!r.exc) {
							me.update_status("Hold", "On Hold");
							d.hide();
						}
					},
				});
			},
		});
		d.show();
	}

	unclose_purchase_order() {
		this.frm.cscript.update_status("Re-open", "Submitted");
	}

	close_purchase_order() {
		this.frm.cscript.update_status("Close", "Closed");
	}

	delivered_by_supplier() {
		const data = this.frm.doc.items
			.filter((item) => item.delivered_by_supplier == 1)
			.map((item) => {
				return {
					__checked: item.qty > item.received_qty,
					name: item.name,
					item_code: item.item_code,
					item_name: item.item_name,
					qty: item.qty,
					uom: item.uom,
					delivered_qty: item.received_qty || 0,
					qty_change: item.qty - item.received_qty,
				};
			});
		const dialog = new frappe.ui.Dialog({
			title: __("Set Dropship Items Delivered Quantity"),
			size: "extra-large",
			fields: [
				{
					fieldname: "items",
					fieldtype: "Table",
					data: data,
					cannot_add_rows: true,
					cannot_delete_rows: true,
					fields: [
						{
							fieldname: "name",
							fieldtype: "Data",
							read_only: true,
							hidden: 1,
						},
						{
							fieldname: "item_code",
							fieldtype: "Link",
							options: "Item",
							label: __("Item Code"),
							in_list_view: 1,
							read_only: true,
						},
						{
							fieldname: "item_name",
							fieldtype: "Data",
							label: __("Item Name"),
							in_list_view: 1,
							read_only: true,
						},
						{
							fieldname: "qty",
							fieldtype: "Float",
							label: __("Quantity"),
							in_list_view: 1,
							read_only: true,
						},
						{
							fieldname: "uom",
							fieldtype: "Data",
							label: __("UOM"),
							in_list_view: 1,
							read_only: true,
						},
						{
							fieldname: "delivered_qty",
							fieldtype: "Float",
							label: __("Delivered Qty"),
							read_only: true,
							in_list_view: 1,
						},
						{
							fieldname: "qty_change",
							fieldtype: "Float",
							label: __("Qty Change"),
							in_list_view: 1,
							reqd: 1,
						},
					],
				},
			],
			primary_action: (values) => {
				const frm = this.frm;
				frappe.call({
					doc: frm.doc,
					method: "update_dropship_received_qty",
					args: {
						data: values.items
							.filter((item) => item.__checked)
							.map((item) => ({
								name: item.name,
								current_qty: item.delivered_qty,
								qty_change: item.qty_change,
							})),
					},
					callback: function (r) {
						if (!r.exc) {
							frm.reload_doc();
							frappe.toast(__("Quantities updated successfully."));
							dialog.hide();
						}
					},
				});
			},
		});
		dialog.show();
	}

	items_on_form_rendered() {
		set_schedule_date(this.frm);
	}
};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new hisaabdari.buying.PurchaseOrderController({ frm: cur_frm }));

cur_frm.cscript.update_status = function (label, status) {
	frappe.call({
		method: "hisaabdari.buying.doctype.purchase_order.purchase_order.update_status",
		args: { status: status, name: cur_frm.doc.name },
		callback: function (r) {
			cur_frm.set_value("status", status);
			cur_frm.reload_doc();
		},
	});
};

function set_schedule_date(frm) {
	if (frm.doc.schedule_date) {
		hisaabdari.utils.copy_value_in_all_rows(
			frm.doc,
			frm.doc.doctype,
			frm.doc.name,
			"items",
			"schedule_date"
		);
	}
}
