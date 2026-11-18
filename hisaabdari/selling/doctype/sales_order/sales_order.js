// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.cscript.tax_table = "Sales Taxes and Charges";

hisaabdari.accounts.taxes.setup_tax_filters("Sales Taxes and Charges");
hisaabdari.accounts.taxes.setup_tax_validations("Sales Order");
hisaabdari.sales_common.setup_selling_controller();

frappe.ui.form.on("Sales Order", {
	setup: function (frm) {
		frm.custom_make_buttons = {
			"Delivery Note": "Delivery Note",
			"Sales Invoice": "Sales Invoice",
			"Purchase Order": "Purchase Order",
			"Payment Entry": "Payment",
		};
		frm.add_fetch("customer", "tax_id", "tax_id");

		// formatter for material request item
		frm.set_indicator_formatter("item_code", function (doc) {
			let color;
			if (!doc.qty && frm.doc.has_unit_price_items) {
				color = "yellow";
			} else if (doc.stock_qty - doc.delivered_qty <= doc.actual_qty) {
				color = "green";
			} else {
				color = "orange";
			}

			return color;
		});

		frm.set_df_property("packed_items", "cannot_add_rows", true);
		frm.set_df_property("packed_items", "cannot_delete_rows", true);
	},
	delivery_date(frm) {
		if (frm.doc.delivery_date) {
			frm.doc.items.forEach((d) => {
				frappe.model.set_value(d.doctype, d.name, "delivery_date", frm.doc.delivery_date);
			});
		}
	},
	transaction_date(frm) {
		prevent_past_delivery_dates(frm);
		frm.set_value("delivery_date", "");
		frm.doc.items.forEach((d) => {
			frappe.model.set_value(d.doctype, d.name, "delivery_date", "");
		});
	},

	refresh: function (frm) {
		if (frm.doc.docstatus === 1) {
			if (
				frm.doc.status !== "Closed" &&
				flt(frm.doc.per_delivered) < 100 &&
				flt(frm.doc.per_billed) < 100 &&
				frm.has_perm("write")
			) {
				frm.add_custom_button(__("Update Items"), () => {
					hisaabdari.utils.update_child_items({
						frm: frm,
						child_docname: "items",
						child_doctype: "Sales Order Detail",
						cannot_add_row: false,
					});
				});
			}
		}

		if (frm.doc.docstatus === 0) {
			hisaabdari.set_unit_price_items_note(frm);

			if (frm.doc.is_internal_customer) {
				frm.events.get_items_from_internal_purchase_order(frm);
			}
		}
		prevent_past_delivery_dates(frm);
	},

	get_items_from_internal_purchase_order(frm) {
		if (!frappe.model.can_read("Purchase Order")) {
			return;
		}

		frm.add_custom_button(
			__("Purchase Order"),
			() => {
				hisaabdari.utils.map_current_doc({
					method: "hisaabdari.buying.doctype.purchase_order.purchase_order.make_inter_company_sales_order",
					source_doctype: "Purchase Order",
					target: frm,
					setters: [
						{
							label: __("Supplier"),
							fieldname: "supplier",
							fieldtype: "Link",
							options: "Supplier",
						},
					],
					get_query_filters: {
						company: frm.doc.company,
						is_internal_supplier: 1,
						docstatus: 1,
						status: ["!=", "Completed"],
					},
				});
			},
			__("Get Items From")
		);
	},

	onload: function (frm) {
		if (!frm.doc.transaction_date) {
			frm.set_value("transaction_date", frappe.datetime.get_today());
		}
		hisaabdari.queries.setup_queries(frm, "Warehouse", function () {
			return {
				filters: [
					["Warehouse", "company", "in", ["", cstr(frm.doc.company)]],
					["Warehouse", "is_group", "=", 0],
				],
			};
		});

		frm.set_query("warehouse", "items", function (doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			let query = {
				filters: [
					["Warehouse", "company", "in", ["", cstr(frm.doc.company)]],
					["Warehouse", "is_group", "=", 0],
				],
			};
			if (row.item_code) {
				query.query = "hisaabdari.controllers.queries.warehouse_query";
				query.filters.push(["Bin", "item_code", "=", row.item_code]);
			}
			return query;
		});

		// On cancel and amending a sales order with advance payment, reset advance paid amount
		if (frm.is_new()) {
			frm.set_value("advance_paid", 0);
		}

		frm.ignore_doctypes_on_cancel_all = [
			"Purchase Order",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
		];
	},
});

