from frappe import _


def get_data():
	return {
		"fieldname": "purchase_order",
		"non_standard_fieldnames": {
			"Journal Entry": "reference_name",
			"Payment Entry": "reference_name",
			"Auto Repeat": "reference_document",
		},
		"internal_links": {
			"Sales Order": ["items", "sales_order"],
		},
		"transactions": [
			{"label": _("Related"), "items": ["Purchase Receipt", "Purchase Invoice", "Sales Order"]},
			{"label": _("Payment"), "items": ["Payment Entry", "Journal Entry"]},
			{
				"label": _("Reference"),
				"items": ["Auto Repeat"],
			},
		],
	}
