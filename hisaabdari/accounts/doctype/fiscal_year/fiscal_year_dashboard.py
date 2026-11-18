from frappe import _


def get_data():
	return {
		"fieldname": "fiscal_year",
		"transactions": [
			{"label": _("References"), "items": ["Period Closing Voucher"]},
		],
	}
