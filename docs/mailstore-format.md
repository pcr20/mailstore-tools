# MailStore Home archive — on-disk format and access

Notes assembled by inspecting MailStore Home archives (engine reports Firebird
**4.0.6**, ODS 13). MailStore publishes no specification for the on-disk format;
everything below is observed, and the parts marked *unverified* were not
reverse-engineered.

## 1. Folder layout

A portable MailStore Home archive is a folder containing:

```
MailStoreHomePortable.exe
Application\                      the app + a full Firebird 4 (32-bit) engine
  Firebird4_x86\
    fbclient.dll                  Firebird client (loads the embedded engine)
    plugins\engine13.dll          Firebird ODS-13 engine provider
    plugins\DBCrypt.dll           MailStore page-encryption plugin  <-- key piece
    gbak.exe gfix.exe gstat.exe   (no isql.exe is shipped)
    firebird.conf                 minimal; no KeyHolderPlugin/DBCrypt config
Cache\MailboxCache.fdb            unencrypted sync/cache state
Data\
    MailStoreMaster.fdb           archive bookkeeping   (encrypted)
    MailStoreMaster.key           key file for the above
    MailStoreFileGroup.fdb        message index         (encrypted)
    MailStoreFileGroup.key
    <n>.dat                       message content containers ("file group")
    <n>.rr                        recovery records (rebuild DB from containers)
    Index0001.dat                 full-text search index (proprietary)
    IndexFolder.txt  rr.prop  *.lock
```

Two databases: **Master** (users, folders, profiles, jobs) and **FileGroup**
(the per-message index). Message bytes themselves are **not** in the databases —
they are in the `<n>.dat` containers, referenced by integer pointers.

## 2. The encrypted databases

- Standard Firebird 4 files (page size **4096**, ODS **13 / 0x800D**) but with
  **page-level encryption**. The header page carries a `DBCRYPT` clumplet naming
  the crypt plugin plus key-hash clumplets; page 0's non-header area and all data
  pages are ciphertext (entropy ~8.0 bits/byte).
- `firebird.conf` contains no `KeyHolderPlugin` or `DBCrypt` entry, and there is
  no `DBCrypt.conf`. So MailStore does **not** supply the key via Firebird's
  normal key-holder mechanism — `DBCrypt.dll` locates and reads the sibling
  `.key` file itself, keyed off the database path.

### `DBCrypt.dll` (the crypt plugin)

A Firebird 4 **crypt plugin**, not a standalone decrypt library.

- Exported entry point: the single Firebird `firebird_plugin` registration
  function. It is driven by the engine, not callable standalone.
- Implements `IDbCryptPlugin`: `setInfo(IDbCryptInfo*)` (engine hands it the DB
  full path + page geometry), `setKey(...)`, and `encrypt`/`decrypt` operating on
  **one page buffer at a time**. Observed error strings confirm the coupling:
  `setKey failed because ptr_dbCryptInfo is NULL. setInfo(...) was not called`,
  `getDatabaseFullPath(...) returns NULL`.
- Uses the Windows CryptoAPI ("Microsoft Enhanced RSA and AES Cryptographic
  Provider") plus **DPAPI** (`CryptUnprotectData`) and reads the `.key` JSON
  itself (its strings include `the key file ... cannot be opened`,
  `missing the "key" property`).

Consequence: you cannot feed `DBCrypt.dll` a file and get plaintext. The only
practical use is to let MailStore's `engine13.dll` load it on attach — i.e. run
the vendor engine against the vendor database with the vendor key.

## 3. The `.key` file

UTF-8 (with BOM) JSON. Structure (lengths are decoded-base64 byte counts):

```
version      2
key          base64  (~262 B)   DPAPI-protected product/file key
timestamp, id, signature
keys:
  masterkey      mode=Unprotected   32 B   the AES master key, in clear
  recoverykey    mode=Passphrase    96 B   unwrapped by a user recovery passphrase
  passphrasekey  mode=DPAPI        246 B   kind=ProductKey (Windows-DPAPI bound)
  encryptionkey  mode=MasterKey     96 B   per-DB key, wrapped by masterkey
                                           (+128 B checksum)
```

- `encryptionkey` is the actual per-database AES-256 key, wrapped by `masterkey`.
- `masterkey` is marked **Unprotected** (present in clear), so in principle the
  database key is derivable from the file alone — but `DBCrypt` still validates
  the **DPAPI** `passphrasekey`/top-level `key` on attach, and that is what binds
  the archive to a machine/user.
- `recoverykey` (**Passphrase**) is MailStore's portability escape hatch: set a
  recovery passphrase in MailStore Home and the archive can be opened on another
  machine with it.

### DPAPI binding (why Lup fails off its origin machine)

`CryptUnprotectData` on a user-scoped blob only succeeds under the same Windows
user (and machine) that protected it. The Lup archive's `.key` was written on
`PC-PAUL` / `PAULROBERTS`; attaching on `DESKTOP-4461DDH` / `PCR20` fails with
`NTE_BAD_KEY_STATE (0x8009000B)`. The main archive's `.key` was written on this
machine/account, so it unwraps. There is no cross-machine fix other than the
recovery passphrase (via MailStore Home) or opening it on the origin box.

## 4. Content containers (`<n>.dat`, `<n>.rr`)

- `<n>.dat` begins with the ASCII header `MailStoreContainer-v1:` followed by
  encrypted (and, *unverified*, compressed) message-part blobs. Content is
  addressed by `(container number, entry number)` — see the pointer columns in
  §6.
- `<n>.rr` are recovery records; since MailStore Home 11 the archive DB can be
  rebuilt from the containers without re-archiving.
- `Index0001.dat` is MailStore's full-text search index (proprietary; not parsed
  here).

