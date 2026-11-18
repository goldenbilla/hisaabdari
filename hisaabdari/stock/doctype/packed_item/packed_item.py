# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# For license information, please see license.txt


import frappe
import frappe.defaults
from frappe.model.document import Document
from frappe.utils import flt

from hisaabdari.stock.get_item_details import get_conversion_factor


class PackedItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_batch_qty: DF.Float
		actual_qty: DF.Float
		batch_no: DF.Link | None
		conversion_factor: DF.Float
		delivered_by_supplier: DF.Check
		description: DF.TextEditor | None
		incoming_rate: DF.Currency
		item_code: DF.Link | None
		item_name: DF.Data | None
		ordered_qty: DF.Float
		packed_qty: DF.Float
		page_break: DF.Check
		parent: DF.Data
		parent_detail_docname: DF.Data | None
		parent_item: DF.Link | None
		parentfield: DF.Data
		parenttype: DF.Data
		picked_qty: DF.Float
		prevdoc_doctype: DF.Data | None
		projected_qty: DF.Float
		qty: DF.Float
		rate: DF.Currency
		received_qty: DF.Float
		requested_qty: DF.Float
		reserve_stock: DF.Check
		return_against_packed_item: DF.Data | None
		sales_order_packed_item: DF.Data | None
		serial_and_batch_bundle: DF.Link | None
		serial_no: DF.Text | None
		target_warehouse: DF.Link | None
		uom: DF.Link | None
		use_serial_batch_fields: DF.Check
		warehouse: DF.Link | None
	# end: auto-generated types

	def set_actual_and_projected_qty(self):
		"Set actual and projected qty based on warehouse and item_code"
		_bin = frappe.db.get_value(
			"Bin",
			{"item_code": self.item_code, "warehouse": self.warehouse},
			["actual_qty", "projected_qty"],
			as_dict=True,
		)
		self.actual_qty = _bin.actual_qty if _bin else 0
		self.projected_qty = _bin.projected_qty if _bin else 0


def get_location_filters(row) -> dict:
	"""Filters that tell apart a component's packed rows of one bundle row, or their ledger entries."""
	if row.serial_and_batch_bundle:
		return {"serial_and_batch_bundle": row.serial_and_batch_bundle}
	return {"warehouse": row.warehouse}


def get_component_stock_qty_per_unit(packing_item, stock_uom, so_packed_item=None):
	"""Component stock qty per bundle stock unit; a Sales Order's packed row keeps the qty it was ordered with."""
	# component qty is in the bundle row's UOM; convert to stock qty
	qty_per_unit = flt(packing_item.qty) * get_component_conversion_factor(packing_item, stock_uom)
	return get_ordered_qty_per_unit(qty_per_unit, so_packed_item)


def get_ordered_qty_per_unit(qty_per_unit, so_packed_item=None):
	"""``qty_per_unit``, or the order's own ratio if the conversion changed after the order was packed."""
	# the order's ratio comes from its rounded packed qty, so use it only once the conversion has changed
	if so_packed_item and so_packed_item.qty_per_unit:
		ordered_qty = flt(
			qty_per_unit * flt(so_packed_item.order_stock_qty), frappe.get_precision("Packed Item", "qty")
		)
		if ordered_qty != flt(so_packed_item.qty):
			return so_packed_item.qty_per_unit

	return qty_per_unit


def get_component_conversion_factor(packing_item, stock_uom):
	uom = packing_item.get("uom")
	if not uom or uom == stock_uom:
		return 1.0
	return flt(get_conversion_factor(packing_item.item_code, uom).get("conversion_factor")) or 1.0


def get_order_packed_items(doc) -> dict:
	"""Packed rows of the rows this document is made from, by that row in idx order:
	the returned document's for a return, else the Sales Order's."""
	return get_packed_items_of_order_rows(
		{row for item in doc.get("items") if (row := get_order_row(doc, item))},
		doc.doctype if doc.get("is_return") else "Sales Order",
	)


