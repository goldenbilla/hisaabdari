// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.utils");

const SALES_DOCTYPES = ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"];
const PURCHASE_DOCTYPES = ["Purchase Order", "Purchase Receipt", "Purchase Invoice"];

hisaabdari.utils.get_party_account_currency = function (party, company) {
	// the server allows only accounts in the billing currency, or in the company currency without one
	return party.default_currency || hisaabdari.get_currency(company);
};

hisaabdari.utils.get_party_details = function (frm, method, args, callback) {
	if (!method) {
		method = "hisaabdari.accounts.party.get_party_details";
	}

	if (!args) {
		if (
			(frm.doctype != "Purchase Order" && frm.doc.customer) ||
			(frm.doc.party_name && ["Quotation"].includes(frm.doc.doctype))
		) {
			let party_type = "Customer";

			args = {
				party: frm.doc.customer || frm.doc.party_name,
				party_type: party_type,
				price_list: frappe.defaults.get_default("selling_price_list"),
			};
		} else if (frm.doc.supplier) {
			args = {
				party: frm.doc.supplier,
				party_type: "Supplier",
				bill_date: frm.doc.bill_date,
				price_list: frappe.defaults.get_default("buying_price_list"),
			};
		}

		if (!args) {
			if (SALES_DOCTYPES.includes(frm.doc.doctype)) {
				args = {
					party: frm.doc.customer || frm.doc.party_name,
					party_type: "Customer",
				};
			}

			if (PURCHASE_DOCTYPES.includes(frm.doc.doctype)) {
				args = {
					party: frm.doc.supplier,
					party_type: "Supplier",
				};
			}
		}

		if (!args || !args.party) return;

		args.posting_date = frm.doc.posting_date || frm.doc.transaction_date;
		args.fetch_payment_terms_template = cint(!frm.doc.ignore_default_payment_terms_template);
	}

	if (SALES_DOCTYPES.includes(frm.doc.doctype)) {
		if (!args.company_address && frm.doc.company_address) {
			args.company_address = frm.doc.company_address;
		}
	}

	if (PURCHASE_DOCTYPES.includes(frm.doc.doctype)) {
		if (!args.company_address && frm.doc.billing_address) {
			args.company_address = frm.doc.billing_address;
		}

		if (!args.shipping_address && frm.doc.shipping_address) {
			args.shipping_address = frm.doc.shipping_address;
		}

		if (!args.dispatch_address && frm.doc.dispatch_address) {
			args.dispatch_address = frm.doc.dispatch_address;
		}
	}

	const field = party_field(frm, args.party_type);
	const label = party_label(frm, args.party_type);

	if (frappe.meta.get_docfield(frm.doc.doctype, "taxes") && !args.posting_date) {
		undo_and_throw(
			frm,
			field,
			__("Cannot load {0} details", [label]),
			__("{0} is required to apply taxes. Set {0}, then select {1} again.", [date_label(frm), label])
		);
	}

	if (!frm.doc.company) {
		undo_and_throw(
			frm,
			field,
			__("Cannot load {0} details", [label]),
			__(
				"Company is required to load address, taxes, and payment terms. Set Company, then select {0} again.",
				[label]
			)
		);
	}

	args.currency = frm.doc.currency;
	args.company = frm.doc.company;
	args.doctype = frm.doc.doctype;
	frappe.call({
		method: method,
		args: args,
		callback: function (r) {
			if (r.message) {
				frm.updating_party_details = true;
				frappe.run_serially([
					() => frm.set_value(r.message),
					() => {
						frm.updating_party_details = false;
						if (callback) callback();
						frm.refresh();
						hisaabdari.utils.add_item(frm);
					},
				]);
			}
		},
	});
};

hisaabdari.utils.add_item = function (frm) {
	if (frm.is_new()) {
		var prev_route = frappe.get_prev_route();
		if (prev_route[1] === "Item" && !(frm.doc.items && frm.doc.items.length)) {
			// add row
			var item = frm.add_child("items");
			frm.refresh_field("items");

			// set item
			frappe.model.set_value(item.doctype, item.name, "item_code", prev_route[2]);
		}
	}
};

hisaabdari.utils.get_address_display = function (frm, address_field, display_field, is_your_company_address) {
	if (frm.updating_party_details) return;

	if (!address_field) {
		if (frm.doctype != "Purchase Order" && frm.doc.customer) {
			address_field = "customer_address";
		} else if (frm.doc.supplier) {
			address_field = "supplier_address";
		} else return;
	}

	if (!display_field) display_field = "address_display";
	if (frm.doc[address_field]) {
		frappe.call({
			method: "frappe.contacts.doctype.address.address.get_address_display",
			args: { address_dict: frm.doc[address_field] },
			callback: function (r) {
				if (r.message) {
					frm.set_value(display_field, r.message);
				}
			},
		});
	} else {
		frm.set_value(display_field, "");
	}
};

hisaabdari.utils.get_contact_details = function (frm) {
	if (frm.updating_party_details) return;

	if (!frm.doc.contact_person) {
		reset_contact_fields(frm);
		return;
	}

	frappe.call({
		method: "frappe.contacts.doctype.contact.contact.get_contact_details",
		args: { contact: frm.doc.contact_person },
		callback: function (r) {
			if (r.message) frm.set_value(r.message);
		},
	});
};

function reset_contact_fields(frm) {
	frm.set_value({
		contact_person: "",
		contact_display: "",
		contact_email: "",
		contact_mobile: "",
		contact_phone: "",
		contact_designation: "",
		contact_department: "",
	});
}

hisaabdari.utils.get_shipping_address = function (frm, callback) {
	if (frm.doc.company) {
		if (
			frm.doc.inter_company_order_reference ||
			frm.doc.internal_invoice_reference ||
			frm.doc.internal_order_reference
		) {
			if (callback) {
				return callback();
			}
		}
		frappe.call({
			method: "hisaabdari.accounts.custom.address.get_shipping_address",
			args: {
				company: frm.doc.company,
				address: frm.doc.shipping_address,
			},
			callback: function (r) {
				if (r.message) {
					frm.set_value("shipping_address", r.message[0]); //Address title or name
					frm.set_value("shipping_address_display", r.message[1]); //Address to be displayed on the page
				}

				if (callback) {
					return callback();
				}
			},
		});
	} else {
		frappe.msgprint(__("Select company first"));
	}
};

function party_field(frm, party_type) {
	if (frappe.meta.get_docfield(frm.doc.doctype, "party_name")) {
		return "party_name";
	}
	if (party_type === "Customer") {
		return "customer";
	}
	if (party_type === "Supplier") {
		return "supplier";
	}
	return ["customer", "supplier"].find((field) => frappe.meta.get_docfield(frm.doc.doctype, field));
}

function party_label(frm, party_type) {
	if (frm.doc.quotation_to) {
		return __(frm.doc.quotation_to);
	}
	return frappe.meta.get_translated_label(frm.doc.doctype, party_field(frm, party_type));
}

function date_label(frm) {
	const field = frappe.meta.get_docfield(frm.doc.doctype, "posting_date")
		? "posting_date"
		: "transaction_date";
	return frappe.meta.get_translated_label(frm.doc.doctype, field);
}

function undo_and_throw(frm, field, title, message) {
	frm.doc[field] = "";
	refresh_field(field);
	frappe.throw({ title, message });
}

// Kept for custom client scripts that call this public helper.
hisaabdari.utils.validate_mandatory = function (frm, label, value, trigger_on) {
	if (value) {
		return true;
	}
	undo_and_throw(frm, trigger_on, __("Mandatory"), __("Please enter {0} first", [label]));
	return false;
};
