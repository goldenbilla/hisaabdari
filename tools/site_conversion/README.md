# Moving an ERPNext site to HisaabDari

These scripts take a site that ran ERPNext version-16 and hand it to HisaabDari. The ledgers are not
touched: the conversion only changes the records that tell Frappe which app owns what.

| Script | What it does |
|---|---|
| `snapshot.py` | Writes a site's key figures to a file: ledger totals, the balance of every account and party, invoice and payment totals, document counts. |
| `convert_erpnext_site.py` | Hands the site from ERPNext to HisaabDari. Run it after restoring and before `bench migrate`. |
| `compare.py` | Compares two snapshots and says whether the financial figures are unchanged. |

## What you need

- A bench with Frappe version-16 and HisaabDari, and every other app the old site had installed
  (ported to HisaabDari where it imported from `erpnext`).
- A backup of the old site made with `bench --site <old-site> backup --with-files`: the database,
  the two file archives and the site config.
- The old site should be on ERPNext version-16. An older site must be upgraded to version-16 with
  ERPNext first.

## Always rehearse first

Do the whole procedure on a copy before doing it for real. A rehearsal takes a few minutes and can be
repeated as often as needed, because every run starts again from the backup.

On a rehearsal bench, keep the copy from acting on the outside world:

```bash
bench set-config -gp pause_scheduler 1
bench set-config -gp mute_emails 1
```

## Procedure

Run everything from the bench folder. `SITE` is the site name on the new bench and `B` is the path
prefix of the backup files (everything before `-database.sql.gz`).

1. Create the site and restore the backup into it.

   ```bash
   bench new-site $SITE
   bench --site $SITE restore $B-database.sql.gz \
       --with-public-files $B-files.tar --with-private-files $B-private-files.tar --force
   ```

   `--force` is needed because the backup lists an app, `erpnext`, that this bench does not have.

2. Copy `encryption_key` from the backup's `site_config_backup.json` into
   `sites/$SITE/site_config.json`. Without it, passwords stored inside the site (email accounts,
   API secrets) cannot be read.

3. Record the figures before changing anything.

   ```bash
   ./env/bin/python apps/hisaabdari/tools/site_conversion/snapshot.py $SITE /tmp/before.json
   ```

4. Convert. Look at what it would do first, then run it.

   ```bash
   ./env/bin/python apps/hisaabdari/tools/site_conversion/convert_erpnext_site.py $SITE --dry-run
   ./env/bin/python apps/hisaabdari/tools/site_conversion/convert_erpnext_site.py $SITE
   ```

   For the real move add `--keep-integrations`, so webhooks and email accounts stay switched on. For
   a rehearsal leave it out.

5. Migrate.

   ```bash
   bench --site $SITE migrate
   ```

6. Record the figures again and compare.

   ```bash
   ./env/bin/python apps/hisaabdari/tools/site_conversion/snapshot.py $SITE /tmp/after.json
   ./env/bin/python apps/hisaabdari/tools/site_conversion/compare.py /tmp/before.json /tmp/after.json
   ```

   The last line must read `FINANCIAL FIGURES UNCHANGED`. If it does not, stop and find out why
   before anyone uses the site.

7. Clear the cache and restart the bench processes.

## What the conversion changes

- The list of installed apps: `erpnext` becomes `hisaabdari`.
- The modules HisaabDari kept (Accounts, Buying, Selling, Setup, Stock, Utilities) are handed to it.
  The other ERPNext modules are deleted.
- The definitions of doctypes HisaabDari does not have are removed, with the custom fields, property
  setters, print formats, reports and similar records that belong to them. **Their database tables
  and the data in them are left alone.** They are simply no longer shown.
- ERPNext's standard reports, print formats, workspaces, charts and number cards are cleared, so
  that `bench migrate` recreates the ones HisaabDari ships.
- Field orders saved with "Customize Form" are dropped for the doctypes HisaabDari ships, so that
  its simplified form layouts apply. Custom fields are not affected: each is positioned by its own
  "insert after" setting.
- Patch history is renamed from `erpnext.patches.` to `hisaabdari.patches.`, so patches that already
  ran are not run again.
- Unless `--keep-integrations` is given, webhooks and email accounts are switched off.

## What it does not do

- It does not upgrade ERPNext. The old site must already be on version-16.
- It does not port other apps. An app that imports from `erpnext` must be changed to import from
  `hisaabdari` before it is installed on the new bench.
- It does not carry over anything from features HisaabDari removed. That data stays in the database
  and can be read with SQL, but no screen shows it.

## After the real move

- Switch the scheduler back on if it was paused: `bench --site $SITE scheduler enable`.
- Check the email accounts and any webhooks.
- Keep the old server, unused, until you are sure. Nothing in this procedure changes it, so going
  back is a matter of pointing the domain at it again.
