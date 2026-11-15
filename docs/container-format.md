# MailStore content container format (`Data\<n>.dat`) — decoded

Fully reverse-engineered from `MailStoreHome.exe` and verified end-to-end
against a real archive with the owner's key. Reading is **in place and
read-only** — nothing in the archive is modified.

## File layout

```
offset 0  : "MailStoreContainer-v1:"            (22-byte magic)
offset 22 : offset table, uint64-LE             table[i] = start of entry i in data region
data base : 22 + 8*len(table)
entries   : data[ table[i] : table[i+1] ]
footer    : trailing "MailStoreDataContainer..." metadata block
```

A `(container, entry)` pointer from the FileGroup DB selects `Data\<container>.dat`,
entry `entry` = `data[table[entry] : table[entry+1]]`.

## Entry record

```
prefix(8)                 per-entry value (an entry hash; not needed to decode)
"MSE1"(4)                 entry magic
mse1len(8, uint64-LE)     length of the rest of the entry
"MailStoreData"(13)       serialization-envelope magic
version(1)                1..4  (observed: 4)
encFlag(1)                1 = encrypted
compFlag(1)               1 = gzip-compressed
plainLen(8, uint64-LE)    decoded length  (present when version >= 3)
IV(16)                    AES-CBC IV
ciphertext(N*16)          AES-256-CBC
trailer(8)                extra bytes after the ciphertext
```

## Keys and cipher (recovered from MailStoreHome.exe)

Key file (`MailStoreMaster.key` / `MailStoreFileGroup.key`) — see
`mailstore-format.md` for the JSON. The two relevant keys:

- `masterkey`  (mode `Unprotected`) = 32-byte AES-256 key, in clear.
- `encryptionkey` (mode `MasterKey`) = the content key, wrapped by `masterkey`.

`DecryptAES(key, blob)` (MailStoreHome.exe):
```
blob = salt(16) | iv(16) | AES-256-CBC-PKCS7( salt(16) | plaintext )
aesKey = PBKDF2-HMAC-SHA1(key, salt, 1000) -> 32 bytes        # Rfc2898DeriveBytes
decrypt, strip PKCS7, verify leading 16 bytes == salt, return the rest
```

Content key:  `contentKey = DecryptAES(masterkey, encryptionkey)[:32]`.
Verified two ways: the built-in salt-check passes, and the key file's
`encryptionkey.checksum` decrypts (same scheme) to the ASCII test vector
`0123456789abcdef0123456789abcdef`.

Container entry decode (version 4):
```
AES-256-CBC( key = contentKey, iv = IV ) over the block-aligned ciphertext
then, if compFlag: gzip-inflate
then take plainLen bytes
```
Note the container cipher uses the content key **directly** (no per-entry
PBKDF2) with a random 16-byte IV stored at the front of each value — fast
enough for millions of entries. Header/plaintext/content parts are stored as
separate entries; a full message is reassembled from its `MIMEENTITY` tree
(root headers + boundary-delimited child parts).

## Tools

- `tools/mailstore_lib.py` — key unwrap, container decode, message reassembly.
- `tools/mailstore_read.py` — CLI: `search`, `eml <mailid>`, `text <mailid>`
  against the SQLite index + the untouched `Data\` folder.

Verified: reconstructed messages parse as valid RFC822/MIME (correct Subject,
From, Date, multipart structure, and decoded bodies).
