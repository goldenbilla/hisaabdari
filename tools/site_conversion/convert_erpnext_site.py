"""Convert a restored ERPNext version-16 site so that HisaabDari can take it over.

Run from the bench folder, BEFORE `bench migrate`, against a site whose database was restored
from an ERPNext backup:

    ./env/bin/python apps/hisaabdari/tools/site_conversion/convert_erpnext_site.py <site> [--dry-run]

Options:
    --dry-run             show what would change and save nothing
    --keep-integrations   leave webhooks and email accounts switched on (use this for the real
                          move; leave it out for a rehearsal copy, so the copy cannot send anything)

It works on the database directly, because Frappe cannot load a site that lists an app
(erpnext) the bench does not have. Nothing is dropped: tables and columns of removed features
stay in the database, only the records that describe them to Frappe are removed.

See README.md in this folder for the whole procedure.
"""
import glob, json, os, sys
import MySQLdb

site = sys.argv[1]
dry = "--dry-run" in sys.argv
OLD, NEW = "erpnext", "hisaabdari"
APP_DIR = f"apps/{NEW}/{NEW}"

cfg = json.load(open(f"sites/{site}/site_config.json"))
common = json.load(open("sites/common_site_config.json"))
db = MySQLdb.connect(host=common.get("db_host", "127.0.0.1"), user=cfg.get("db_user") or cfg["db_name"],
	passwd=cfg["db_password"], db=cfg["db_name"], charset="utf8mb4")
cur = db.cursor()

def q(sql, args=None):
	cur.execute(sql, args); return cur.fetchall()
def run(sql, args=None):
	cur.execute(sql, args); return cur.rowcount
def has_table(doctype):
	return bool(q("show tables like %s", ("tab" + doctype,)))
def has_column(doctype, column):
	return bool(q(f"show columns from `tab{doctype}` like %s", (column,)))
def in_list(values):
	return ", ".join(["%s"] * len(values))
CHILD_TABLES = [r[0] for r in q(
	"select table_name from information_schema.columns where table_schema=database() and column_name='parenttype'")]

def delete_docs(doctype, where, args=None):
	"""Delete records of `doctype` matching `where`, with their rows in every child table."""
	if not has_table(doctype):
		return 0
	names = [r[0] for r in q(f"select name from `tab{doctype}` where {where}", args)]
	for start in range(0, len(names), 400):
		chunk = names[start:start + 400]
		marks = in_list(chunk)
		for table in CHILD_TABLES:
			run(f"delete from `{table}` where parenttype=%s and parent in ({marks})", [doctype] + chunk)
		run(f"delete from `tab{doctype}` where name in ({marks})", chunk)
	return len(names)

log = []
def note(text, count=None):
	log.append(f"{text}: {count}" if count is not None else text); print(log[-1])

# What HisaabDari ships ---------------------------------------------------------------------
new_modules = [m.strip() for m in open(f"{APP_DIR}/modules.txt") if m.strip()]
shipped_doctypes = set()
for path in glob.glob(f"{APP_DIR}/*/doctype/*/*.json"):
	try:
		d = json.load(open(path))
	except Exception:
		continue
	if isinstance(d, dict) and d.get("doctype") == "DocType":
		shipped_doctypes.add(d["name"])
note(f"HisaabDari ships {len(new_modules)} modules and {len(shipped_doctypes)} doctypes")

old_modules = [r[0] for r in q("select name from `tabModule Def` where app_name=%s", (OLD,))]
if not old_modules:
	already = q("select count(*) from `tabModule Def` where app_name=%s", (NEW,))[0][0]
	sys.exit(f"No module belongs to '{OLD}' on this site ({already} belong to '{NEW}'). Nothing to convert.")
kept_modules = [m for m in old_modules if m in new_modules]
gone_modules = [m for m in old_modules if m not in new_modules]
note(f"ERPNext modules kept: {', '.join(sorted(kept_modules))}")
note(f"ERPNext modules removed: {', '.join(sorted(gone_modules))}")

# 1. The list of installed apps --------------------------------------------------------------
for name, value in q("select name, defvalue from `tabDefaultValue` where defkey='installed_apps'"):
	apps = [NEW if a == OLD else a for a in json.loads(value)]
	run("update `tabDefaultValue` set defvalue=%s where name=%s", (json.dumps(apps), name))
	note(f"installed apps are now {apps}")
if has_table("Installed Application"):
	note("installed application record renamed", run("update `tabInstalled Application` set app_name=%s where app_name=%s", (NEW, OLD)))

# 2. Doctypes HisaabDari does not have ----------------------------------------------------------
gone_doctypes = [r[0] for r in q(
	f"select name from `tabDocType` where module in ({in_list(old_modules)}) and ifnull(custom,0)=0", old_modules)
	if r[0] not in shipped_doctypes]