frappe.ui.form.on("Sales Order Item", {
	item_code: async function (frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (frm.doc.delivery_date) {
			row.delivery_date = frm.doc.delivery_date;
			refresh_field("delivery_date", cdn, "items");
		} else {
			frm.script_manager.copy_from_first_row("items", row, ["delivery_date"]);
		}
	},

	delivery_date: function (frm, cdt, cdn) {
		if (!frm.doc.delivery_date) {
			hisaabdari.utils.copy_value_in_all_rows(frm.doc, cdt, cdn, "items", "delivery_date");
		}
	},
});

hisaabdari.selling.SalesOrderController = class SalesOrderController extends hisaabdari.selling.SellingController {
	setup(doc) {
		this.setup_accounting_dimension_triggers();
		super.setup(doc);
	}
	onload(doc, dt, dn) {
		super.onload(doc, dt, dn);
	}

	refresh(doc, dt, dn) {
		var me = this;
		super.refresh();
		let allow_delivery = false;

		if (doc.docstatus == 1) {
			if (this.frm.has_perm("submit")) {
				if (doc.status === "On Hold") {
					// un-hold
					this.frm.add_custom_button(
						__("Resume"),
						function () {
							me.frm.cscript.update_status("Resume", "Draft");
						},
						__("Status")
					);

					if (flt(doc.per_delivered) < 100 || flt(doc.per_billed) < 100) {
						// close
						this.frm.add_custom_button(__("Close"), () => this.close_sales_order(), __("Status"));
					}
				} else if (doc.status === "Closed") {
					// un-close
					this.frm.add_custom_button(
						__("Re-open"),
						function () {
							me.frm.cscript.update_status("Re-open", "Draft");
						},
						__("Status")
					);
				}
			}
			if (doc.status !== "Closed") {
				if (doc.status !== "On Hold") {
					const items_are_deliverable = this.frm.doc.items.some(
						(item) => item.delivered_by_supplier === 0 && item.qty > flt(item.delivered_qty)
					);
					allow_delivery =
						(this.frm.doc.has_unit_price_items || items_are_deliverable) &&
						!this.frm.doc.skip_delivery_note;

					if (this.frm.has_perm("submit")) {
						if (flt(doc.per_delivered) < 100 || flt(doc.per_billed) < 100) {
							// hold
							this.frm.add_custom_button(
								__("Hold"),
								() => this.hold_sales_order(),
								__("Status")
							);
							// close
							this.frm.add_custom_button(
								__("Close"),
								() => this.close_sales_order(),
								__("Status")
							);
						}
					}

					const order_is_a_sale = ["Sales", "Shopping Cart"].indexOf(doc.order_type) !== -1;
					// order type has been customised then show all the action buttons
					const order_is_a_custom_sale =
						["Sales", "Shopping Cart", "Maintenance"].indexOf(doc.order_type) === -1;

					// delivery note
					if (
						flt(doc.per_delivered) < 100 &&
						(order_is_a_sale || order_is_a_custom_sale) &&
						allow_delivery
					) {
						if (frappe.model.can_create("Delivery Note")) {
							this.frm.add_custom_button(
								__("Delivery Note"),
								() => this.make_delivery_note_based_on_delivery_date(),
								__("Create")
							);
						}
					}

					// sales invoice
					if (
						doc.__onload?.has_potentially_billable_items &&
						frappe.model.can_create("Sales Invoice")
					) {
						this.frm.add_custom_button(
							__("Sales Invoice"),
							() => me.make_sales_invoice(),
							__("Create")
						);
					}

					// Make Purchase Order
					if (
						!this.frm.doc.is_internal_customer &&
						frappe.model.can_create("Purchase Order")
					) {
						this.frm.add_custom_button(
							__("Purchase Order"),
							() => this.make_purchase_order(),
							__("Create")
						);
					}

					if (doc.docstatus === 1 && doc.is_internal_customer) {
						let button_label =
							doc.company === doc.represents_company
								? __("Internal Purchase Order")
								: __("Inter Company Purchase Order");

						this.add_inter_company_order_button(
							button_label,
							"Purchase Order",
							"sales_order_item"
						);
					}
				}
				// payment request
				if (flt(doc.per_billed) < 100 + frappe.boot.sysdefaults.over_billing_allowance) {
					if (frappe.model.can_create("Payment Entry")) {
						this.frm.add_custom_button(
							__("Payment"),
							() => this.make_payment_entry(),
							__("Create")
						);
					}
				}
				this.frm.page.set_inner_btn_group_as_primary(__("Create"));
			}
		}

		if (this.frm.doc.docstatus === 0 && frappe.model.can_read("Quotation")) {
			this.frm.add_custom_button(
				__("Quotation"),
				function () {
					let d = hisaabdari.utils.map_current_doc({
						method: "hisaabdari.selling.doctype.quotation.quotation.make_sales_order",
						source_doctype: "Quotation",
						target: me.frm,
						setters: [
							{
								label: __("Customer"),
								fieldname: "party_name",
								fieldtype: "Link",
								options: "Customer",
								default: me.frm.doc.customer || undefined,
							},
						],
						get_query_filters: {
							company: me.frm.doc.company,
							docstatus: 1,
							status: ["not in", ["Lost", "Ordered"]],
						},
						allow_child_item_selection: true,
						child_fieldname: "items",
						child_columns: ["item_code", "item_name", "qty", "rate", "amount"],
					});
				},
				__("Get Items From")
			);
		}

		this.order_type(doc);
	}

	items_add(doc, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		const field_copy = [];
		if (doc.delivery_date) {
			frappe.model.set_value(cdt, cdn, "delivery_date", doc.delivery_date);
		} else {
			field_copy.push("delivery_date");
		}
		if (field_copy.length) {
			this.frm.script_manager.copy_from_first_row("items", row, field_copy);
		}
	}

	order_type() {
		this.toggle_delivery_date();
	}

	tc_name() {
		this.get_terms();
	}

	skip_delivery_note() {
		this.toggle_delivery_date();
	}

	toggle_delivery_date() {
		this.frm.fields_dict.items.grid.toggle_reqd(
			"delivery_date",
			this.frm.doc.order_type == "Sales" && !this.frm.doc.skip_delivery_note
		);
	}

	make_delivery_note_based_on_delivery_date(for_reserved_stock = false) {
		var me = this;

		var delivery_dates = this.frm.doc.items.map((i) => i.delivery_date);
		delivery_dates = [...new Set(delivery_dates)];

		var today = new Date();

		var item_grid = this.frm.fields_dict["items"].grid;
		if (!item_grid.get_selected().length && delivery_dates.length > 1) {
			var dialog = new frappe.ui.Dialog({
				title: __("Select Items based on Delivery Date"),
				fields: [{ fieldtype: "HTML", fieldname: "dates_html" }],
			});

			var html = $(`
				<div style="border: 1px solid #d1d8dd">
					<div class="list-item list-item--head">
						<div class="list-item__content list-item__content--flex-2">
							${__("Delivery Date")}
						</div>
					</div>
					${delivery_dates
						.map(
							(date) => `
						<div class="list-item">
							<div class="list-item__content list-item__content--flex-2">
								<label>
								<input
									type="checkbox"
									data-date="${date}"
									${frappe.datetime.get_day_diff(new Date(date), today) > 0 ? "" : 'checked="checked"'}
								/>
								${frappe.datetime.str_to_user(date)}
								</label>
							</div>
						</div>
					`
						)
						.join("")}
				</div>
			`);

			var wrapper = dialog.fields_dict.dates_html.$wrapper;
			wrapper.html(html);

			dialog.set_primary_action(__("Select"), function () {
				var dates = wrapper
					.find("input[type=checkbox]:checked")
					.map((i, el) => $(el).attr("data-date"))
					.toArray();

				if (!dates) return;

				me.make_delivery_note(dates, for_reserved_stock);
				dialog.hide();
			});
			dialog.show();
		} else {
			this.make_delivery_note([], for_reserved_stock);
		}
	}

	make_delivery_note(delivery_dates, for_reserved_stock = false) {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.selling.doctype.sales_order.sales_order.make_delivery_note",
			frm: this.frm,
			args: {
				delivery_dates,
			},
			freeze: true,
			freeze_message: __("Creating Delivery Note ..."),
		});
	}

	make_sales_invoice() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.selling.doctype.sales_order.sales_order.make_sales_invoice",
			frm: this.frm,
		});
	}

	make_inter_company_order() {
		frappe.model.open_mapped_doc({
			method: "hisaabdari.selling.doctype.sales_order.sales_order.make_inter_company_purchase_order",
			frm: this.frm,
		});
	}

	make_purchase_order() {
		let pending_items = this.frm.doc.items.some((item) => {
			const pending_qty = flt(item.stock_qty) - this.get_ordered_qty(item, this.frm.doc);
			return pending_qty > 0;
		});
		if (!pending_items) {
			frappe.throw({
				message: __("Purchase Order already created for all Sales Order items"),
				title: __("Note"),
			});
		}

		var me = this;
		var dialog = new frappe.ui.Dialog({
			title: __("Select Items"),
			size: "large",
			fields: [
				{
					fieldname: "set_supplier",
					fieldtype: "Link",
					label: __("Set Supplier"),
					options: "Supplier",
					onchange: function () {
						let supplier = dialog.get_value("set_supplier");
						let items_table = dialog.fields_dict.items_for_po.grid;
						let selected_items = items_table.get_selected_children();

						selected_items.forEach((item) => {
							item.supplier = supplier;
							items_table.refresh();
						});
					},
				},
				{
					fieldtype: "Column Break",
				},
				{
					fieldtype: "Section Break",
				},
				{
					fieldname: "items_for_po",
					fieldtype: "Table",
					label: __("Select Items"),
					cannot_add_rows: true,
					cannot_delete_rows: true,
					fields: [
						{
							fieldtype: "Data",
							fieldname: "item_code",
							label: __("Item"),
							read_only: 1,
							in_list_view: 1,
						},
						{
							fieldtype: "Data",
							fieldname: "item_name",
							label: __("Item name"),
							read_only: 1,
							in_list_view: 1,
						},
						{
							fieldtype: "Float",
							fieldname: "pending_qty",
							label: __("Pending Qty"),
							read_only: 1,
							in_list_view: 1,
						},
						{
							fieldtype: "Link",
							read_only: 1,
							fieldname: "uom",
							label: __("UOM"),
							options: "UOM",
							in_list_view: 1,
						},
						{
							fieldtype: "Link",
							fieldname: "supplier",
							label: __("Supplier"),
							reqd: 1,
							options: "Supplier",
							in_list_view: 1,
						},
					],
				},
			],
			primary_action_label: __("Create Purchase Order"),
			primary_action(args) {
				if (!args) return;

				let selected_items = dialog.fields_dict.items_for_po.grid.get_selected_children();
				if (selected_items.length == 0) {
					frappe.throw({
						message: "Please select Items from the Table",
						title: __("Items Required"),
						indicator: "blue",
					});
				}

				if (selected_items.some((item) => !item.supplier)) {
					frappe.throw({
						message: __("Supplier is required for all selected Items"),
						title: __("Supplier Required"),
						indicator: "blue",
					});
				}

				dialog.hide();
				return frappe.call({
					method: "hisaabdari.selling.doctype.sales_order.sales_order.make_purchase_order",
					freeze_message: __("Creating Purchase Order ..."),
					args: {
						source_name: me.frm.doc.name,
						selected_items: selected_items,
					},
					freeze: true,
					callback: function (r) {
						if (!r.exc) {
							if (r.message.length == 1) {
								frappe.model.sync(r.message[0]);
								frappe.set_route("Form", r.message[0].doctype, r.message[0].name);
							} else {
								frappe.route_options = {
									sales_order: me.frm.doc.name,
								};
								frappe.set_route("List", "Purchase Order");
							}
						}
					},
				});
			},
		});

		function set_po_items_data(dialog) {
			let po_items = [];
			me.frm.doc.items.forEach((d) => {
				let ordered_qty = me.get_ordered_qty(d, me.frm.doc);
				let pending_qty = (flt(d.stock_qty) - ordered_qty) / flt(d.conversion_factor);
				if (pending_qty > 0) {
					po_items.push({
						name: d.name,
						item_name: d.item_name,
						item_code: d.item_code,
						pending_qty: pending_qty,
						uom: d.uom,
						supplier: d.supplier,
					});
				}
			});

			dialog.fields_dict["items_for_po"].df.data = po_items;
			dialog.get_field("items_for_po").refresh();
		}

		set_po_items_data(dialog);
		dialog.get_field("items_for_po").refresh();
		dialog.wrapper.find(".grid-heading-row .grid-row-check").click();
		dialog.show();
	}

	get_ordered_qty(item, so) {
		let ordered_qty = item.ordered_qty;
		return ordered_qty;
	}

	hold_sales_order() {
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
				frappe.call({
					method: "frappe.desk.form.utils.add_comment",
					args: {
						reference_doctype: me.frm.doctype,
						reference_name: me.frm.docname,
						content: __("Reason for hold:") + " " + data.reason_for_hold,
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
	close_sales_order() {
		this.frm.cscript.update_status("Close", "Closed");
	}
	update_status(label, status) {
		var doc = this.frm.doc;
		var me = this;
		frappe.ui.form.is_saving = true;
		frappe.call({
			method: "hisaabdari.selling.doctype.sales_order.sales_order.update_status",
			args: { status: status, name: doc.name },
			callback: function (r) {
				me.frm.reload_doc();
			},
			always: function () {
				frappe.ui.form.is_saving = false;
			},
		});
	}
};

extend_cscript(cur_frm.cscript, new hisaabdari.selling.SalesOrderController({ frm: cur_frm }));

function prevent_past_delivery_dates(frm) {
	if (frm.doc.transaction_date) {
		frm.fields_dict["delivery_date"].datepicker?.update({
			minDate: new Date(frm.doc.transaction_date),
		});
	}
}
