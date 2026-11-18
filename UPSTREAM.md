# Upstream baseline

HisaabDari was imported from ERPNext with `dev/import_from_erpnext.py`.

| | |
|---|---|
| Repository | https://github.com/frappe/erpnext |
| Branch | version-16 |
| Version | 16.60.0 |
| Commit | 886ab6a (2026-11-17) |
| Frappe | version-16, commit 2df0425 (2026-11-18) |

## Intentional differences from upstream

HisaabDari is ERPNext with the package renamed and unused features removed. The complete
record of intentional differences is the diff between:

- the baseline commit above, passed through `dev/import_from_erpnext.py` (rename only), and
- this repository.

Kinds of difference, in the order they were applied:

1. **Rename.** Package token `erpnext` renamed to `hisaabdari` throughout (Python imports,
   JavaScript namespace, asset paths, file names).
2. **Whole modules removed:** manufacturing, crm, projects, quality_management, support,
   subcontracting, assets, maintenance, telephony, regional, edi, bulk_transaction, portal,
   communication, erpnext_integrations, shopping_cart (`dev/prune.py`).
3. **DocTypes and reports removed** inside the kept modules, and fields that linked to them
   stripped from the kept doctypes (`dev/prune.py`; the full list is `dev/pruned.json`).
4. **Ledger doctypes** (GL Entry, Payment Ledger Entry, Stock Ledger Entry, Account Closing
   Balance): `project` and `finance_book` are kept as hidden plain-text fields so the posting
   code is unchanged.
5. **Stand-in modules** at upstream's import paths that answer "none":
   `accounts/doctype/accounting_dimension`, `accounts/doctype/accounting_dimension_filter`,
   `stock/doctype/inventory_dimension`.
6. **Code references removed** to everything in 2 and 3, following `dev/TRIM_BRIEF.md`:
   imports, branches, buttons, fields and functions that existed only for a removed feature.
   Posting and valuation arithmetic was not changed.
7. **hooks.py** regenerated without entries for removed code (`dev/regen_hooks.py`).
8. **Branding:** ERPNext logos replaced, product title set to HisaabDari, ERPNext
   documentation links removed from forms.
9. **Exchange rates** come only from Currency Exchange records (the external rate fetch
   needed the removed Currency Exchange Settings).

10. **Migration patches:** only version-16 patches that touch kept doctypes remain in
    `patches.txt`. Older patches and patches for removed features were deleted. When an
    existing ERPNext site is converted, its Patch Log entries must be renamed from
    `erpnext.patches.` to `hisaabdari.patches.`, and any upstream version-16 patch the site
    has not yet run must be reviewed by hand.

To pick up an upstream fix: diff the baseline commit against the newer upstream commit for
the files that still exist here, and port the relevant hunks by hand.
