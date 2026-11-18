// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.item");

const SALES_DOCTYPES = ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"];
const PURCHASE_DOCTYPES = ["Purchase Order", "Purchase Receipt", "Purchase Invoice"];

frappe.ui.form.on("Item", {
	stock_uom(frm) {
		// Each factor is relative to Stock UOM and becomes invalid when it changes.
		frm.clear_table("uoms");
		frm.refresh_field("uoms");
	},

	valuation_method(frm) {
		if (!frm.is_new() && frm.doc.valuation_method === "Moving Average") {
			let stock_exists = frm.doc.__onload && frm.doc.__onload.stock_exists ? 1 : 0;
			let current_valuation_method = frm.doc.__onload.current_valuation_method;

			if (stock_exists && current_valuation_method !== frm.doc.valuation_method) {
				let msg = __(
					"Changing the valuation method to Moving Average will affect new transactions. If backdated entries are added, earlier FIFO-based entries will be reposted, which may change closing balances."
				);
				msg += "<br><br>";
				msg += __(
					"Also you can't switch back to FIFO after setting the valuation method to Moving Average for this item."
				);
				msg += "<br><br>";
				msg += __("Do you want to change valuation method?");

				frappe.confirm(
					msg,
					() => {
						frm.set_value("valuation_method", "Moving Average");
					},
					() => {
						frm.set_value("valuation_method", current_valuation_method);
					}
				);
			}
		}
	},

	restrict_to_companies(frm) {
		if (!frm.doc.restrict_to_companies) {
			frm.set_value("allowed_companies", []);
		}
	},

	setup: function (frm) {
		frm.set_query("item_group", () => ({ filters: { is_group: 0 } }));
		frm.set_query("allowed_companies", () => ({
			query: "hisaabdari.stock.doctype.company_restriction.company_restriction.company_query",
		}));
		frm.add_fetch("tax_type", "tax_rate", "tax_rate");

		frm.make_methods = {
			Quotation: () => {
				open_form(frm, "Quotation", "Quotation Item", "items");
			},
			"Sales Order": () => {
				open_form(frm, "Sales Order", "Sales Order Item", "items");
			},
			"Delivery Note": () => {
				open_form(frm, "Delivery Note", "Delivery Note Item", "items");
			},
			"Sales Invoice": () => {
				open_form(frm, "Sales Invoice", "Sales Invoice Item", "items");
			},
			"Purchase Order": () => {
				open_form(frm, "Purchase Order", "Purchase Order Item", "items");
			},
			"Purchase Receipt": () => {
				open_form(frm, "Purchase Receipt", "Purchase Receipt Item", "items");
			},
			"Purchase Invoice": () => {
				open_form(frm, "Purchase Invoice", "Purchase Invoice Item", "items");
			},
			"Stock Entry": () => {
				open_form(frm, "Stock Entry", "Stock Entry Detail", "items");
			},
		};
	},

	onload: function (frm) {
		hisaabdari.item.setup_queries(frm);
	},

	toggle_has_serial_batch_fields(frm) {
		let hide_fields = cint(frappe.user_defaults?.enable_serial_and_batch_no_for_item) === 0 ? 1 : 0;

		frm.toggle_display(
			[
				"serial_no_series",
				"batch_number_series",
				"create_new_batch",
				"has_expiry_date",
				"retain_sample",
			],
			!hide_fields
		);
		frm.toggle_enable(["has_serial_no", "has_batch_no"], !hide_fields);

		if (hide_fields) {
			let header = frm.fields_dict["serial_nos_and_batches"].wrapper;
			let wrapper = header.find(".section-head.collapsible");

			render_serial_batch_banner(wrapper);

			if (!wrapper.data("banner-handler-added")) {
				wrapper.data("banner-handler-added", true);

				wrapper.on("click", function () {
					setTimeout(() => {
						let isCollapsed = $(this).hasClass("collapsed");

						wrapper.find(".custom-serial-batch-banner").toggleClass("hidden", isCollapsed);
					}, 10);
				});
			}

			// Button action
			wrapper.find(".go-to-settings").on("click", function () {
				frappe.set_route("Form", "Stock Settings");
			});
		}
	},

	refresh: function (frm) {
		frm.trigger("toggle_has_serial_batch_fields");

		if (frappe.defaults.get_default("item_naming_by") != "Naming Series") {
			frm.toggle_display("naming_series", false);
		} else {
			hisaabdari.toggle_naming_series();
		}

		frm.toggle_display(["standard_rate"], frappe.model.can_create("Item Price"));

		if (frm.is_new()) {
			frm.toggle_display("disabled", false);
			return;
		}

		frm.toggle_display("disabled", true);

		if (frm.doc.is_stock_item) {
			frm.add_custom_button(
				__("Stock Balance"),
				function () {
					frappe.route_options = {
						item_code: frm.doc.name,
					};
					frappe.set_route("query-report", "Stock Balance");
				},
				__("View")
			);
			frm.add_custom_button(
				__("Stock Ledger"),
				function () {
					frappe.route_options = {
						item_code: frm.doc.name,
					};
					frappe.set_route("query-report", "Stock Ledger");
				},
				__("View")
			);
			frm.add_custom_button(
				__("Stock Projected Qty"),
				function () {
					frappe.route_options = {
						item_code: frm.doc.name,
					};
					frappe.set_route("query-report", "Stock Projected Qty");
				},
				__("View")
			);

			const can_create_stock_entry =
				frappe.model.can_create("Stock Entry") && frappe.model.can_write("Stock Entry");

			const has_existing_stock = frm.doc.__onload && frm.doc.__onload.stock_exists ? 1 : 0;

			if (can_create_stock_entry && !has_existing_stock) {
				frm.add_custom_button(
					__("Set Opening Stock"),
					() => hisaabdari.item.show_opening_stock_dialog(frm),
					__("Actions")
				);
			}
		}

		// clear intro
		frm.set_intro();

		hisaabdari.item.make_dashboard(frm);

		hisaabdari.item.render_item_prices(frm);

		frm.add_custom_button(__("Duplicate"), function () {
			// frm.copy_doc skips link triggers, so stock_uom does not clear the copied UOMs
			frm.copy_doc((new_item) => {
				// Duplicate item could have different name, causing "copy paste" error.
				if (new_item.item_name === new_item.item_code) {
					new_item.item_name = null;
				}
				if (new_item.item_code === new_item.description) {
					new_item.description = null;
				}
			});
		});

		const stock_exists = frm.doc.__onload && frm.doc.__onload.stock_exists ? 1 : 0;

		[
			"is_stock_item",
			"is_customer_provided_item",
			"has_serial_no",
			"has_batch_no",
		].forEach((fieldname) => {
			frm.set_df_property(fieldname, "read_only", stock_exists);
		});
	},

	validate: function (frm) {
		hisaabdari.item.weight_to_validate(frm);
	},

	image: function () {
		refresh_field("image_view");
	},

	page_name: frappe.utils.warn_page_name_change,

	item_code: function (frm) {
		if (!frm.doc.item_name) frm.set_value("item_name", frm.doc.item_code);
	},

	is_stock_item: function (frm) {
		if (!frm.doc.is_stock_item) {
			frm.set_value("has_batch_no", 0);
			frm.set_value("create_new_batch", 0);
			frm.set_value("has_serial_no", 0);
		}
	},
});

