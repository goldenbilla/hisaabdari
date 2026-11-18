# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate
from frappe.utils.data import now_datetime
from frappe.utils.nestedset import get_root_of

from hisaabdari import get_default_company


def get_stored_exchange_rate(from_currency, to_currency, transaction_date, args=None, checkpoint_date=None):
	"""Return the latest rate from Currency Exchange records, or None if there is none.

	On the same date, a record meant only for the requested side (buying or selling)
	wins over a record meant for both.
	"""
	filters = [
		["date", "<=", getdate(transaction_date)],
		["from_currency", "=", from_currency],
		["to_currency", "=", to_currency],
	]
	order_by = "date desc"

	if args == "for_buying":
		filters.append(["for_buying", "=", 1])
		order_by += ", for_selling asc"
	elif args == "for_selling":
		filters.append(["for_selling", "=", 1])
		order_by += ", for_buying asc"

	if checkpoint_date:
		filters.append(["date", ">", getdate(checkpoint_date)])

	entries = frappe.get_all(
		"Currency Exchange",
		fields=["exchange_rate"],
		filters=filters,
		order_by=order_by + ", name desc",
		limit=1,
	)
	if entries:
		return flt(entries[0].exchange_rate)


@frappe.whitelist()
def get_exchange_rate(from_currency, to_currency, transaction_date=None, args=None):
	if not (from_currency and to_currency):
		# manqala 19/09/2016: Should this be an empty return or should it throw and exception?
		return
	for currency in (from_currency, to_currency):
		if not isinstance(currency, str) or not frappe.db.exists("Currency", currency):
			frappe.throw(_("Invalid currency: {0}").format(currency))

	if from_currency == to_currency:
		return 1

	transaction_date = getdate(transaction_date)
	if not transaction_date:
		frappe.throw(_("Invalid transaction date"))
	transaction_date = transaction_date.isoformat()

	currency_settings = frappe.get_cached_doc("Accounts Settings")
	allow_stale_rates = currency_settings.get("allow_stale")

	checkpoint_date = None
	if not allow_stale_rates:
		checkpoint_date = add_days(transaction_date, -currency_settings.get("stale_days"))

	rate = get_stored_exchange_rate(from_currency, to_currency, transaction_date, args, checkpoint_date)
	if rate is not None:
		return rate

	# no direct record: use the inverse of a record for the opposite direction
	reverse_args = {"for_buying": "for_selling", "for_selling": "for_buying"}.get(args, args)
	reverse_rate = get_stored_exchange_rate(
		to_currency, from_currency, transaction_date, reverse_args, checkpoint_date
	)
	if reverse_rate:
		return 1 / reverse_rate

	frappe.msgprint(
		_(
			"Unable to find exchange rate for {0} to {1} for key date {2}. Please create a Currency Exchange record manually"
		).format(from_currency, to_currency, transaction_date)
	)
	return 0.0


def enable_all_roles_and_domains():
	"""enable all roles and domain for testing"""
	_enable_all_roles_for_admin()


def _enable_all_roles_for_admin():
	from frappe.desk.page.setup_wizard.setup_wizard import add_all_roles_to

	all_roles = set(frappe.get_all("Role", pluck="name"))
	admin_roles = set(
		frappe.db.get_values("Has Role", {"parent": "Administrator"}, fieldname="role", pluck="role")
	)

	if all_roles.difference(admin_roles):
		add_all_roles_to("Administrator")


def set_defaults_for_tests():
	defaults = {
		"customer_group": get_root_of("Customer Group"),
	}
	frappe.db.set_single_value("Selling Settings", defaults)
	for key, value in defaults.items():
		frappe.db.set_default(key, value)
	frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)

	frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)


def insert_record(records):
	from frappe.desk.page.setup_wizard.setup_wizard import make_records

	make_records(records)


def welcome_email():
	site_name = get_default_company() or "HisaabDari"
	title = _("Welcome to {0}").format(site_name)
	return title


def identity(x, *args, **kwargs):
	"""Used for redefining the translation function to return the string as is.

	We want to create english records but still mark the strings as translatable.
	E.g. when the respective DocTypes have 'Translate Link Fields' enabled or
	we're creating custom fields.

	Use like this: `from hisaabdari.setup.utils import identity as _`
	"""
	return x


def set_root_as_default_parent(doc):
	"""Default an empty tree parent to the root, unless the doc is the root."""
	if doc.get(doc.nsm_parent_field):
		return

	root = get_root_of(doc.doctype)
	if root != doc.name:
		doc.set(doc.nsm_parent_field, root)
