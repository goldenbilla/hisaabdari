# HisaabDari

Simple ERP for small and medium businesses: accounts, sales, purchases and stock, with short forms that do not need a qualified accountant.

HisaabDari is an app for the [Frappe Framework](https://frappeframework.com) (version 16). It cannot be installed on the same site as ERPNext.

## Status

Early development. Not ready for production use.

## Origin and licence

HisaabDari is derived from ERPNext (version 16.60.0, commit `886ab6a`), copyright Frappe Technologies Pvt. Ltd. and contributors, and is distributed under the GNU General Public License v3 (see `license.txt`).

HisaabDari is an independent project. It is not affiliated with, sponsored by or endorsed by Frappe Technologies. "ERPNext" and "Frappe" are trademarks of Frappe Technologies Pvt. Ltd.

## Compatibility with ERPNext custom apps

DocType names, field names, function names and module layout are kept identical to ERPNext for everything HisaabDari retains. An ERPNext custom app can usually be ported by replacing the Python and JavaScript package prefix `erpnext.` with `hisaabdari.` and removing anything that relied on a feature HisaabDari does not include.