frappe.ui.form.on("Item Reorder", {
	warehouse_group(frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		if (!row.warehouse_group) {
			frappe.throw(__("Please select the Warehouse first"));
		}
	},
});

frappe.ui.form.on("Item Customer Detail", {
	customer_items_add: function (frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "customer_group", "");
	},
	customer_name: function (frm, cdt, cdn) {
		set_customer_group(frm, cdt, cdn);
	},
	customer_group: function (frm, cdt, cdn) {
		if (set_customer_group(frm, cdt, cdn)) {
			frappe.msgprint(__("Changing Customer Group for the selected Customer is not allowed."));
		}
	},
});

var set_customer_group = function (frm, cdt, cdn) {
	var row = frappe.get_doc(cdt, cdn);

	if (!row.customer_name) {
		return false;
	}

	frappe.model.with_doc("Customer", row.customer_name, function () {
		var customer = frappe.model.get_doc("Customer", row.customer_name);
		row.customer_group = customer.customer_group;
		refresh_field("customer_group", cdn, "customer_items");
	});
	return true;
};

function render_serial_batch_banner(wrapper) {
	let hiddenClass = "";
	if (wrapper.hasClass("collapsed")) {
		hiddenClass = "hidden";
	}

	wrapper.find(".custom-serial-batch-banner").remove();

	let banner_html = `
		<div class="custom-serial-batch-banner ${hiddenClass}">
			<div class="banner-content">
				<span class="banner-icon">${frappe.utils.icon("triangle-alert", "lg", "", "padding-bottom:2px")}</span>
				<span class="banner-text">
					${__("To use Serial / Batch feature, enable {0} in {1}.", [
						`<b>${__("Activate Serial / Batch No for Item")}</b>`,
						`<a class="go-to-settings" style="text-decoration: underline;">${__(
							"Stock Settings"
						)}</a>`,
					])}
				</span>
			</div>
		</div>
		<style>
			.custom-serial-batch-banner {
				background-color: var(--amber-50);
				border: 1px solid var(--amber-50);
				border-radius: 8px;
				padding: 12px 16px;
				margin-top: 16px;
			}

			.custom-serial-batch-banner .banner-content {
				display: flex;
				align-items: center;
				gap: 12px;
			}

			.custom-serial-batch-banner .banner-icon {
				font-size: 18px;
			}

			.custom-serial-batch-banner .banner-text {
				flex: 1;
				font-size: 14px;
				color: var(--gray-800);
			}

			.custom-serial-batch-banner .btn {
				white-space: nowrap;
			}
		</style>
	`;

	// Insert banner at top of section
	wrapper.append(banner_html);
}

