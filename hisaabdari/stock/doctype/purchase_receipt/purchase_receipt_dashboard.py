from frappe import _


def get_data():
	return {
		"fieldname": "purchase_receipt_no",
		"non_standard_fieldnames": {
			"Purchase Invoice": "purchase_receipt",
			"Auto Repeat": "reference_document",
			"Purchase Receipt": "return_against",
		},
		"internal_links": {
			"Purchase Order": ["items", "purchase_order"],
		},
		"internal_and_external_links": {
			"Purchase Invoice": ["items", "purchase_invoice"],
		},
		"transactions": [
			{
				"label": _("Related"),
				"items": ["Purchase Invoice"],
			},
			{
				"label": _("Reference"),
				"items": ["Purchase Order"],
			},
			{"label": _("Returns"), "items": ["Purchase Receipt"]},
			{"label": _("Subscription"), "items": ["Auto Repeat"]},
		],
	}
