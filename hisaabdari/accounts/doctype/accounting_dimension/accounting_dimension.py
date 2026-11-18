# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""HisaabDari has no custom Accounting Dimensions; Cost Center is the only dimension.

This module keeps the function names of ERPNext's accounting_dimension module so the
ledger code and custom apps that call them keep working. Each lookup answers "none".
"""

import frappe


def get_doctypes_with_dimensions():
	return frappe.get_hooks("accounting_dimension_doctypes")


def get_accounting_dimensions(as_list=True):
	return []


def get_checks_for_pl_and_bs_accounts():
	return []


def get_dimension_with_children(doctype, dimensions):
	if isinstance(dimensions, str):
		dimensions = [dimensions]

	all_dimensions = []

	for dimension in dimensions:
		lft, rgt = frappe.db.get_value(doctype, dimension, ["lft", "rgt"])
		children = frappe.get_all(doctype, filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, order_by="lft")
		all_dimensions += [c.name for c in children]

	return all_dimensions


@frappe.whitelist()
def get_dimensions(with_cost_center_and_project=False):
	dimension_filters = []

	if isinstance(with_cost_center_and_project, str):
		with_cost_center_and_project = with_cost_center_and_project.lower().strip() == "true"

	if with_cost_center_and_project:
		dimension_filters.append(frappe._dict({"fieldname": "cost_center", "document_type": "Cost Center"}))

	return dimension_filters, {}


def create_accounting_dimensions_for_doctype(doctype):
	return


def make_dimension_in_accounting_doctypes(doc, doclist=None):
	return


def get_dimension_fieldname(dim_doctype: str) -> str:
	"""Return the `GL Entry` fieldname for a given dimension."""
	if dim_doctype == "Cost Center":
		return frappe.scrub(dim_doctype)
