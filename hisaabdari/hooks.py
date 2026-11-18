"""HisaabDari hooks. Generated from ERPNext's hooks by dev/regen_hooks.py, then maintained by hand."""

app_name = 'hisaabdari'

app_title = 'HisaabDari'

app_publisher = 'HisaabDari contributors'

app_description = 'Simple ERP for small and medium businesses'

app_icon = 'fa fa-th'

app_color = '#e74c3c'

app_email = ''

app_license = 'GNU General Public License (v3)'

source_link = ''

app_logo_url = '/assets/hisaabdari/images/hisaabdari-logo.svg'

app_home = '/desk/home'

add_to_apps_screen = [{'name': 'hisaabdari',
  'logo': '/assets/hisaabdari/images/hisaabdari-logo.svg',
  'title': 'HisaabDari',
  'route': '/desk/home',
  'setup_wizard_text': "Let's give your business a home.",
  'has_permission': 'hisaabdari.check_app_permission',
  'sequence_id': 1}]

code_only_modules = {'Utilities': ['Setup']}

app_include_js = 'hisaabdari.bundle.js'

app_include_css = 'hisaabdari.bundle.css'

web_include_css = 'hisaabdari-web.bundle.css'

email_css = 'hisaabdari_email.bundle.css'

app_include_icons = ['/assets/hisaabdari/icons/module-icons.svg']

doctype_js = {'Address': 'public/js/address.js',
 'Customer': ['public/js/party_overview.js', 'public/js/customer_overview.js'],
 'Supplier': ['public/js/party_overview.js', 'public/js/supplier_overview.js'],
 'Event': 'public/js/event.js',
 'Newsletter': 'public/js/newsletter.js',
 'Contact': 'public/js/contact.js'}

page_js = {'print': 'public/js/print.js'}

extend_doctype_class = {'Address': 'hisaabdari.accounts.custom.address.ERPNextAddress'}

welcome_email = 'hisaabdari.setup.utils.welcome_email'

setup_wizard_requires = 'assets/hisaabdari/js/setup_wizard.js'

setup_wizard_stages = 'hisaabdari.setup.setup_wizard.setup_wizard.get_setup_stages'

after_install = 'hisaabdari.setup.install.after_install'

never_skip_patches = ['hisaabdari.patches.v16_0.update_serial_batch_entries']

boot_session = 'hisaabdari.startup.boot.boot_session'

notification_config = 'hisaabdari.startup.notifications.get_notification_config'

get_help_messages = 'hisaabdari.utilities.activation.get_help_messages'

filters_config = 'hisaabdari.startup.filters.get_filters_config'

treeviews = ['Account', 'Cost Center', 'Warehouse', 'Item Group', 'Customer Group', 'Supplier Group']

jinja = {'methods': ['hisaabdari.stock.serial_batch_bundle.get_serial_or_batch_nos']}

website_context = {'favicon': '/assets/hisaabdari/images/hisaabdari-favicon.svg',
 'splash_image': '/assets/hisaabdari/images/hisaabdari-logo.svg'}

permission_query_conditions = {'Item': 'hisaabdari.stock.doctype.company_restriction.company_restriction.get_permission_query_conditions',
 'Customer': 'hisaabdari.stock.doctype.company_restriction.company_restriction.get_permission_query_conditions',
 'Supplier': 'hisaabdari.stock.doctype.company_restriction.company_restriction.get_permission_query_conditions',
 '*': 'hisaabdari.stock.doctype.company_restriction.company_restriction.get_inherited_permission_query_conditions'}

has_permission = {'Item': 'hisaabdari.stock.doctype.company_restriction.company_restriction.has_permission',
 'Customer': 'hisaabdari.stock.doctype.company_restriction.company_restriction.has_permission',
 'Supplier': 'hisaabdari.stock.doctype.company_restriction.company_restriction.has_permission',
 '*': 'hisaabdari.stock.doctype.company_restriction.company_restriction.has_inherited_permission'}

sqlite_search = ['hisaabdari.stock.doctype.item.item_search.ItemSearch']

period_closing_doctypes = ['Sales Invoice',
 'Purchase Invoice',
 'Journal Entry',
 'Stock Entry',
 'Payment Entry',
 'Period Closing Voucher',
 'Delivery Note',
 'Purchase Receipt',
 'Stock Reconciliation']

doc_events = {'*': {'validate': ['hisaabdari.stock.doctype.company_restriction.company_restriction.validate_transaction_company']},
 ('Sales Invoice', 'Purchase Invoice', 'Journal Entry', 'Stock Entry', 'Payment Entry', 'Period Closing Voucher', 'Delivery Note', 'Purchase Receipt', 'Stock Reconciliation'): {'validate': 'hisaabdari.accounts.doctype.accounting_period.accounting_period.validate_accounting_period_on_doc_save'},
 'Item': {'on_update': 'hisaabdari.stock.doctype.item.item_search.reindex_item',
          'after_rename': 'hisaabdari.stock.doctype.item.item_search.reindex_renamed_item'},
 ('Item', 'Customer', 'Supplier'): {'validate': 'hisaabdari.stock.doctype.company_restriction.company_restriction.validate_allowed_companies'},
 'User': {'after_insert': 'frappe.contacts.doctype.contact.contact.update_contact'}}

