import frappe

from hisaabdari.setup.install import update_pegged_currencies


def execute():
	update_pegged_currencies()
