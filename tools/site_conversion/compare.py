"""Compare two snapshots made by snapshot.py, before and after a conversion.

    ./env/bin/python apps/hisaabdari/tools/site_conversion/compare.py before.json after.json
"""
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
ok = True
def cmp(label, x, y):
	global ok
	if x == y: print(f"  same     {label}"); return
	ok = False; print(f"  DIFFERENT {label}")
	if isinstance(x, dict):
		keys = [k for k in sorted(set(x) | set(y)) if x.get(k) != y.get(k)]
		for k in keys[:15]: print(f"      {k}: {x.get(k)} -> {y.get(k)}")
		if len(keys) > 15: print(f"      ... and {len(keys) - 15} more")
	else: print(f"      {x} -> {y}")
for key in ("gl", "gl_by_account", "gl_by_party", "invoices", "payments", "payment_ledger", "stock", "submitted"):
	cmp(key, a.get(key), b.get(key))
# Documents of other apps: only doctypes that still exist are compared. A doctype an app has since
# removed is listed separately; its rows are still in the database.
kept = {k: v for k, v in a["other_app_counts"].items() if k in b["other_app_counts"]}
cmp("documents of other apps", kept, b["other_app_counts"])
gone = {k: v for k, v in a["other_app_counts"].items() if k not in b["other_app_counts"]}
if gone: print("  doctypes other apps no longer have (rows left in the database):", gone)
print("  counts that changed:")
for k in sorted(a["counts"]):
	if a["counts"][k] != b["counts"].get(k): print(f"      {k}: {a['counts'][k]} -> {b['counts'].get(k)}")
print("  doctypes:", a["doctypes"], "->", b["doctypes"], "| tables:", a["tables"], "->", b["tables"])
print("  modules by app:", b["module_apps"], "| patch log:", b["patch_log"])
print("\nFINANCIAL FIGURES", "UNCHANGED" if ok else "CHANGED - LOOK ABOVE")
sys.exit(0 if ok else 1)
