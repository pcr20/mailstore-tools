# Building and searching the archive index

`tools/build_index.py` reads `MailStoreFileGroup.fdb` (via MailStore's own
Firebird engine + DBCrypt plugin, same as `dump_schema.py`) and writes a single
SQLite database with three tables plus an FTS5 index:

- `folder(folderid, name)`
- `mail(mailid, folderid, messageid, date, arcdate, flags, size, subject, fromorto)`
  and `mail_fts` (FTS5 over subject + fromorto)
- `part(...)` — one row per MIME part with the **container+entry pointers**
  (`content_*`, `plaintext_*`, `header_*`) into the `Data\<n>.dat` containers

This is the **header-level + file-level** index. It does NOT contain decoded
body text — `(container, entry)` tells you where each body lives, but decoding
the container bytes is a separate problem (use MailStore's EML export for bodies).

## Build

```
py -3 tools/build_index.py <MailStore...\fbclient.dll> \
      <copy-of>\MailStoreFileGroup.fdb  out\mailstore_index.db
```
(the `.fdb` copy must have its `.key` beside it). `run_index.bat` wires this up
for the main archive. On the reference archive this produced ~714k mail rows,
~2.28M parts, and a ~490 MB database.

## Search (no dependencies, stdlib sqlite3)

```
py -3 tools/search_index.py <db> stats
py -3 tools/search_index.py <db> folders 2000          # folders with >=2000 msgs
py -3 tools/search_index.py <db> fts "invoice"         # full-text subject+sender
py -3 tools/search_index.py <db> from "Michael Daniel"
py -3 tools/search_index.py <db> subject "renewal"
py -3 tools/search_index.py <db> year 2019
py -3 tools/search_index.py <db> parts <mailid>        # container pointers for a message
```

FTS5 syntax works in the `fts` command (`"invoice AND vultr"`, `"renew*"`, phrases).
