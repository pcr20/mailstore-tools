# MailStore database page cipher (`MailStore*.fdb`) — recovered

How MailStore's `DBCrypt` plugin encrypts the Firebird databases, recovered by
disassembling `DBCrypt.dll` (native) and `MailStoreHome.exe` (.NET) and verified
against a real archive (RLE-decompressed `RDB$RELATIONS` records yield the actual
Firebird system-table names). This is the missing piece for an open-source,
in-place reader on Linux (no MailStore binaries).

## What is encrypted

Firebird encrypts **selectively, by page type** (standard Firebird behaviour):

| page type | contents | encrypted? |
|---|---|---|
| 1 header, 2 PIP, 3 TIP, 4 pointer, 6 index-root, 10 SCN | structure | **no** (clear) |
| 5 data, 7 index B-tree, 8 blob, 9 generator | content | **yes** |

On every page the 16-byte `pag` header stays in clear — crucially including
`pag_pageno` at offset 12 — so Firebird can identify pages without the key.

## Cipher

```
key   = contentKey           (32 bytes; the same key as the containers —
                              DecryptAES(masterKey, encryptionKey); see mailstore-format.md)
mode  = AES-256-ECB          (NOT CBC — each 16-byte block independent, so any
                              page decrypts standalone with no IV/chaining)
region= page[16 : page_size] (the body after the 16-byte pag header)
```

Decrypt a page: `AES-256-ECB(contentKey).decrypt(page[16:])`, leave `page[0:16]`
as-is. Firebird then RLE-decompresses records itself. (Verified: data-page
record-pointer arrays are valid and `RDB$RELATIONS` records decompress to
`RDB$RELATIONS`, `RDB$FIELDS`, `RDB$DATABASE`, … and the MailStore tables.)

Page size here is 4096, ODS 13 (Firebird 4). `page_size - 16 = 4080 = 255*16`,
an exact AES block multiple, consistent with the plugin's "length % 16 == 0" check.

## Header page crypt marker

Page 0 carries the `DBCRYPT` plugin name plus two base64 SHA-1 **key-verification
hashes** (no IV is stored — ECB needs none). A stock Firebird refuses the file
until a crypt plugin registered as `DBCRYPT` supplies a key whose hash matches.

## Three ciphers, one key

| data | cipher | mode |
|---|---|---|
| key file wrapping (`encryptionkey`) | AES-256 + PBKDF2-HMAC-SHA1(1000) | CBC |
| content containers (`.dat` entries) | AES-256, content key | CBC (per-entry IV) |
| **database pages (`.fdb`)** | **AES-256, content key** | **ECB** |

## Open-source Linux access (Route A)

With this, stock open-source Firebird 4 can read the archives on Linux via a
small `DBCrypt`+KeyHolder plugin (from `examples/dbcrypt`) that: computes the
content key from the `.key`, and ECB-encrypts/decrypts the page buffer Firebird
hands it. No index build, no Windows, no MailStore binaries. (A simpler interim:
ECB-decrypt the pages into a plaintext `.fdb` copy and clear the page-0 crypt
marker, which any stock Firebird opens directly.)