naming_series_variables_list = ['FY', 'TFY', 'ABBR', 'MM', 'DD', 'YY', 'YYYY', 'JJJ', 'WW']

naming_series_variables = {'FY': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'TFY': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'ABBR': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'MM': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'DD': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'YY': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'YYYY': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'JJJ': 'hisaabdari.accounts.utils.parse_naming_series_variable',
 'WW': 'hisaabdari.accounts.utils.parse_naming_series_variable'}

auto_cancel_exempted_doctypes = ['Payment Entry']

scheduler_events = {'cron': {'0/15 * * * *': ['hisaabdari.stock.doctype.repost_item_valuation.repost_item_valuation.run_parallel_reposting'],
          '30 * * * *': ['hisaabdari.accounts.doctype.gl_entry.gl_entry.rename_gle_sle_docs'],
          '45 0 * * *': []},
 'hourly_long': [],
 'hourly_maintenance': ['hisaabdari.stock.doctype.repost_item_valuation.repost_item_valuation.repost_entries'],
 'daily': [],
 'daily_long': [],
 'daily_maintenance': ['hisaabdari.controllers.accounts_controller.update_invoice_status',
                       'hisaabdari.accounts.doctype.fiscal_year.fiscal_year.auto_create_fiscal_year',
                       'hisaabdari.stock.doctype.serial_no.serial_no.update_maintenance_status',
                       'hisaabdari.setup.doctype.company.company.cache_companies_monthly_sales_history',
                       'hisaabdari.selling.doctype.quotation.quotation.set_expired_status',
                       'hisaabdari.accounts.utils.auto_create_exchange_rate_revaluation_daily'],
 'weekly': ['hisaabdari.accounts.utils.auto_create_exchange_rate_revaluation_weekly'],
 'monthly_long': ['hisaabdari.accounts.utils.auto_create_exchange_rate_revaluation_monthly']}

email_brand_image = 'assets/hisaabdari/images/hisaabdari-logo.svg'

get_translated_dict = {('doctype', 'Global Defaults'): 'frappe.geo.country_info.get_translated_dict'}

get_site_info = 'hisaabdari.utilities.get_site_info'

communication_doctypes = ['Customer', 'Supplier']

advance_payment_receivable_doctypes = ['Sales Order']

advance_payment_payable_doctypes = ['Purchase Order']

invoice_doctypes = ['Sales Invoice', 'Purchase Invoice']

accounting_dimension_doctypes = ['GL Entry',
 'Payment Ledger Entry',
 'Sales Invoice',
 'Purchase Invoice',
 'Payment Entry',
 'Stock Entry',
 'Delivery Note',
 'Sales Invoice Item',
 'Purchase Invoice Item',
 'Purchase Order Item',
 'Sales Order Item',
 'Journal Entry Account',
 'Delivery Note Item',
 'Purchase Receipt Item',
 'Stock Entry Detail',
 'Payment Entry Deduction',
 'Sales Taxes and Charges',
 'Purchase Taxes and Charges',
 'Landed Cost Taxes and Charges',
 'Stock Reconciliation',
 'Opening Invoice Creation Tool',
 'Opening Invoice Creation Tool Item',
 'Purchase Order',
 'Purchase Receipt',
 'Sales Order',
 'Account Closing Balance',
 'Payment Reconciliation',
 'Payment Reconciliation Allocation',
 'Advance Taxes and Charges']

global_search_doctypes = {'Default': [{'doctype': 'Customer', 'index': 0},
             {'doctype': 'Supplier', 'index': 1},
             {'doctype': 'Item', 'index': 2},
             {'doctype': 'Sales Invoice', 'index': 3},
             {'doctype': 'Purchase Invoice', 'index': 4},
             {'doctype': 'Sales Order', 'index': 5},
             {'doctype': 'Purchase Order', 'index': 6},
             {'doctype': 'Quotation', 'index': 7},
             {'doctype': 'Delivery Note', 'index': 8},
             {'doctype': 'Purchase Receipt', 'index': 9},
             {'doctype': 'Payment Entry', 'index': 10},
             {'doctype': 'Journal Entry', 'index': 11},
             {'doctype': 'Stock Entry', 'index': 16},
             {'doctype': 'Serial No', 'index': 23},
             {'doctype': 'Batch', 'index': 24}]}

extend_bootinfo = ['hisaabdari.startup.boot.bootinfo']

default_log_clearing_doctypes = {'Repost Item Valuation': 60}

export_python_type_annotations = True

fields_for_group_similar_items = ['qty', 'amount']

ignore_translatable_strings_from = ['frappe']

repost_allowed_doctypes = ['Sales Invoice', 'Purchase Invoice', 'Journal Entry', 'Payment Entry', 'Purchase Receipt']

data_import_providers = {'Customer': 'hisaabdari.utilities.party_import_provider.PartyImportProvider',
 'Supplier': 'hisaabdari.utilities.party_import_provider.PartyImportProvider'}

calendars = ['Sales Order', 'ToDo']
