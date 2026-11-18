from frappe import _


def get_data():
	return {
		"fieldname": "sales_order",
		"non_standard_fieldnames": {
			"Delivery Note": "against_sales_order",
			"Journal Entry": "reference_name",
			"Payment Entry": "reference_name",
			"Auto Repeat": "reference_document",
		},
		"internal_links": {
			"Quotation": ["items", "prevdoc_docname"],
			"Purchase Order": ["items", "purchase_order"],
		},
		"transactions": [
			{
				"label": _("Fulfillment"),
				"items": ["Sales Invoice", "Delivery Note"],
			},
			{"label": _("Purchasing"), "items": ["Purchase Order"]},
			{"label": _("Reference"), "items": ["Quotation", "Auto Repeat"]},
			{"label": _("Payment"), "items": ["Payment Entry", "Journal Entry"]},
		],
	}
