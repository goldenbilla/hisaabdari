from frappe import _


def get_data():
	return {
		"fieldname": "customer",
		"non_standard_fieldnames": {
			"Payment Entry": "party",
			"Quotation": "party_name",
			"Bank Account": "party",
		},
		"dynamic_links": {
			"party_name": ["Customer", "quotation_to"],
			"party": ["Customer", "party_type"],
		},
		"transactions": [
			{"label": _("Pre Sales"), "items": ["Quotation"]},
			{"label": _("Orders"), "items": ["Sales Order", "Delivery Note", "Sales Invoice"]},
			{"label": _("Payments"), "items": ["Payment Entry", "Bank Account"]},
		],
	}