$.extend(hisaabdari.item, {
	setup_queries: function (frm) {
		frm.fields_dict["item_defaults"].grid.get_field("expense_account").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				query: "hisaabdari.controllers.queries.get_expense_account",
				filters: { company: row.company },
			};
		};

		frm.fields_dict["item_defaults"].grid.get_field("income_account").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				query: "hisaabdari.controllers.queries.get_income_account",
				filters: { company: row.company },
			};
		};

		frm.fields_dict["item_defaults"].grid.get_field("default_inventory_account").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				filters: { company: row.company, account_type: "Stock", is_group: 0 },
			};
		};

		frm.fields_dict["item_defaults"].grid.get_field("default_discount_account").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				filters: {
					report_type: "Profit and Loss",
					company: row.company,
					is_group: 0,
				},
			};
		};

		frm.fields_dict["item_defaults"].grid.get_field("buying_cost_center").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				filters: {
					is_group: 0,
					company: row.company,
				},
			};
		};

		frm.fields_dict["item_defaults"].grid.get_field("selling_cost_center").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				filters: {
					is_group: 0,
					company: row.company,
				},
			};
		};

		frm.fields_dict["taxes"].grid.get_field("tax_type").get_query = function (doc, cdt, cdn) {
			return {
				filters: [
					["Account", "account_type", "in", "Tax, Chargeable, Income Account, Expense Account"],
					["Account", "docstatus", "!=", 2],
				],
			};
		};

		frm.fields_dict["item_defaults"].grid.get_field("default_warehouse").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const row = locals[cdt][cdn];
			return {
				filters: {
					is_group: 0,
					company: row.company,
				},
			};
		};

		frm.fields_dict.reorder_levels.grid.get_field("warehouse_group").get_query = function (
			doc,
			cdt,
			cdn
		) {
			let row = locals[cdt][cdn];
			return {
				query: "hisaabdari.stock.doctype.warehouse.warehouse.get_warehouses_for_reorder",
				filters: {
					warehouse: row.warehouse,
				},
			};
		};

		frm.fields_dict.reorder_levels.grid.get_field("warehouse").get_query = function (doc, cdt, cdn) {
			var d = locals[cdt][cdn];

			var filters = {
				is_group: 0,
			};

			if (d.parent_warehouse) {
				filters.extend({ parent_warehouse: d.warehouse_group });
			}

			return {
				filters: filters,
			};
		};

		frm.set_query("default_provisional_account", "item_defaults", (doc, cdt, cdn) => {
			let row = locals[cdt][cdn];
			return {
				filters: {
					company: row.company,
					root_type: ["in", ["Liability", "Asset"]],
					is_group: 0,
				},
			};
		});

		let fields = [
			"purchase_expense_account",
			"purchase_expense_contra_account",
			"expenses_added_to_stock_account",
			"expenses_added_to_stock_contra_account",
			"default_cogs_account",
		];

		fields.forEach((field) => {
			frm.set_query(field, "item_defaults", (doc, cdt, cdn) => {
				let row = locals[cdt][cdn];
				return {
					filters: {
						company: row.company,
						root_type: "Expense",
						is_group: 0,
					},
				};
			});
		});

		frm.set_query("default_inventory_account", "item_defaults", (doc, cdt, cdn) => {
			let row = locals[cdt][cdn];
			return {
				filters: {
					is_group: 0,
					company: row.company,
					account_type: "Stock",
				},
			};
		});
	},

	make_dashboard: function (frm) {
		if (frm.doc.__islocal) return;

		if (frm.doc.is_stock_item) {
			frappe.require("item-dashboard.bundle.js", function () {
				const section = frm.fields_dict["stock_levels_html"].$wrapper;

				hisaabdari.item.item_dashboard = new hisaabdari.stock.ItemDashboard({
					parent: section,
					item_code: frm.doc.name,
					page_length: 20,
					method: "hisaabdari.stock.dashboard.item_dashboard.get_data",
					template: "item_dashboard_list",
				});
				hisaabdari.item.item_dashboard.refresh();
			});
		}
	},

	render_item_prices: function (frm) {
		if (frm.doc.__islocal) return;

		if (!frappe.model.can_read("Item Price")) {
			frm.toggle_display("prices_html", false);
			return;
		}
		frm.toggle_display("prices_html", true);

		frappe.require("embedded_list.bundle.js", () => hisaabdari.item.build_prices_list(frm));
	},

	build_prices_list: function (frm) {
		const item_code = frm.doc.name;
		const container = frm.fields_dict["prices_html"].$wrapper.empty();

		const list = new frappe.ui.EmbeddedList({
			wrapper: $("<div></div>").appendTo(container),
			description: __("All active prices for this item across buying and selling price lists."),
			show_index: true,
			show_search: false,
			empty_icon: "tag",
			empty_message: __("No active item prices found."),
			add_button: {
				label: __("Add Price"),
				action: () => hisaabdari.item.new_item_price(frm),
			},
			on_row_click: (row) => frappe.set_route("Form", "Item Price", row.name),
			get_data() {
				return frappe
					.xcall("hisaabdari.stock.doctype.item.item.get_item_prices", { item_code })
					.then((r) => {
						this._has_more = r.has_more;
						return r.prices;
					});
			},
			before_render() {
				this._all_data.forEach((row) => {
					row.price_type =
						row.buying && row.selling
							? __("Buy & Sell")
							: row.buying
							? __("Buying")
							: __("Selling");
				});
			},
			columns: [
				{ label: __("Price List"), fieldname: "price_list" },
				{
					label: __("Type"),
					type: "badge",
					fieldname: "price_type",
				},
				{
					label: __("Party"),
					type: "link",
					text: (row) => row.customer || row.supplier || "",
					route: (row) => [
						"Form",
						row.customer ? "Customer" : "Supplier",
						row.customer || row.supplier,
					],
				},
				{
					label: __("Rate"),
					fieldname: "price_list_rate",
					render: (row) => format_currency(row.price_list_rate, row.currency),
				},
				{
					label: __("UOM"),
					fieldname: "uom",
					render: (row) => frappe.utils.escape_html(row.uom || frm.doc.stock_uom || ""),
				},
				{
					label: __("Valid Upto"),
					fieldname: "valid_upto",
					render: (row) => (row.valid_upto ? frappe.datetime.str_to_user(row.valid_upto) : ""),
				},
			],
		});

		list.refresh().then(() => {
			if (!list._has_more) return;
			frappe.ui
				.button({
					label: __("View All Prices"),
					variant: "subtle",
					size: "sm",
					onclick: () => {
						frappe.route_options = { item_code };
						frappe.set_route("List", "Item Price");
					},
				})
				.appendTo(
					$('<div class="flex justify-end" style="margin-bottom: 8px;"></div>').appendTo(container)
				);
		});
	},

	new_item_price: function (frm) {
		const filters = {};
		if (frm.doc.is_sales_item && !frm.doc.is_purchase_item) {
			filters.selling = 1;
		} else if (frm.doc.is_purchase_item && !frm.doc.is_sales_item) {
			filters.buying = 1;
		}
		frappe.new_doc("Item Price", { item_code: frm.doc.name, uom: frm.doc.stock_uom }, (dialog) => {
			if (Object.keys(filters).length) {
				dialog.fields_dict.price_list.get_query = () => ({ filters });
			}
		});
	},

	show_opening_stock_dialog: function (frm) {
		const has_serial = cint(frm.doc.has_serial_no);
		const has_batch = cint(frm.doc.has_batch_no);

		if (has_serial || has_batch) {
			const default_company = frappe.defaults.get_default("company");
			const row = (frm.doc.item_defaults || []).find((d) => d.company === default_company);
			const default_warehouse = (row && row.default_warehouse) || "";

			frappe.route_options = {
				purpose: "Opening Stock",
				company: default_company,
			};

			frappe.new_doc("Stock Reconciliation", null, (doc) => {
				const child = doc.items[0];
				frappe.model.set_value(child.doctype, child.name, "item_code", frm.doc.name);
				if (default_warehouse) {
					frappe.model.set_value(child.doctype, child.name, "warehouse", default_warehouse);
				}
			});
			return;
		}

		const companies = (frm.doc.item_defaults || []).map((d) => d.company).filter(Boolean);

		if (!companies.length) {
			frappe.msgprint({
				title: __("No Company Found"),
				message: __(
					"Please add at least one row in Item Defaults with a Company before setting opening stock."
				),
				indicator: "orange",
			});
			return;
		}

		const get_warehouse_for_company = (company) => {
			const row = (frm.doc.item_defaults || []).find((d) => d.company === company);
			return (row && row.default_warehouse) || "";
		};

		const fields = [
			{
				label: __("Company"),
				fieldname: "company",
				fieldtype: "Select",
				options: companies.join("\n"),
				default: companies[0],
				reqd: 1,
				onchange: function () {
					const warehouse = get_warehouse_for_company(dialog.get_value("company"));
					dialog.set_value("warehouse", warehouse);
					dialog.set_df_property(
						"warehouse",
						"description",
						warehouse
							? __("Default warehouse from Item Defaults.")
							: __(
									"No default warehouse set for this company. Entry will use Stock Settings default."
							  )
					);
				},
			},
			{
				label: __("Default Warehouse"),
				fieldname: "warehouse",
				fieldtype: "Data",
				read_only: 1,
				description: __("Default warehouse from Item Defaults."),
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Opening Stock"),
				fieldname: "qty",
				fieldtype: "Float",
				default: frm.doc.opening_stock || 1,
				reqd: 1,
			},
			{
				label: __("Valuation Rate"),
				fieldname: "valuation_rate",
				fieldtype: "Currency",
				default: frm.doc.valuation_rate || 0,
				description: __("Leave as 0 to allow zero valuation rate."),
			},
		];

		const dialog = new frappe.ui.Dialog({
			title: __("Add Opening Stock"),
			fields: fields,
			primary_action_label: __("Save"),
			primary_action: function (values) {
				frappe.call({
					method: "hisaabdari.stock.doctype.item.item.make_opening_stock_entry",
					args: {
						item_code: frm.doc.name,
						company: values.company,
						qty: values.qty,
						valuation_rate: values.valuation_rate || 0,
						warehouse: values.warehouse || null,
					},
					freeze: true,
					freeze_message: __("Creating Opening Stock Entry..."),
					callback: function (r) {
						if (!r.exc && r.message) {
							dialog.hide();
							frm.reload_doc();
						}
					},
				});
			},
		});

		dialog.set_value("warehouse", get_warehouse_for_company(companies[0]));
		dialog.show();
		dialog.add_custom_action(__("Edit Full Form"), function () {
			const default_company = frappe.defaults.get_default("company");
			const row = (frm.doc.item_defaults || []).find((d) => d.company === default_company);

			frappe.route_options = {
				purpose: "Opening Stock",
				company: default_company,
			};

			frappe.new_doc("Stock Reconciliation", null, (doc) => {
				const child = doc.items[0];
				frappe.model.set_value(child.doctype, child.name, "item_code", frm.doc.name);
				if (row && row.default_warehouse) {
					frappe.model.set_value(child.doctype, child.name, "warehouse", row.default_warehouse);
				}
			});

			dialog.hide();
		});
	},

	weight_to_validate: function (frm) {
		if (frm.doc.weight_per_unit && !frm.doc.weight_uom) {
			frappe.msgprint({
				message: __("Please mention 'Weight UOM' along with Weight."),
				title: __("Note"),
			});
		}
	},
});

