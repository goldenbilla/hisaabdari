# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def get_notification_config():
	notifications = {
		"for_doctype": {
			"Contact": {"status": "Open"},
			"Quotation": {"docstatus": 0},
			"Sales Order": {"status": ("not in", ("Completed", "Closed")), "docstatus": ("<", 2)},
			"Journal Entry": {"docstatus": 0},
			"Sales Invoice": {"outstanding_amount": (">", 0), "docstatus": ("<", 2)},
			"Purchase Invoice": {"outstanding_amount": (">", 0), "docstatus": ("<", 2)},
			"Payment Entry": {"docstatus": 0},
			"Delivery Note": {"status": ("not in", ("Completed", "Closed")), "docstatus": ("<", 2)},
			"Stock Entry": {"docstatus": 0},
			"Purchase Order": {"status": ("not in", ("Completed", "Closed")), "docstatus": ("<", 2)},
			"Purchase Receipt": {"status": ("not in", ("Completed", "Closed")), "docstatus": ("<", 2)},
		},
		"targets": {
			"Company": {
				"filters": {"monthly_sales_target": (">", 0)},
				"target_field": "monthly_sales_target",
				"value_field": "total_monthly_sales",
			}
		},
	}

	doctype = [d for d in notifications.get("for_doctype")]
	for doc in frappe.get_all(
		"DocType", fields=["name"], filters={"name": ("not in", doctype), "is_submittable": 1}
	):
		notifications["for_doctype"][doc.name] = {"docstatus": 0}

	return notifications