note("doctype definitions to remove (their tables and data stay)", len(gone_doctypes))
if gone_doctypes:
	marks = in_list(gone_doctypes)
	delete_docs("DocType", f"name in ({marks})", gone_doctypes)
	# Customisations and saved settings that hang off those doctypes
	for table, column in (("Custom Field", "dt"), ("Property Setter", "doc_type"), ("Custom DocPerm", "parent"),
		("Client Script", "dt"), ("Print Format", "doc_type"), ("Report", "ref_doctype"), ("Notification", "document_type"),
		("Workflow", "document_type"), ("Number Card", "document_type"), ("Dashboard Chart", "document_type"),
		("Webhook", "webhook_doctype"), ("Auto Repeat", "reference_doctype"), ("Web Form", "doc_type")):
		if has_table(table) and has_column(table, column):
			n = delete_docs(table, f"`{column}` in ({marks})", gone_doctypes)
			if n: note(f"  {table} records for removed doctypes deleted", n)

# 3. Standard records of ERPNext's modules: HisaabDari's own files recreate the ones it ships ---
marks = in_list(old_modules)
for table, where in (
	("Report", "is_standard='Yes'"), ("Print Format", "standard='Yes'"), ("Dashboard Chart", "is_standard=1"),
	("Number Card", "is_standard=1"), ("Dashboard", "is_standard=1"), ("Module Onboarding", "1=1"),
	("Form Tour", "is_standard=1"), ("Web Form", "is_standard=1"), ("Notification", "is_standard=1"),
	("Workspace", "ifnull(for_user,'')=''"),
):
	if has_table(table) and has_column(table, "module"):
		n = delete_docs(table, f"module in ({marks}) and {where}", old_modules)
		note(f"standard {table} records cleared for re-creation", n)
# Print formats and reports that ERPNext shipped inside modules which no longer exist (for example
# the regional "IRS 1099 Form"), whatever their "standard" flag says: nothing can open them any more.
if gone_modules:
	for table in ("Print Format", "Report"):
		n = delete_docs(table, f"module in ({in_list(gone_modules)})", gone_modules)
		if n: note(f"{table} records left in removed modules deleted", n)
for table in ("Workspace Sidebar", "Desktop Icon", "Dock", "Sidebar"):
	if has_table(table) and has_column(table, "app"):
		note(f"{table} records of ERPNext cleared", delete_docs(table, "app=%s", (OLD,)))
if has_table("Onboarding Step"):
	run("delete from `tabOnboarding Step` where name not in (select step from `tabOnboarding Step Map`)")

# Field orders saved with "Customize Form" on the old site would override HisaabDari's simplified
# layouts (and push its new fields to the bottom of the form). Drop them for the doctypes
# HisaabDari ships; doctypes of other apps keep theirs. Custom fields are positioned separately,
# by their own "insert after" setting, so they are not affected.
shipped = sorted(shipped_doctypes)
note("saved field orders dropped so HisaabDari's layouts apply", delete_docs(
	"Property Setter", f"property='field_order' and doc_type in ({in_list(shipped)})", shipped))

# 4. Modules -------------------------------------------------------------------------------------
if kept_modules:
	note("modules handed to HisaabDari", run(
		f"update `tabModule Def` set app_name=%s where name in ({in_list(kept_modules)})", [NEW] + kept_modules))
if gone_modules:
	marks = in_list(gone_modules)
	left = q(f"select count(*) from `tabDocType` where module in ({marks})", gone_modules)[0][0]
	if left:
		note(f"  {left} custom doctypes still sit in removed modules; those modules are kept and handed to HisaabDari")
		run(f"update `tabModule Def` set app_name=%s where name in ({marks})", [NEW] + gone_modules)
	else:
		note("removed modules deleted", run(f"delete from `tabModule Def` where name in ({marks})", gone_modules))
		if has_table("Block Module"):
			run(f"delete from `tabBlock Module` where module in ({marks})", gone_modules)

# 5. Patch history: the same patches, under the new package name ----------------------------------
note("patch log entries renamed", run(
	"update `tabPatch Log` set patch=replace(patch, %s, %s) where patch like %s", (OLD + ".", NEW + ".", "%" + OLD + ".%")))

# 6. Things that must not act on the outside world from a copy ---------------------------------------
if "--keep-integrations" not in sys.argv:
	if has_table("Webhook"):
		note("webhooks disabled", run("update `tabWebhook` set enabled=0 where enabled=1"))
	if has_table("Email Account"):
		note("email accounts: incoming and outgoing switched off", run(
			"update `tabEmail Account` set enable_incoming=0, enable_outgoing=0 where enable_incoming=1 or enable_outgoing=1"))

if dry:
	db.rollback(); print("\nDry run: nothing was saved.")
else:
	db.commit(); print("\nSaved. Next: bench --site %s migrate" % site)