frappe.ui.form.on("UOM Conversion Detail", {
	uom: function (frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (row.uom) {
			frappe.call({
				method: "hisaabdari.stock.doctype.item.item.get_uom_conv_factor",
				args: {
					uom: row.uom,
					stock_uom: frm.doc.stock_uom,
				},
				callback: function (r) {
					if (!r.exc && r.message) {
						frappe.model.set_value(cdt, cdn, "conversion_factor", r.message);
					}
				},
			});
		}
	},
});

frappe.tour["Item"] = [
	{
		fieldname: "item_code",
		title: "Item Code",
		description: __(
			"Enter an Item Code, the name will be auto-filled the same as Item Code on clicking inside the Item Name field."
		),
	},
	{
		fieldname: "item_group",
		title: "Item Group",
		description: __("Select an Item Group."),
	},
	{
		fieldname: "is_stock_item",
		title: "Maintain Stock",
		description: __(
			"If you are maintaining stock of this Item in your Inventory, HisaabDari will make a stock ledger entry for each transaction of this item."
		),
	},
	{
		fieldname: "opening_stock",
		title: "Opening Stock",
		description: __("Enter the opening stock units."),
	},
	{
		fieldname: "valuation_rate",
		title: "Valuation Rate",
		description: __(
			"There are two options to maintain valuation of stock. FIFO (first in - first out) and Moving Average. To understand this topic in detail please visit <a href='https://docs.frappe.io/erpnext/user/manual/en/calculation-of-valuation-rate-in-fifo-and-moving-average' target='_blank'>Item Valuation, FIFO and Moving Average.</a>"
		),
	},
	{
		fieldname: "standard_rate",
		title: "Standard Selling Rate",
		description: __(
			"When creating an Item, entering a value for this field will automatically create an Item Price at the backend."
		),
	},
	{
		fieldname: "item_defaults",
		title: "Item Defaults",
		description: __(
			"In this section, you can define Company-wide transaction-related defaults for this Item. Eg. Default Warehouse, Default Price List, Supplier, etc."
		),
	},
];

function open_form(frm, doctype, child_doctype, parentfield) {
	frappe.model.with_doctype(doctype, () => {
		let new_doc = frappe.model.get_new_doc(doctype);

		let new_child_doc = frappe.model.add_child(new_doc, child_doctype, parentfield);
		new_child_doc.item_code = frm.doc.name;
		new_child_doc.item_name = frm.doc.item_name;
		if (SALES_DOCTYPES.includes(doctype) && frm.doc.sales_uom) {
			new_child_doc.uom = frm.doc.sales_uom;
		} else if (PURCHASE_DOCTYPES.includes(doctype) && frm.doc.purchase_uom) {
			new_child_doc.uom = frm.doc.purchase_uom;
		} else {
			new_child_doc.uom = frm.doc.stock_uom;
		}
		new_child_doc.description = frm.doc.description;
		if (!new_child_doc.qty) {
			new_child_doc.qty = 1.0;
		}

		frappe.run_serially([
			() => frappe.ui.form.make_quick_entry(doctype, null, null, new_doc),
			() => {
				frappe.flags.ignore_company_party_validation = true;
				frappe.model.trigger("item_code", frm.doc.name, new_child_doc);
			},
		]);
	});
}
