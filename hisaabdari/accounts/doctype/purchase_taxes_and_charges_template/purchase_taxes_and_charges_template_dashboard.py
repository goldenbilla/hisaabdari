from frappe import _


def get_data():
	return {
		"fieldname": "taxes_and_charges",
		"transactions": [
			{
				"label": _("Transactions"),
				"items": ["Purchase Invoice", "Purchase Order", "Purchase Receipt"],
			},
		],
	}
