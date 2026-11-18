# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""HisaabDari has no Inventory Dimensions. Function names match ERPNext's module so the
stock ledger code and custom apps that call them keep working. Each lookup answers "none".
"""

import frappe


def field_exists(doctype, fieldname) -> str | None:
	return frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, "name")


@frappe.whitelist()
def get_inventory_documents(doctype=None, txt=None, searchfield=None, start=None, page_len=None, filters=None):
	return []


def get_evaluated_inventory_dimension(doc, sl_dict, parent_doc=None):
	return []


def get_document_wise_inventory_dimensions(doctype) -> dict:
	return {}


def get_mandatory_inventory_dimensions(doctype) -> list:
	return []


def get_mandatory_dimension_fields(doctype, dimension) -> list:
	return []


@frappe.whitelist()
def get_inventory_dimensions():
	return []
