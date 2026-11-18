from frappe import _


def get_data():
	return {
		"fieldname": "delivery_note",
		"non_standard_fieldnames": {
			"Stock Entry": "delivery_note_no",
			"Auto Repeat": "reference_document",
			"Purchase Receipt": "inter_company_reference",
		},
		"internal_links": {
			"Sales Order": ["items", "against_sales_order"],
			"Purchase Order": ["items", "purchase_order"],
		},
		"internal_and_external_links": {
			"Sales Invoice": ["items", "against_sales_invoice"],
		},
		"transactions": [
			{"label": _("Related"), "items": ["Sales Invoice"]},
			{"label": _("Reference"), "items": ["Sales Order"]},
			{"label": _("Returns"), "items": ["Stock Entry"]},
			{"label": _("Subscription"), "items": ["Auto Repeat"]},
			{
				"label": _("Internal Transfer"),
				"items": ["Purchase Order", "Purchase Receipt"],
			},
		],
	}
