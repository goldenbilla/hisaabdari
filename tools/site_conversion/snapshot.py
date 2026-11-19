"""Key figures of a site, read straight from its database (works before and after conversion).

Run from the bench folder:

    ./env/bin/python apps/hisaabdari/tools/site_conversion/snapshot.py <site> <out.json>
"""
import json, sys
import MySQLdb

site, out = sys.argv[1], sys.argv[2]
cfg = json.load(open(f"sites/{site}/site_config.json"))
common = json.load(open("sites/common_site_config.json"))
db = MySQLdb.connect(host=common.get("db_host", "127.0.0.1"), user=cfg.get("db_user") or cfg["db_name"], passwd=cfg["db_password"], db=cfg["db_name"], charset="utf8mb4")
cur = db.cursor()

def q(sql, args=None):
	cur.execute(sql, args); return cur.fetchall()
def has(table):
	return bool(q("show tables like %s", (table,)))
def num(x):
	return round(float(x or 0), 2)

snap = {"counts": {}, "submitted": {}}
tables = [r[0] for r in q("show tables")]
for dt in ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "GL Entry", "Stock Ledger Entry", "Payment Ledger Entry",
	"Customer", "Supplier", "Item", "Address", "Contact", "File", "User", "Account", "Cost Center", "Warehouse", "Quotation", "Sales Order",
	"Purchase Order", "Delivery Note", "Purchase Receipt", "Stock Entry", "Bank Account", "Bank Transaction", "Mode of Payment", "Fiscal Year",
	"Period Closing Voucher", "Custom Field", "Property Setter", "Print Format", "Client Script", "Server Script", "Workspace", "Report"]:
	if has("tab" + dt):
		snap["counts"][dt] = q(f"select count(*) from `tab{dt}`")[0][0]
for dt in ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Delivery Note", "Sales Order", "Quotation"]:
	if has("tab" + dt):
		snap["submitted"][dt] = q(f"select count(*) from `tab{dt}` where docstatus=1")[0][0]

r = q("select sum(debit), sum(credit), count(*) from `tabGL Entry` where is_cancelled=0")[0]
snap["gl"] = {"debit": num(r[0]), "credit": num(r[1]), "rows": r[2]}
snap["gl_by_account"] = {a: num(b) for a, b in q("select account, sum(debit)-sum(credit) from `tabGL Entry` where is_cancelled=0 group by account")}
snap["gl_by_party"] = {f"{t}|{p}": num(b) for t, p, b in q("select party_type, party, sum(debit)-sum(credit) from `tabGL Entry` where is_cancelled=0 and ifnull(party,'')!='' group by party_type, party")}
snap["invoices"] = {}
for dt in ["Sales Invoice", "Purchase Invoice"]:
	r = q(f"select sum(base_grand_total), sum(outstanding_amount) from `tab{dt}` where docstatus=1")[0]
	snap["invoices"][dt] = {"grand_total": num(r[0]), "outstanding": num(r[1])}
r = q("select sum(paid_amount), sum(unallocated_amount) from `tabPayment Entry` where docstatus=1")[0]
snap["payments"] = {"paid": num(r[0]), "unallocated": num(r[1])}
if has("tabPayment Ledger Entry"):
	snap["payment_ledger"] = {t or "": num(a) for t, a in q("select account_type, sum(amount) from `tabPayment Ledger Entry` where delinked=0 group by account_type")}
if has("tabBin"):
	r = q("select sum(actual_qty), sum(stock_value) from `tabBin`")[0]
	snap["stock"] = {"qty": num(r[0]), "value": num(r[1])}
# Documents of the site's other apps (custom apps), so their data can be compared too.
snap["other_app_counts"] = {}
for (name,) in q("""select d.name from `tabDocType` d join `tabModule Def` m on m.name = d.module
	where m.app_name not in ('frappe', 'erpnext', 'hisaabdari') and d.istable=0 and d.issingle=0"""):
	if has("tab" + name):
		snap["other_app_counts"][name] = q(f"select count(*) from `tab{name}`")[0][0]
snap["installed_apps"] = q("select defvalue from `tabDefaultValue` where defkey='installed_apps' and parent='__global'")
snap["installed_applications"] = [list(x) for x in q("select app_name, app_version from `tabInstalled Application`")] if has("tabInstalled Application") else None
snap["module_apps"] = {a or "": c for a, c in q("select app_name, count(*) from `tabModule Def` group by app_name")}
snap["doctypes"] = q("select count(*) from `tabDocType`")[0][0]
snap["patch_log"] = {"total": q("select count(*) from `tabPatch Log`")[0][0], "erpnext": q("select count(*) from `tabPatch Log` where patch like 'erpnext.%%'")[0][0],
	"hisaabdari": q("select count(*) from `tabPatch Log` where patch like 'hisaabdari.%%'")[0][0]}
snap["tables"] = len(tables)
json.dump(snap, open(out, "w"), indent=1, default=str, sort_keys=True)
brief = {k: v for k, v in snap.items() if k not in ("gl_by_account", "gl_by_party")}
print(json.dumps(brief, indent=1, default=str))
print("accounts with balance:", len(snap["gl_by_account"]), "| parties with balance:", len(snap["gl_by_party"]))
