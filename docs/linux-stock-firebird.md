# Reading the archives on Linux with stock Firebird (no MailStore, no Windows)

Two routes. **A2** (here) decrypts to a plaintext `.fdb` that *unmodified* Firebird
opens — validated end-to-end on Firebird 4.0.6. **A1** is an in-place crypt plugin
(see `plugin/`).

## A2 — decrypt to a plaintext Firebird database

`tools/fb_decrypt.py` reads a MailStore `.fdb` + its `.key` and writes an ordinary
unencrypted Firebird 4 database:

- For every page whose `pag_flags` has `crypted_page` (0x80): AES-256-**ECB**
  decrypt `page[16:]` with the content key, then clear the 0x80 flag.
- On the header page: clear `hdr_flags` bits `hdr_encrypted|hdr_crypt_process`
  (offset 42), zero `hdr_crypt_page` (80) and `hdr_crypt_plugin` (84).

```
python3 fb_decrypt.py MailStoreFileGroup.fdb MailStoreFileGroup.key fg_plain.fdb
```

The result opens in any stock Firebird 4 / FlameRobin / DBeaver / firebird-driver
with no crypt plugin. Verified on Firebird 4.0.6 (`isql`): the decrypted Master DB
lists all user tables, and the decrypted FileGroup DB answers
`SELECT COUNT(*) FROM MAIL` and returns real subjects/senders/dates.

Needs only `pip install pycryptodome`. It is a decrypted *copy* (regenerate when
the archive changes). No per-page checksums exist in ODS 13, so decrypted pages
are valid as-is.

### Getting stock Firebird 4 on Linux (reference)

Firebird is open source. On Debian/Ubuntu the only runtime dependency not bundled
is `libtommath.so.0` (Firebird bundles libtomcrypt but not libtommath); install
the distro `libtommath` or build it from source and symlink the soname. ICU is
the distro's. Then `isql <plain.fdb>` (embedded) or point `firebird-driver` at
`libfbclient.so`.

## DPAPI / portability note

The decryptor derives the content key from the key file's **`masterkey`** (mode
`Unprotected`, in clear) via `DecryptAES` — it never uses Windows DPAPI. So this
works on Linux and, unlike MailStore's own plugin, **also decrypts the Lup
archive** (whose DPAPI product-key is bound to the old machine). Verified: Lup's
FileGroup DB opened on Linux with 24,243 messages / 126,248 parts.
