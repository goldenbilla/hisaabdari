// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.selling");

hisaabdari.sales_common = {
	setup_selling_controller: function () {
		hisaabdari.selling.SellingController = class SellingController extends hisaabdari.TransactionController {
			setup() {
				super.setup();
				this.toggle_enable_for_stock_uom("allow_to_edit_stock_uom_qty_for_sales");
				this.frm.email_field = "contact_email";
			}

			onload() {
				super.onload();
				this.setup_queries();
			}

			setup_queries() {
				var me = this;

				$.each([["customer", "customer"]], function (i, opts) {
					if (me.frm.fields_dict[opts[0]]) me.frm.set_query(opts[0], hisaabdari.queries[opts[1]]);
				});

				me.frm.set_query("contact_person", hisaabdari.queries.contact_query);
				me.frm.set_query("company_contact_person", hisaabdari.queries.company_contact_query);
				me.frm.set_query("customer_address", hisaabdari.queries.address_query);
				me.frm.set_query("shipping_address_name", hisaabdari.queries.address_query);
				me.frm.set_query("dispatch_address_name", hisaabdari.queries.dispatch_address_query);
				me.frm.set_query("company_address", hisaabdari.queries.company_address_query);

				hisaabdari.accounts.dimensions.setup_dimension_filters(me.frm, me.frm.doctype);

				if (this.frm.fields_dict.selling_price_list) {
					this.frm.set_query("selling_price_list", function () {
						return { filters: { selling: 1, enabled: 1 } };
					});
				}

				if (this.frm.fields_dict.tc_name) {
					this.frm.set_query("tc_name", function () {
						return { filters: { selling: 1, disabled: 0 } };
					});
				}

				if (!this.frm.fields_dict["items"]) {
					return;
				}

				if (this.frm.fields_dict["items"].grid.get_field("item_code")) {
					this.frm.set_query("item_code", "items", function () {
						let customer = me.frm.doc.customer;
						if (me.frm.doc.doctype == "Quotation" && me.frm.doc.quotation_to == "Customer") {
							customer = me.frm.doc.party_name;
						}
						return {
							query: "hisaabdari.controllers.queries.item_query",
							filters: {
								is_sales_item: 1,
								customer: customer,
								company: me.frm.doc.company,
							},
						};
					});
				}

				if (this.frm.fields_dict["items"].grid.get_field("item_code")) {
					this.frm.set_query("item_tax_template", "items", function (doc, cdt, cdn) {
						return me.set_query_for_item_tax_template(doc, cdt, cdn);
					});
				}
			}

			refresh() {
				super.refresh();

				frappe.dynamic_link = { doc: this.frm.doc, fieldname: "customer", doctype: "Customer" };

				this.frm.toggle_display(
					"customer_name",
					this.frm.doc.customer_name && this.frm.doc.customer_name !== this.frm.doc.customer
				);

				this.toggle_editable_price_list_rate();
				this.change_warehouse_labels_for_return();
			}

			company() {
				super.company();
				this.set_default_company_address();
				if (!this.is_onload) {
					// we don't want to override the mapped contact from prevdoc
					this.set_default_company_contact_person();
				}
			}

			set_default_company_address() {
				if (!frappe.meta.has_field(this.frm.doc.doctype, "company_address")) return;
				var me = this;
				if (this.frm.doc.company) {
					frappe.call({
						method: "hisaabdari.setup.doctype.company.company.get_default_company_address",
						args: {
							name: this.frm.doc.company,
							existing_address: this.frm.doc.company_address || "",
						},
						debounce: 2000,
						callback: function (r) {
							if (r.message) {
								me.frm.set_value("company_address", r.message);
							} else {
								me.frm.set_value("company_address", "");
							}
						},
					});
				}
			}

			set_default_company_contact_person() {
				if (!frappe.meta.has_field(this.frm.doc.doctype, "company_contact_person")) {
					return;
				}

				if (this.frm.doc.company) {
					frappe.db
						.get_value("Company", this.frm.doc.company, "default_sales_contact")
						.then((r) => {
							if (r.message?.default_sales_contact) {
								this.frm.set_value("company_contact_person", r.message.default_sales_contact);
							} else {
								this.frm.set_value("company_contact_person", "");
							}
						});
				}
			}

			customer() {
				var me = this;
				hisaabdari.utils.get_party_details(this.frm, null, null, function () {
					me.apply_price_list();
				});
			}

			customer_address() {
				hisaabdari.utils.get_address_display(this.frm, "customer_address");
			}

			shipping_address_name() {
				hisaabdari.utils.get_address_display(this.frm, "shipping_address_name", "shipping_address");
			}

			dispatch_address_name() {
				hisaabdari.utils.get_address_display(this.frm, "dispatch_address_name", "dispatch_address");
			}

			selling_price_list() {
				this.apply_price_list();
				this.set_dynamic_labels();
			}

			discount_percentage(doc, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				item.discount_amount = 0.0;
				this.apply_discount_on_item(doc, cdt, cdn, "discount_percentage");
			}

			discount_amount(doc, cdt, cdn) {
				if (doc.name === cdn) {
					return;
				}

				var item = frappe.get_doc(cdt, cdn);
				item.discount_percentage = 0.0;
				this.apply_discount_on_item(doc, cdt, cdn, "discount_amount");
			}

			warehouse(doc, cdt, cdn) {
				if (doc.docstatus === 0 && doc.is_return && !doc.return_against) {
					frappe.model.set_value(cdt, cdn, "incoming_rate", 0.0);
				}

				this.set_actual_qty(doc, cdt, cdn);
			}

			set_actual_qty(doc, cdt, cdn) {
				let row = locals[cdt][cdn];
				let sales_doctypes = ["Sales Invoice", "Delivery Note", "Sales Order", "Quotation"];

				if (row.item_code && row.warehouse && sales_doctypes.includes(doc.doctype)) {
					return this.frm.call({
						method: "hisaabdari.stock.get_item_details.get_bin_details",
						child: row,
						args: {
							item_code: row.item_code,
							warehouse: row.warehouse,
							company: doc.company,
							include_child_warehouses: true,
						},
					});
				}
			}

			toggle_editable_price_list_rate() {
				var df = frappe.meta.get_docfield(
					this.frm.doc.doctype + " Item",
					"price_list_rate",
					this.frm.doc.name
				);
				var editable_price_list_rate = cint(frappe.defaults.get_default("editable_price_list_rate"));

				if (df && editable_price_list_rate) {
					const parent_field = frappe.meta.get_parentfield(
						this.frm.doc.doctype,
						this.frm.doc.doctype + " Item"
					);
					if (!this.frm.fields_dict[parent_field]) return;

					this.frm.fields_dict[parent_field].grid.update_docfield_property(
						"price_list_rate",
						"read_only",
						0
					);
				}
			}

			company_address() {
				var me = this;
				if (this.frm.doc.company_address) {
					frappe.call({
						method: "frappe.contacts.doctype.address.address.get_address_display",
						args: { address_dict: this.frm.doc.company_address },
						callback: function (r) {
							if (r.message) {
								me.frm.set_value(
									"company_address_display",
									frappe.utils.html2text(r.message)
								);
							}
						},
					});
				} else {
					this.frm.set_value("company_address_display", "");
				}
			}

			conversion_factor(doc, cdt, cdn, dont_fetch_price_list_rate) {
				super.conversion_factor(doc, cdt, cdn, dont_fetch_price_list_rate);
			}

			qty(doc, cdt, cdn) {
				super.qty(doc, cdt, cdn);
			}

			pick_serial_and_batch(doc, cdt, cdn) {
				let item = locals[cdt][cdn];
				let me = this;

				frappe.db.get_value("Item", item.item_code, ["has_batch_no", "has_serial_no"]).then((r) => {
					if (r.message && (r.message.has_batch_no || r.message.has_serial_no)) {
						item.has_serial_no = r.message.has_serial_no;
						item.has_batch_no = r.message.has_batch_no;
						item.type_of_transaction = item.qty > 0 ? "Outward" : "Inward";

						item.title = item.has_serial_no ? __("Select Serial No") : __("Select Batch No");

						if (item.has_serial_no && item.has_batch_no) {
							item.title = __("Select Serial and Batch");
						}

						new hisaabdari.SerialBatchPackageSelector(me.frm, item, (r) => {
							if (r) {
								let qty = Math.abs(r.total_qty);
								if (doc.is_return) {
									qty = qty * -1;
								}

								frappe.model.set_value(item.doctype, item.name, {
									serial_and_batch_bundle: r.name,
									use_serial_batch_fields: 0,
									incoming_rate: r.avg_rate,
									qty:
										qty /
										flt(
											item.conversion_factor || 1,
											precision("conversion_factor", item)
										),
								});
							}
						});
					}
				});
			}

			update_auto_repeat_reference(doc) {
				if (doc.auto_repeat) {
					frappe.call({
						method: "frappe.automation.doctype.auto_repeat.auto_repeat.update_reference",
						args: {
							docname: doc.auto_repeat,
							reference: doc.name,
						},
						callback: function (r) {
							if (r.message == "success") {
								frappe.show_alert({
									message: __("Auto repeat document updated"),
									indicator: "green",
								});
							} else {
								frappe.show_alert({
									message: __("An error occurred during the update process"),
									indicator: "red",
								});
							}
						},
					});
				}
			}

			is_return() {
				let reset = !this.frm.doc.is_return;
				this.change_warehouse_labels_for_return(reset);
			}

			change_warehouse_labels_for_return(reset) {
				// swap source and target warehouse labels for return
				let source_warehouse_label = __("Source Warehouse");
				let target_warehouse_label = __("Set Target Warehouse");

				if (this.frm.doc.doctype == "Delivery Note") {
					source_warehouse_label = __("Set Source Warehouse");
				}

				if (reset) {
					// reset to original labels
					this.frm.set_df_property("set_warehouse", "label", source_warehouse_label);
					this.frm.set_df_property("set_target_warehouse", "label", target_warehouse_label);
					return;
				}

				if (this.frm.doc.is_return) {
					this.frm.set_df_property("set_warehouse", "label", target_warehouse_label);
					this.frm.set_df_property("set_target_warehouse", "label", source_warehouse_label);
				}
			}
		};
	},
};

hisaabdari.pre_sales = {
	lost_reason_fields: function (doctype) {
		return [
			{
				fieldtype: "Small Text",
				label: __("Detailed Reason"),
				fieldname: "detailed_reason",
			},
		];
	},

	set_as_lost: function (doctype) {
		frappe.ui.form.on(doctype, {
			set_as_lost_dialog: function (frm) {
				var dialog = new frappe.ui.Dialog({
					title: __("Set as Lost"),
					fields: hisaabdari.pre_sales.lost_reason_fields(frm.doctype),
					primary_action: function (values) {
						frm.call({
							doc: frm.doc,
							method: "declare_enquiry_lost",
							args: {
								lost_reasons_list: [],
								competitors: [],
								detailed_reason: values.detailed_reason,
							},
							callback: function (r) {
								dialog.hide();
								frm.reload_doc();
							},
						});
					},
					primary_action_label: __("Declare Lost"),
				});

				dialog.show();
			},
		});
	},
};
