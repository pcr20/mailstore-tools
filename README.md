# mailstore-tools

Tools and notes for reading a **MailStore Home** archive directly, outside the
MailStore application, by driving MailStore's own bundled Firebird 4 engine and
`DBCrypt` plugin.

This came out of inspecting Paul's two local archives:

| Archive | Path | State |
|---|---|---|
| Main | `C:\Users\pcr20\OneDrive\Apps\Mailstore` | active, ~714k messages |
| Lup  | `C:\Users\pcr20\OneDrive\Apps\MailstoreLup` | dormant copy from the old PC |

## What works

**Full write-up: [FINDINGS.md](FINDINGS.md)** — the complete reverse-engineering, crypto scheme, and results.


The archive's `.fdb` databases are Firebird 4 databases encrypted at the page
level by MailStore's `DBCrypt` plugin. A stock Firebird client cannot open them,
and there is no documented on-disk format. But the archive is self-contained:
MailStore ships the whole engine (`fbclient.dll`, `engine13.dll`, `DBCrypt.dll`)
and the `.key` file sits beside the database. So the supported engine can open
its own database — we just drive it ourselves instead of through the GUI.

`tools/dump_schema.py` loads MailStore's `fbclient.dll` via the pure-Python
`firebird-driver`, attaches to a **copy** of each database (with its `.key`
beside it), and dumps the schema and row counts. Login is plain
`SYSDBA` / `masterkey`; the plugin decrypts pages on attach. No key is extracted
and nothing is cracked — the vendor engine does the decryption as designed.

## The portability catch (important)

`DBCrypt` unwraps part of the key set with Windows **DPAPI**, which is bound to
the **Windows user + machine that created the archive**:

- **Main archive** → created on `DESKTOP-4461DDH` as user `PCR20` → opens fine
  on that machine/account.
- **Lup archive** → created on `PC-PAUL` as user `PAULROBERTS` → attach fails
  with `DbCrypt: UnprotectData ... NTE_BAD_KEY_STATE`. It can only be opened on
  the original machine/account, or inside MailStore Home using its **recovery
  passphrase**.

See `captures/attach_log_lup_failed.txt` for the failure and
`captures/schema_main_archive.txt` for the successful dump.

## Layout

```
tools/
  dump_schema.py          schema dumper (firebird-driver -> MailStore fbclient)
  run_mainarchive.bat     runner for the main archive (Master + FileGroup)
  run_lup.bat             runner for the Lup archive (fails: DPAPI binding)
  requirements.txt        python deps (pure-python; bundle offline if needed)
docs/
  mailstore-format.md     on-disk format, key file, schema, pointer mapping
captures/
  schema_main_archive.txt successful schema + row-count dump
  attach_log_lup_failed.txt  the DPAPI failure on the Lup archive
```

## Running

Needs Windows (the plugin is a 32-bit Windows DLL using the Windows crypto API)
and Python 3.11+. Install deps, or bundle them offline into a `pylib/` folder
next to `dump_schema.py` (the batch files extract a `pylib.zip` if present).

```
py -3 dump_schema.py <path-to>\fbclient.dll <db1.fdb> [<db2.fdb> ...]
```

The database copy must have its matching `.key` in the same folder, and the
`fbclient.dll` you pass must be MailStore's (so its `plugins\engine13.dll` and
`plugins\DBCrypt.dll` load). The batch files do the copy-to-temp and wiring.

## Getting actual message bodies

The schema gets you a searchable **header-level** index immediately
(`MAIL.DISPLAYSUBJECT` / `DISPLAYFROMORTO` / `DATE` / `FOLDERID`). The message
**bodies** live in the separately-encoded `*.dat` containers that
`MIMEENTITY` points into (see the format doc). Reversing that container encoding
is not done here; for bodies, MailStore Home's **EML export** remains the clean
route.
