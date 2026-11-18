# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from hisaabdari.accounts.report.utils import validate_date_range
from hisaabdari.selling.report.sales_analytics.sales_analytics import Analytics


def execute(filters=None):
	validate_date_range(filters)

	return Analytics(filters).run()
