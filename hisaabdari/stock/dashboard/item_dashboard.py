import frappe
from frappe import _
from frappe.desk.reportview import build_match_conditions
from frappe.utils import cint, escape_html, flt

QTY_FIELDS = (
	"projected_qty",
	"reserved_qty",
	"ordered_qty",
	"actual_qty",
)


@frappe.whitelist()
def make_stock_entry(
	item_code: str,
	source_warehouse: str | None = None,
	target_warehouse: str | None = None,
	stock_entry_type: str | None = None,
	qty: float | None = None,
	rate: float | None = None,
):
	"""Return an unsaved Stock Entry for the item, with company taken from the warehouse"""
	stock_entry = frappe.new_doc("Stock Entry")
	if warehouse := source_warehouse or target_warehouse:
		stock_entry.company = frappe.get_cached_value("Warehouse", warehouse, "company")

	stock_entry.stock_entry_type = stock_entry_type or (
		"Material Transfer" if source_warehouse else "Material Receipt"
	)
	stock_entry.purpose = frappe.get_cached_value("Stock Entry Type", stock_entry.stock_entry_type, "purpose")
	stock_entry.from_warehouse = source_warehouse
	stock_entry.to_warehouse = target_warehouse

	stock_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
	stock_entry.append(
		"items",
		{
			"item_code": item_code,
			"s_warehouse": source_warehouse,
			"t_warehouse": target_warehouse,
			"qty": flt(qty),
			"transfer_qty": flt(qty),
			"basic_rate": flt(rate),
			"uom": stock_uom,
			"stock_uom": stock_uom,
			"conversion_factor": 1,
		},
	)

	# checked against the doc so user permissions on company, warehouses and item apply;
	# generic message so values of restricted records are not leaked
	if not frappe.has_permission("Stock Entry", "create", doc=stock_entry):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return stock_entry


@frappe.whitelist()
def get_data(
	item_code: str | None = None,
	warehouse: str | None = None,
	item_group: str | None = None,
	start: int = 0,
	sort_by: str = "actual_qty",
	sort_order: str = "desc",
):
	"""Return data to render the item dashboard"""
	if not frappe.has_permission("Bin", "read") or not frappe.has_permission("Warehouse", "read"):
		return []

	if sort_by not in QTY_FIELDS or sort_order not in ("asc", "desc"):
		frappe.throw(_("Invalid sort order"))

	filters = []
	if item_code:
		filters.append(["item_code", "=", item_code])
	if warehouse:
		filters.append(["warehouse", "descendants of (inclusive)", warehouse])
	if item_group:
		lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"])
		items = frappe.db.sql_list(
			"""
			select i.name from `tabItem` i
			where exists(select name from `tabItem Group`
				where name=i.item_group and lft >=%s and rgt<=%s)
		""",
			(lft, rgt),
		)
		filters.append(["item_code", "in", items])

	if build_match_conditions("Warehouse", user=frappe.session.user):
		filters.append(["warehouse", "in", frappe.get_list("Warehouse", pluck="name", limit_page_length=0)])

	items = frappe.get_list(
		"Bin",
		fields=[
			"item_code",
			"warehouse",
			"projected_qty",
			"reserved_qty",
			"actual_qty",
			"valuation_rate",
		],
		or_filters={field: ["!=", 0] for field in QTY_FIELDS},
		filters=filters,
		order_by=f"{sort_by} {sort_order}",
		limit_start=start,
		limit_page_length=21,
	)

	precision = cint(frappe.db.get_single_value("System Settings", "float_precision"))

	for item in items:
		item.update(
			{
				"item_code": escape_html(item.item_code),
				"item_name": escape_html(frappe.get_cached_value("Item", item.item_code, "item_name")),
				"stock_uom": escape_html(frappe.get_cached_value("Item", item.item_code, "stock_uom")),
				"warehouse": escape_html(item.warehouse),
				"disable_quick_entry": frappe.get_cached_value("Item", item.item_code, "has_batch_no")
				or frappe.get_cached_value("Item", item.item_code, "has_serial_no"),
				"projected_qty": flt(item.projected_qty, precision),
				"reserved_qty": flt(item.reserved_qty, precision),
				"actual_qty": flt(item.actual_qty, precision),
			}
		)

	return items
