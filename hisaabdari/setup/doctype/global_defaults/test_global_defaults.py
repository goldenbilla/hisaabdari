# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.www.printview import is_visible

from hisaabdari.tests.utils import ERPNextTestSuite


class TestGlobalDefaults(ERPNextTestSuite):
	def test_save_without_changes_keeps_site_cache(self):
		frappe.get_doc("Global Defaults").save()
		frappe.cache.set_value("global_defaults_probe", 1)

		frappe.get_doc("Global Defaults").save()
		self.assertEqual(frappe.cache.get_value("global_defaults_probe"), 1)

	def test_disable_in_words_preserves_payment_print_defaults(self):
		for doctype in ("Payment Entry",):
			make_property_setter(doctype, "in_words", "print_hide", 1, "Check")

		with self.change_settings("Global Defaults", disable_in_words=0):
			defaults = frappe.get_doc("Global Defaults")
			for disabled in (0, 1, 0):
				with self.subTest(disabled=disabled):
					defaults.disable_in_words = disabled
					defaults.save()
					for doctype in ("Payment Entry",):
						field = frappe.get_meta(doctype).get_field("in_words")
						self.assertEqual(field.hidden, disabled)
						self.assertEqual(field.print_hide, 1)
						doc = frappe.new_doc(doctype)
						doc.in_words = "INR One Hundred only."
						self.assertFalse(is_visible(field, doc))

					field = frappe.get_meta("Sales Invoice").get_field("in_words")
					self.assertEqual(field.hidden, disabled)
					self.assertEqual(field.print_hide, disabled)

			defaults.hide_currency_symbol = "No" if defaults.hide_currency_symbol == "Yes" else "Yes"
			defaults.save()
			for doctype in ("Payment Entry",):
				self.assertEqual(frappe.get_meta(doctype).get_field("in_words").print_hide, 1)

	def test_disable_in_words_preserves_custom_print_visibility(self):
		for doctype in ("Payment Entry",):
			make_property_setter(doctype, "in_words", "print_hide", 0, "Check", is_system_generated=False)

		for disabled in (1, 0):
			with self.change_settings("Global Defaults", disable_in_words=disabled):
				for doctype in ("Payment Entry",):
					field = frappe.get_meta(doctype).get_field("in_words")
					self.assertEqual(field.hidden, disabled)
					self.assertEqual(field.print_hide, 0)