def get_packed_item_link_field(doc):
	return "return_against_packed_item" if doc.get("is_return") else "sales_order_packed_item"


def get_order_row(doc, item_row):
	"""Row whose packed rows ``item_row`` keeps the qty of."""
	if not doc.get("is_return"):
		return item_row.get("so_detail")
	return item_row.get(
		"dn_detail" if doc.doctype == "Delivery Note" else frappe.scrub(doc.doctype) + "_item"
	)


def get_packed_items_of_order_rows(order_rows, doctype="Sales Order") -> dict:
	"""Packed rows of the given rows of ``doctype``, by row in idx order."""
	if not order_rows:
		return {}

	packed_item = frappe.qb.DocType("Packed Item")
	order_item = frappe.qb.DocType(f"{doctype} Item")
	rows = (
		frappe.qb.from_(packed_item)
		.join(order_item)
		.on(order_item.name == packed_item.parent_detail_docname)
		.select(
			packed_item.name,
			packed_item.parent_detail_docname,
			packed_item.parent_item,
			packed_item.item_code,
			packed_item.warehouse,
			packed_item.reserve_stock,
			packed_item.qty,
			packed_item.picked_qty,
			packed_item.sales_order_packed_item,
			order_item.stock_qty.as_("order_stock_qty"),
		)
		.where((packed_item.parenttype == doctype) & packed_item.parent_detail_docname.isin(list(order_rows)))
		.orderby(packed_item.idx)
		.run(as_dict=True)
	)

	order_packed_items = {}
	for row in rows:
		row.qty_per_unit = flt(row.qty) / flt(row.order_stock_qty) if flt(row.order_stock_qty) else 0
		order_packed_items.setdefault(row.parent_detail_docname, []).append(row)

	return order_packed_items


def pop_order_packed_item(so_packed_items, parent_item, item_code):
	"""Take the order's packed row of a component; a component repeated in the bundle takes the next one."""
	for idx, row in enumerate(so_packed_items):
		if row.parent_item == parent_item and row.item_code == item_code:
			return so_packed_items.pop(idx)


def get_component_order_rows(doc, parent_item, components, so_packed_items) -> list[tuple]:
	"""Each component of a bundle row with the order's packed row it packs.

	A return packs every delivered row of a component, e.g. one per warehouse it was delivered from."""
	if not doc.get("is_return"):
		return [
			(component, pop_order_packed_item(so_packed_items, parent_item, component.item_code))
			for component in components
		]

	# rows delivered from several warehouses share the Sales Order packed row of their occurrence
	delivered_rows = {}
	for row in so_packed_items:
		delivered_rows.setdefault(row.sales_order_packed_item or row.name, []).append(row)

	first_rows = [rows[0] for rows in delivered_rows.values()]
	component_rows = []
	for component in components:
		first_row = pop_order_packed_item(first_rows, parent_item, component.item_code)
		rows = delivered_rows[first_row.sales_order_packed_item or first_row.name] if first_row else [None]
		component_rows.extend((component, row) for row in rows)

	return component_rows


def get_order_packed_item_pairs(doc) -> list[tuple]:
	"""Pair each packed row of a document made from a Sales Order with the order's packed row it delivers."""
	order_packed_items = get_order_packed_items(doc)
	link_field = get_packed_item_link_field(doc)
	pairs = []
	for item in doc.get("items"):
		so_packed_items = list(order_packed_items.get(get_order_row(doc, item), []))
		so_packed_items_by_name = {row.name: row for row in so_packed_items}
		for packed_item in doc.get("packed_items"):
			if packed_item.parent_detail_docname != (item.name or item.idx):
				continue

			if so_packed_item := so_packed_items_by_name.get(
				packed_item.get(link_field)
			) or pop_order_packed_item(so_packed_items, packed_item.parent_item, packed_item.item_code):
				pairs.append((packed_item, so_packed_item))

	return pairs


def on_doctype_update():
	frappe.db.add_index("Packed Item", ["item_code", "warehouse"])