The container entry framing and the compression/encoding of a stored part were
**not** reverse-engineered. For message bodies, MailStore Home's EML export is
the clean path.

## 5. Schema — `MailStoreMaster.fdb` (15 tables)

Archive bookkeeping. Notable tables:

- `USER` — accounts (`USERNAME`, `PASSWORDHASH CHAR(80)`, `ISADMIN`, MFA fields).
  One row in a Home archive.
- `PROFILE` — archiving profiles (`CONNECTOR`, `PROPERTIES` blob). 6 rows here.
- `FOLDER`, `USERFOLDER`, `FILEGROUP`, `CREDENTIAL`, `TAG`, `USERMAPPING`,
  `USERDATA`, `GLOBALPROPERTY`, `GLOBALBINARY`, `KNOWNKEYS`.
- `JOB`, `JOBRESULT`, `WORKERRESULT` — archiving run history (32 worker results).

Full column listing: `captures/schema_main_archive.txt`.

## 6. Schema — `MailStoreFileGroup.fdb` (the message index)

This is the interesting one.

### `MAIL` — one row per message (714,245 rows in the main archive)

| column | type | meaning |
|---|---|---|
| `MAILID` | BIGINT | primary key |
| `FOLDERID` | BIGINT | → `FOLDER` |
| `MESSAGEID` | VARCHAR(200) | RFC Message-ID |
| `HEADERHASH` | CHAR(40) | dedup hash |
| `DATE` | TIMESTAMP | message date |
| `ARCDATE` | TIMESTAMP | archival date |
| `FLAGS` | INTEGER | read/flag bits |
| `SIZE` | BIGINT | message size |
| `RRCONTAINER` / `RRENTRY` | BIGINT / INT | pointer into recovery records |
| `DISPLAYSUBJECT` | VARCHAR(255) | **subject (searchable directly)** |
| `DISPLAYFROMORTO` | VARCHAR(255) | **from/to (searchable directly)** |

`MAIL` alone gives a header-level index: subject, correspondent, date, folder,
size — no container decoding needed.

### `MIMEENTITY` — per-part pointers into the containers

| column | type | meaning |
|---|---|---|
| `MIMEENTITYID` | BIGINT | pk |
| `MAILID` | BIGINT | → `MAIL` |
| `PARENTMIMEENTITYID` | BIGINT | MIME tree parent |
| `POSITION` | INTEGER | order within parent |
| `HEADERSTRING` | BLOB(text) | this part's headers |
| `CONTENTCONTAINER` / `CONTENTENTRY` | BIGINT / INT | → `<container>.dat` entry (raw part) |
| `CONTENTISDECODED` | SMALLINT | whether stored decoded |
| `CONTENTHASH` | CHAR(40) | dedup hash |
| `PLAINTEXTCONTAINER` / `PLAINTEXTENTRY` | BIGINT / INT | → extracted plain text |
| `HEADERCONTAINER` / `HEADERENTRY` | BIGINT / INT | → full header blob |

So the content path is:
`MAIL.MAILID → MIMEENTITY.* → (container N, entry E) → Data\<N>.dat @ entry E`,
with separate pointers for the raw part, an extracted plaintext copy, and the
headers. Dedup is by `CONTENTHASH` / `HEADERHASH` (identical parts stored once).

### Other FileGroup tables

- `FOLDER` (238 rows) — folder names (name stored as a blob).
- `FOLDERCMB` — combined/virtual folder definitions.
- `MAILTAG` — message↔tag links.
- `SEARCHINDEX` — full-text index metadata (`NEEDSREBUILD`).
- `GLOBALPROPERTY` — misc settings.

## 7. Access recipe that works

1. Windows, Python 3.11+, MailStore's own `Firebird4_x86` folder intact.
2. Copy the target `.fdb` **and its `.key`** into a scratch folder together.
3. `firebird-driver` → `driver_config.fb_client_library.value =` MailStore's
   `fbclient.dll`; set `FIREBIRD` env to that folder so `plugins\` + `.msg` + ICU
   resolve.
4. `connect(<db>, user="SYSDBA", password="masterkey", no_db_triggers=True)`.
5. Query `RDB$RELATIONS` / `RDB$RELATION_FIELDS` for schema, or `MAIL` for the
   header index.

Works only where the `.key`'s DPAPI blob unwraps — i.e. the machine/account that
created the archive (§3), or after setting a recovery passphrase in MailStore.
