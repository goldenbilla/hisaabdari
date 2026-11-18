// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.buying");

hisaabdari.buying = {
	setup_buying_controller: function () {
		hisaabdari.buying.BuyingController = class BuyingController extends hisaabdari.TransactionController {
			setup() {
				super.setup();
				this.toggle_enable_for_stock_uom("allow_to_edit_stock_uom_qty_for_purchase");
				this.frm.email_field = "contact_email";
			}

			onload(doc, cdt, cdn) {
				this.setup_queries(doc, cdt, cdn);
				super.onload();

				if (
					this.frm.doc.__islocal &&
					frappe.meta.has_field(this.frm.doc.doctype, "disable_rounded_total")
				) {
					var df = frappe.meta.get_docfield(this.frm.doc.doctype, "disable_rounded_total");
					var disable = cint(df.default) || cint(frappe.sys_defaults.disable_rounded_total);
					this.frm.set_value("disable_rounded_total", disable);
				}

				// no idea where me is coming from
				if (this.frm.get_field("shipping_address")) {
					this.frm.set_query("shipping_address", () => {
						if (this.frm.doc.customer) {
							return {
								query: "frappe.contacts.doctype.address.address.address_query",
								filters: { link_doctype: "Customer", link_name: this.frm.doc.customer },
							};
						} else return hisaabdari.queries.company_address_query(this.frm.doc);
					});
				}

				if (this.frm.get_field("dispatch_address")) {
					this.frm.set_query("dispatch_address", () => {
						return hisaabdari.queries.address_query(this.frm.doc);
					});
				}
			}

			setup_queries(doc, cdt, cdn) {
				var me = this;

				if (this.frm.fields_dict.buying_price_list) {
					this.frm.set_query("buying_price_list", function () {
						return {
							filters: { buying: 1, enabled: 1 },
						};
					});
				}

				if (this.frm.fields_dict.tc_name) {
					this.frm.set_query("tc_name", function () {
						return {
							filters: { buying: 1, disabled: 0 },
						};
					});
				}

				me.frm.set_query("supplier", hisaabdari.queries.supplier);
				me.frm.set_query("contact_person", hisaabdari.queries.contact_query);
				me.frm.set_query("supplier_address", hisaabdari.queries.address_query);

				me.frm.set_query("billing_address", hisaabdari.queries.company_address_query);
				hisaabdari.accounts.dimensions.setup_dimension_filters(me.frm, me.frm.doctype);

				this.frm.set_query("item_code", "items", function () {
					return {
						query: "hisaabdari.controllers.queries.item_query",
						filters: {
							supplier: me.frm.doc.supplier,
							is_purchase_item: 1,
							company: me.frm.doc.company,
						},
					};
				});

				if (this.frm.fields_dict["items"].grid.get_field("item_code")) {
					this.frm.set_query("item_tax_template", "items", function (doc, cdt, cdn) {
						return me.set_query_for_item_tax_template(doc, cdt, cdn);
					});
				}
			}

			refresh(doc) {
				frappe.dynamic_link = { doc: this.frm.doc, fieldname: "supplier", doctype: "Supplier" };

				this.frm.toggle_display(
					"supplier_name",
					this.frm.doc.supplier_name && this.frm.doc.supplier_name !== this.frm.doc.supplier
				);

				super.refresh();
			}

			supplier() {
				var me = this;
				hisaabdari.utils.get_party_details(this.frm, null, null, function () {
					me.apply_price_list();
				});
			}

			company() {
				super.company();
				if (!frappe.meta.has_field(this.frm.doc.doctype, "billing_address")) return;

				frappe.call({
					method: "hisaabdari.setup.doctype.company.company.get_billing_shipping_address",
					args: {
						name: this.frm.doc.company,
						billing_address: this.frm.doc.billing_address,
						shipping_address: this.frm.doc.shipping_address,
					},
					callback: (r) => {
						if (!r.message) return;

						this.frm.set_value("billing_address", r.message.primary_address || "");

						const is_drop_ship = this.frm.doc.items.some((item) => item.delivered_by_supplier);
						if (
							frappe.meta.has_field(this.frm.doc.doctype, "shipping_address") &&
							!is_drop_ship
						) {
							this.frm.set_value("shipping_address", r.message.shipping_address || "");
						}
					},
				});
				hisaabdari.utils.set_letter_head(this.frm);
			}

			supplier_address() {
				hisaabdari.utils.get_address_display(this.frm);
			}

			buying_price_list() {
				this.apply_price_list();
			}

			discount_percentage(doc, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				item.discount_amount = 0.0;
				this.price_list_rate(doc, cdt, cdn);
			}

			discount_amount(doc, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				item.discount_percentage = 0.0;
				this.price_list_rate(doc, cdt, cdn);
			}

			qty(doc, cdt, cdn) {
				if (
					doc.doctype == "Purchase Receipt" ||
					(doc.doctype == "Purchase Invoice" && doc.update_stock)
				) {
					this.calculate_received_qty(doc, cdt, cdn);
				}
				super.qty(doc, cdt, cdn);
			}

			rejected_qty(doc, cdt, cdn) {
				this.calculate_received_qty(doc, cdt, cdn);
			}

			calculate_received_qty(doc, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				frappe.model.round_floats_in(item, ["qty", "rejected_qty"]);

				if (
					!doc.is_return &&
					this.validate_negative_quantity(cdt, cdn, item, ["qty", "rejected_qty"])
				) {
					return;
				}

				let received_qty = flt(item.qty + item.rejected_qty, precision("received_qty", item));
				let received_stock_qty =
					flt(item.conversion_factor, precision("conversion_factor", item)) * flt(received_qty);

				frappe.model.set_value(cdt, cdn, "received_qty", received_qty);
				frappe.model.set_value(cdt, cdn, "received_stock_qty", received_stock_qty);
			}

			batch_no(doc, cdt, cdn) {
				super.batch_no(doc, cdt, cdn);
			}

			validate_negative_quantity(cdt, cdn, item, fieldnames) {
				if (!item || !fieldnames) {
					return;
				}

				var is_negative_qty = false;
				for (var i = 0; i < fieldnames.length; i++) {
					if (item[fieldnames[i]] < 0) {
						frappe.msgprint(
							__("Row #{0}: {1} can not be negative for item {2}", [
								item.idx,
								__(frappe.meta.get_label(cdt, fieldnames[i], cdn)),
								item.item_code,
							])
						);
						is_negative_qty = true;
						break;
					}
				}

				return is_negative_qty;
			}

			warehouse(doc, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				if (item.item_code && item.warehouse) {
					return this.frm.call({
						method: "hisaabdari.stock.get_item_details.get_bin_details",
						child: item,
						args: {
							item_code: item.item_code,
							warehouse: item.warehouse,
							company: doc.company,
							include_child_warehouses: true,
						},
					});
				}
			}

			rejected_warehouse(doc, cdt) {
				// trigger autofill_warehouse only if parent rejected_warehouse field is triggered
				if (["Purchase Invoice", "Purchase Receipt"].includes(cdt)) {
					this.autofill_warehouse(doc.items, "rejected_warehouse", doc.rejected_warehouse);
				}
			}

			category(doc, cdt, cdn) {
				// should be the category field of tax table
				if (cdt != doc.doctype) {
					this.calculate_taxes_and_totals();
				}
			}
			add_deduct_tax(doc, cdt, cdn) {
				this.calculate_taxes_and_totals();
			}

			shipping_address() {
				var me = this;
				hisaabdari.utils.get_address_display(
					this.frm,
					"shipping_address",
					"shipping_address_display",
					true
				);
			}

			dispatch_address() {
				var me = this;
				hisaabdari.utils.get_address_display(
					this.frm,
					"dispatch_address",
					"dispatch_address_display",
					true
				);
			}

			billing_address() {
				hisaabdari.utils.get_address_display(
					this.frm,
					"billing_address",
					"billing_address_display",
					true
				);
			}

			tc_name() {
				this.get_terms();
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

			add_serial_batch_bundle(doc, cdt, cdn) {
				let item = locals[cdt][cdn];
				let me = this;
				let fields = ["has_batch_no", "has_serial_no"];

				frappe.db.get_value("Item", item.item_code, fields).then((r) => {
					if (r.message && (r.message.has_batch_no || r.message.has_serial_no)) {
						fields.forEach((field) => {
							item[field] = r.message[field];
						});

						item.type_of_transaction = item.qty > 0 ? "Inward" : "Outward";
						item.is_rejected = false;

						new hisaabdari.SerialBatchPackageSelector(me.frm, item, (r) => {
							if (r) {
								let qty = Math.abs(r.total_qty);
								if (doc.is_return) {
									qty = qty * -1;
								}

								let update_values = {
									serial_and_batch_bundle: r.name,
									use_serial_batch_fields: 0,
									qty:
										qty /
										flt(
											item.conversion_factor || 1,
											precision("conversion_factor", item)
										),
								};

								if (r.warehouse) {
									update_values["warehouse"] = r.warehouse;
								}

								frappe.model.set_value(item.doctype, item.name, update_values);
							}
						});
					}
				});
			}

			add_serial_batch_for_rejected_qty(doc, cdt, cdn) {
				let item = locals[cdt][cdn];
				let me = this;
				let fields = ["has_batch_no", "has_serial_no"];

				frappe.db.get_value("Item", item.item_code, fields).then((r) => {
					if (r.message && (r.message.has_batch_no || r.message.has_serial_no)) {
						fields.forEach((field) => {
							item[field] = r.message[field];
						});

						item.type_of_transaction = !doc.is_return > 0 ? "Inward" : "Outward";
						item.is_rejected = true;

						new hisaabdari.SerialBatchPackageSelector(me.frm, item, (r) => {
							if (r) {
								let qty = Math.abs(r.total_qty);
								if (doc.is_return) {
									qty = qty * -1;
								}

								let update_values = {
									rejected_serial_and_batch_bundle: r.name,
									use_serial_batch_fields: 0,
									rejected_qty:
										qty /
										flt(
											item.conversion_factor || 1,
											precision("conversion_factor", item)
										),
								};

								if (r.warehouse) {
									update_values["rejected_warehouse"] = r.warehouse;
								}

								frappe.model.set_value(item.doctype, item.name, update_values);
							}
						});
					}
				});
			}
		};
	},
};

hisaabdari.buying.prevent_past_schedule_dates = function (frm) {
	if (frm.doc.transaction_date) {
		frm.fields_dict["schedule_date"].datepicker?.update({
			minDate: new Date(frm.doc.transaction_date),
		});
	}
};
