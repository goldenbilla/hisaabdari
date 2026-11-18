from frappe import _


def get_data():
	return {
		"fieldname": "taxes_and_charges",
		"transactions": [
			{"label": _("Transactions"), "items": ["Sales Invoice", "Sales Order", "Delivery Note"]},
		],
	}
