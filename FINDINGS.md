# MailStore Home — archive format findings

A complete reverse-engineering of the **MailStore Home** on-disk archive, from
"can these files be read at all?" to a working, dependency-free reader that
reconstructs any message **in place** without the MailStore application.

Reference environment: MailStore Home portable, engine **Firebird 4.0.6 / ODS 13**,
`MailStoreHome.exe` version **26.2.0.24007**. Verified against a real archive of
**714,245 messages** (2000–2026).

---

## 1. Starting point

A MailStore Home archive folder (`...\Mailstore\`) contains:

- `Application\` — the app plus a full bundled Firebird 4 engine
  (`fbclient.dll`, `plugins\engine13.dll`, `plugins\DBCrypt.dll`) and
  `MailStoreHome.exe`.
- `Data\` — two encrypted Firebird databases (`MailStoreMaster.fdb`,
  `MailStoreFileGroup.fdb`) with their `.key` files, plus the content
  containers `<n>.dat`, recovery records `<n>.rr`, and a search index.

Nothing about the byte formats is publicly documented; MailStore's position is
"export to EML if you want portability." Both databases are Firebird files but
**page-level encrypted** (a `DBCRYPT` clumplet in the header, data pages at ~8.0
bits/byte entropy), so a stock Firebird client cannot open them, and the `.dat`
containers are likewise opaque.

---

## 2. Reading the databases: engine-with-plugin

The archive is self-contained — it ships the exact engine and crypt plugin that
can open it. Rather than reverse the database encryption, we drive MailStore's
own stack: point the pure-Python `firebird-driver` at the bundled `fbclient.dll`
(which loads `engine13.dll` + `DBCrypt.dll`), copy a database with its sibling
`.key`, and attach. Login is plain `SYSDBA` / `masterkey`; the plugin decrypts
pages on attach. No key extraction — the vendor engine does the work.

This yielded the full schema (`docs/mailstore-format.md`):

- **`MailStoreMaster.fdb`** — users, profiles, folders, jobs (15 tables).
- **`MailStoreFileGroup.fdb`** — the message index:
  - `MAIL` (one row per message: `DISPLAYSUBJECT`, `DISPLAYFROMORTO`, `DATE`,
    `FOLDERID`, `SIZE`, …) — a directly searchable header index.
  - `MIMEENTITY` — the MIME tree, each part carrying `CONTENT*`, `PLAINTEXT*`,
    `HEADER*` `(container, entry)` pointers into the `.dat` files.

### The DPAPI portability catch

`DBCrypt` unwraps part of the key set with **Windows DPAPI**, which is bound to
the Windows **user + machine** that created the archive. The main archive
(created on this machine as this user) opens; the dormant **Lup** archive
(created as `PAULROBERTS` on `PC-PAUL`) fails with
`DbCrypt: UnprotectData … NTE_BAD_KEY_STATE` and can only be opened on its origin
box or via its MailStore recovery passphrase. (See §6 — our own reader does not
use DPAPI, so this limit is narrower than it first appears.)

---

## 3. The key file

`MailStore*.key` is UTF-8/BOM JSON. The keys that matter:

| key | mode | meaning |
|---|---|---|
| `masterkey` | `Unprotected` | 32-byte AES-256 key, **in clear** |
| `encryptionkey` | `MasterKey` | the content key, wrapped by `masterkey` (+ checksum) |
| `passphrasekey` | `DPAPI` (ProductKey) | Windows-bound; the DPAPI wall above |
| `recoverykey` | `Passphrase` | the cross-machine escape hatch (recovery passphrase) |

Because `masterkey` is present in clear, the content key is derivable **from the
key file alone** — DPAPI is one unwrap path, not the only one.

---

## 4. The crypto, recovered from `MailStoreHome.exe`

`MailStoreHome.exe` is a .NET assembly; its managed IL was disassembled
(`dnfile`/`dncil`) to read the exact construction rather than guess it.

**`DecryptAES(key, blob)`** — used for the key file and database key wrapping:

```
blob   = salt(16) | iv(16) | AES-256-CBC-PKCS7( salt(16) | plaintext )
aesKey = PBKDF2-HMAC-SHA1(key, salt, 1000) -> 32 bytes      (Rfc2898DeriveBytes)
decrypt, strip PKCS7, verify leading 16 bytes == salt, return the rest
```

**Content key:** `contentKey = DecryptAES(masterkey, encryptionkey)[:32]`.
Verified two independent ways: the built-in salt-check passes, **and** the key
file's `encryptionkey.checksum` decrypts (same scheme) to the ASCII test vector
`0123456789abcdef0123456789abcdef`.

**Content containers (`Data\<n>.dat`)** — framing:

```
"MailStoreContainer-v1:"(22) | uint64-LE offset table | entries | footer
entry = prefix(8) | "MSE1" | mse1len(u64) |
        "MailStoreData" | version(1) | encFlag(1) | compFlag(1) |
        plainLen(u64, if version>=3) | IV(16) | AES-256-CBC ciphertext | trailer(8)
```

Entry decode (version 4, as observed): `AES-256-CBC(contentKey, IV)` over the
block-aligned ciphertext, then **gzip-inflate** if `compFlag`, then take
`plainLen` bytes. The container cipher uses the content key **directly** (no
per-entry PBKDF2) with a random 16-byte IV at the front of each value — fast
enough for millions of entries. A message is reassembled from its `MIMEENTITY`
tree: root headers + boundary-delimited child parts (`header` entries +
`content` entries).

Robustness note: the offset-table length is found deterministically by anchoring
on the per-entry `MSE1` marker, not by a monotonic heuristic.

---

## 5. Result — in-place reader

`tools/mailstore_lib.py` + `tools/mailstore_read.py` reconstruct any message from
the SQLite index (built by `build_index.py`) and the untouched `Data\` folder.
AES uses `pycryptodome` if present, otherwise **Windows CNG via ctypes**, so it
runs with no binary dependencies (tested on Python 3.15).

Verified end-to-end on the live archive:

- Oldest message (2007 Google Calendar share) — full multipart reconstructed.
- Recent message (Nov 2026 Xero invoice thread, INV-0057) — reconstructed as a
  valid nested `multipart/related → multipart/alternative → text/plain +
  text/html + image/jpeg`, i.e. **headers, bodies and attachments** intact.

Everything is read-only; the archive is never modified.

```
py -3 mailstore_read.py <key> <Data dir> index.db search "<fts>"
py -3 mailstore_read.py <key> <Data dir> index.db text  <mailid>
py -3 mailstore_read.py <key> <Data dir> index.db eml   <mailid> out.eml
```

---

## 6. Limitations & open items

- **Lup archive.** The DPAPI wall blocked only the *Firebird attach* path. Our
  container reader never uses DPAPI, so if Lup's `masterkey` is also stored
  `Unprotected`, its containers are decodable directly. The one remaining piece
  is reading Lup's `MIMEENTITY` tree — its `FileGroup.fdb` is still page-encrypted
  and DPAPI-locked for the plugin (needs the recovery passphrase, or reimplementing
  Firebird page decryption).
- **Scope.** Observed `version == 4` entries throughout; the reader also carries
  the version-1/2 (legacy) code paths seen in the IL but these were not exercised.

---

## 7. Security implication

Once the scheme is known, the `.key` file *is* the archive — anyone holding it
plus the `.dat` files can read every message, with no Windows account or DPAPI
binding required (the `Unprotected` master key is sufficient). The DPAPI binding
protects only the application's own open path, not the data at rest. Treat the
`.key` file as a credential.

---

## 8. Toolset

| file | purpose |
|---|---|
| `tools/dump_schema.py` | attach the encrypted DBs via the bundled engine + plugin; dump schema |
| `tools/build_index.py` | extract `MAIL` + `MIMEENTITY` into SQLite (+ FTS5) |
| `tools/search_index.py` | query the header/file index (stdlib only) |
| `tools/mailstore_lib.py` | key unwrap, container decode, MIME reassembly |
| `tools/mailstore_read.py` | in-place, read-only reader CLI (search / text / eml) |
| `docs/mailstore-format.md` | databases, key file, schema |
| `docs/container-format.md` | container + entry format and cipher |
| `docs/searching.md` | building and querying the index |

> **Update:** Lup is in fact fully recoverable without the recovery passphrase. The DPAPI wall only blocks MailStore's *own* Firebird plugin; our reader derives the content key from the clear `masterkey`, so it decrypts Lup too (verified: Lup FileGroup opened on stock Linux Firebird, 24,243 messages). See `docs/linux-stock-firebird.md`.
