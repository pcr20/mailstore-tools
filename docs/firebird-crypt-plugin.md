# A1 — open-source Firebird DBCRYPT plugin (read the archive in place)

`plugin/MsDbCrypt.cpp` is a ~250-line Firebird 4 database-encryption plugin that
reproduces MailStore Home's page cipher, so **stock Firebird opens a MailStore
archive database directly, with the files left in their native encrypted form** —
no decrypted copy, no index rebuild.

Validated on Firebird 4.0.6 (the exact engine MailStore bundles): the plugin opens
the untouched encrypted `MailStoreMaster.fdb` and a `MailStoreFileGroup.fdb` and
answers ordinary SQL (`SELECT COUNT(*) FROM MAIL` → 24,243; real subjects/senders/
dates).

## How it works

- Registers a `TYPE_DB_CRYPT` plugin named **`DBCRYPT`** (matching the name stored
  in the database header's `hdr_crypt_plugin`).
- `setInfo` captures the database path; `setKey` reads the sibling `.key` file and
  derives the content key exactly as MailStore does:
  `PBKDF2-HMAC-SHA1(masterKey, salt=encBlob[0:16], 1000, 32)` → AES-256-CBC
  (iv = `encBlob[16:32]`) decrypt of `encBlob[32:]`, content key = plaintext[16:48].
- `encrypt`/`decrypt` are AES-256-**ECB** over the buffer Firebird passes (via
  OpenSSL). No Windows / DPAPI — the masterkey is stored in the clear, so it runs
  on Linux and also opens the Lup archive.

**Key-hash check passes automatically.** On attach Firebird validates the key by
encrypting the sample `"0123456789ABCDEF"` with the plugin and comparing
`base64(sha1(result))` to the header's `HDR_crypt_hash`. Because the plugin's ECB
output is byte-identical to MailStore's, the hashes match with no special handling.

## Build & install

```
FB=/opt/firebird ./plugin/build.sh          # needs g++ + libssl-dev + FB4 headers
cp DBCRYPT.so $FB/plugins/
cat plugin/plugins.conf.snippet >> $FB/plugins.conf
```

Then open `.../MailStoreMaster.fdb` (its `.key` beside it) with isql / DBeaver /
firebird-driver — no KeyHolder, no decryption step.

Reference engine for a self-contained test rig: Firebird 4.0.6 Linux tarball
(`Firebird-4.0.6.*.amd64.tar.gz`). Its only unbundled runtime dep is
`libtommath.so.0` — build it from libtommath source and drop the `.so.0` into
`$FB/lib` (Firebird bundles libtomcrypt but not libtommath).

## Read-only / untouched archives

Firebird refuses **read-write** access to a database whose file is read-only on
disk (it will not silently downgrade): `isc_no_priv "read-write access to
database"` (jrd/pag.cpp). Options to read the original archive files, which are
normally read-only:

1. Open from a **writable copy** of the `.fdb` (archive bytes preserved elsewhere).
2. Mark the database read-only once — `gfix -mode read_only <db>` (one header
   write) — after which it opens read-only even from read-only media, in place,
   forever.

If you need the files byte-for-byte untouched and read-only, prefer **A2**
(`tools/fb_decrypt.py`) which writes a separate plaintext copy and never needs the
original to be writable.

## A1 vs A2

| | A1 plugin | A2 decrypt-to-copy |
|--|--|--|
| Firebird | stock + this plugin | stock, unmodified |
| Archive files | read in place (native encrypted form) | one plaintext copy made |
| Extra build | compile one `.so` | none (pure Python) |
| Best when | you want to point tools straight at the live archive | maximum portability / zero native code |
