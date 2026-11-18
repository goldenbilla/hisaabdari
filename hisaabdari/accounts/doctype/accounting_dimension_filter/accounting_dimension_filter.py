# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""HisaabDari has no Accounting Dimension Filters. Function names match ERPNext's module."""

import frappe


def get_dimension_filter_map():
	return {}


def get_dimension_label(meta, fieldname):
	"""Translated label of the dimension field, or the unscrubbed fieldname when the field no longer exists."""
	if meta.has_field(fieldname):
		return meta.get_translated_label(fieldname)
	return frappe.unscrub(fieldname)
