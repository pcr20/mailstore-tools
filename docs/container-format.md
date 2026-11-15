# MailStore content container format (`Data\<n>.dat`)

Reverse-engineered **framing only** (file layout). The entry payloads are
encrypted and are NOT decoded here — see "Payloads" below.

## File layout

```
offset 0   : "MailStoreContainer-v1:"            (22-byte ASCII magic)
offset 22  : offset table — array of uint64 LE
             table[i] = start of entry i within the data region
             (table[0] = 0; monotonically increasing)
data base  : 22 + 8 * len(table)
entries    : data[ table[i] : table[i+1] ]       one blob per table slot
footer     : trailing block beginning "MailStoreDataContainer..." (plaintext
             metadata; sits after the last entry)
```

A `(container, entry)` pointer from `MIMEENTITY`/`MAIL` in the FileGroup DB
selects file `Data\<container>.dat`, entry index `entry` → the byte range
`data[table[entry] : table[entry+1]]`.

Reference container `1.dat`: 1,022 entries, data base 8206, 1,452-byte footer.

## Entry record

Each entry blob is:

```
8 bytes   per-entry prefix   (high-entropy; nonce / IV seed / auth tag)
4 bytes   "MSE1"             (ASCII magic, MailStore Entry v1)
8 bytes   payload length L   (uint64 LE)
L bytes   payload            (AES ciphertext; L is always a multiple of 16)
```

So an entry's on-disk size is `20 + L`, and every observed entry size ≡ 4 (mod 16).

## Payloads — encrypted, not compressed

Evidence that the `L`-byte payloads are AES-encrypted rather than compressed:

- `L` is **always a multiple of 16** (AES block size) across all 1,022 entries.
- **Zero** entries carry a zlib (`78 9c/01/da`) or gzip (`1f 8b`) magic.
- Data-region byte entropy is **7.99 / 8.0** (indistinguishable from random).
- Even the tiny `rr.prop` properties file is full-entropy (the archive
  encrypts auxiliary files too).

The key is the FileGroup `encryptionkey` (AES-256, mode `MasterKey` — wrapped by
the `Unprotected` `masterkey`; see `mailstore-format.md`). The 8-byte per-entry
prefix is the per-entry IV/nonce. The exact cipher mode and IV derivation live in
MailStore's application code and are **not** reproduced here.

## Getting decoded bodies

This framing locates every message part exactly, but readable text requires
MailStore's content decryption. The supported route is **MailStore Home → Export
→ EML** (MailStore decrypts on export; also the only route for the Lup archive,
via its recovery passphrase). Reimplementing the content cipher from the key is
out of scope here.
