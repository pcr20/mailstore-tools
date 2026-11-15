#!/usr/bin/env python3
"""Read a MailStore Home archive in place: decrypt content containers and
reassemble messages, without exporting or modifying anything.

Scheme (recovered from MailStoreHome.exe):
  content key = DecryptAES(masterKey, encryptionKey) from the FileGroup .key
    DecryptAES(key,blob): blob = salt(16)|iv(16)|AES-CBC-PKCS7( salt|plaintext ),
      aesKey = PBKDF2-HMAC-SHA1(key, salt, 1000, 32); verify leading salt.
  container Data\\<n>.dat:
    "MailStoreContainer-v1:"(22) | uint64-LE offset table | entries | footer
    entry = prefix(8) | "MSE1" | mse1len(u64) |
            "MailStoreData" | version(1) | encFlag(1) | compFlag(1) |
            plainLen(u64, if version>=3) | IV(16) | AES-CBC ciphertext | trailer(8)
    decode: AES-256-CBC(contentKey, IV) over block-aligned ciphertext,
            then gzip-inflate if compFlag, take plainLen bytes.
"""
import json, base64, hashlib, struct, zlib, os, sys

# AES-256-CBC decrypt with no padding. Prefer pycryptodome; otherwise use the
# OS-native provider (Windows CNG via ctypes) so no binary wheel is needed.
def _aes_cbc_decrypt(key, iv, ct):
    try:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    except ImportError:
        pass
    if sys.platform == "win32":
        return _aes_cbc_decrypt_cng(key, iv, ct)
    raise RuntimeError("no AES backend: install pycryptodome")

def _aes_cbc_decrypt_cng(key, iv, ct):
    import ctypes
    from ctypes import wintypes
    bcrypt = ctypes.WinDLL("bcrypt.dll")
    alg = ctypes.c_void_p()
    if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(alg),
            ctypes.c_wchar_p("AES"), None, 0): raise OSError("open alg")
    try:
        mode = ctypes.create_unicode_buffer("ChainingModeCBC")
        bcrypt.BCryptSetProperty(alg, ctypes.c_wchar_p("ChainingMode"),
            ctypes.cast(mode, ctypes.POINTER(ctypes.c_ubyte)),
            (len(mode.value)+1)*2, 0)
        hkey = ctypes.c_void_p()
        kb = (ctypes.c_ubyte*len(key)).from_buffer_copy(key)
        if bcrypt.BCryptGenerateSymmetricKey(alg, ctypes.byref(hkey), None, 0,
                kb, len(key), 0): raise OSError("genkey")
        try:
            ivb = (ctypes.c_ubyte*len(iv)).from_buffer_copy(iv)
            inb = (ctypes.c_ubyte*len(ct)).from_buffer_copy(ct)
            out = (ctypes.c_ubyte*len(ct))()
            res = wintypes.ULONG(0)
            if bcrypt.BCryptDecrypt(hkey, inb, len(ct), None, ivb, len(iv),
                    out, len(ct), ctypes.byref(res), 0): raise OSError("decrypt")
            return bytes(out[:res.value])
        finally:
            bcrypt.BCryptDestroyKey(hkey)
    finally:
        bcrypt.BCryptCloseAlgorithmProvider(alg, 0)

def _b64(s): return base64.b64decode(s)

def _decrypt_aes(key, blob):
    salt, iv, ct = blob[:16], blob[16:32], blob[32:]
    dk = hashlib.pbkdf2_hmac('sha1', key, salt, 1000, 32)
    pt = _aes_cbc_decrypt(dk, iv, ct)
    if pt and 1 <= pt[-1] <= 16 and pt[-pt[-1]:] == bytes([pt[-1]])*pt[-1]:
        pt = pt[:-pt[-1]]
    if pt[:16] != salt:
        raise ValueError("salt-check failed")
    return pt[16:]

def content_key_from_keyfile(path):
    k = json.load(open(path, encoding='utf-8-sig'))
    mk = _b64(k['keys']['masterkey']['key'])
    ek = _b64(k['keys']['encryptionkey']['key'])
    return _decrypt_aes(mk, ek)[:32]

class Container:
    def __init__(self, path, content_key):
        self.key = content_key
        self.d = open(path, 'rb').read()
        assert self.d[:22] == b'MailStoreContainer-v1:', "bad container magic"
        off = []; p = 22; prev = -1
        while p + 8 <= len(self.d):
            v = struct.unpack_from('<Q', self.d, p)[0]
            if v < prev or v > len(self.d): break
            off.append(v); prev = v; p += 8
        self.off = off
        self.base = 22 + 8*len(off)

    def entry_count(self): return len(self.off) - 1

    def decode(self, idx):
        e = self.d[self.base + self.off[idx]: self.base + self.off[idx+1]]
        j = e.find(b'MailStoreData')
        if j < 0: raise ValueError("no MailStoreData header")
        p = j + 13
        ver, enc, comp = e[p], e[p+1], e[p+2]; p += 3
        ln = -1
        if ver >= 3:
            ln = struct.unpack_from('<q', e, p)[0]; p += 8
        data = e[p:]
        out = data
        if enc:
            iv, body = data[:16], data[16:]
            ctlen = (len(body)//16)*16
            out = _aes_cbc_decrypt(self.key, iv, body[:ctlen])
        if comp:
            do = zlib.decompressobj(16 + zlib.MAX_WBITS)
            out = do.decompress(out) + do.flush()
        elif enc:
            if out and 1 <= out[-1] <= 16 and out[-out[-1]:] == bytes([out[-1]])*out[-1]:
                out = out[:-out[-1]]
        if ln >= 0:
            out = out[:ln]
        return out

class Archive:
    """Decode (container, entry) pointers against a directory of .dat files."""
    def __init__(self, data_dir, content_key):
        self.dir = data_dir; self.key = content_key; self._cache = {}
    def _container(self, n):
        c = self._cache.get(n)
        if c is None:
            c = Container(os.path.join(self.dir, f"{n}.dat"), self.key)
            self._cache[n] = c
        return c
    def get(self, container, entry):
        if container is None or entry is None: return None
        return self._container(container).decode(entry)

def reassemble(parts, archive):
    """parts: list of dicts with keys mailid,mimeentityid,parentid,position,
    header_container,header_entry,content_container,content_entry.
    Returns the full message bytes (RFC822)."""
    by_parent = {}
    for p in parts:
        by_parent.setdefault(p['parentid'], []).append(p)
    for v in by_parent.values():
        v.sort(key=lambda x: (x['position'] or 0))
    roots = by_parent.get(None) or by_parent.get(0) or []
    # MailStore uses parentid NULL for root; some use 0
    def boundary(hdr):
        import re
        m = re.search(rb'boundary="?([^";\r\n]+)"?', hdr, re.I)
        return m.group(1) if m else None
    def render(ent):
        hdr = archive.get(ent['header_container'], ent['header_entry']) or b''
        kids = by_parent.get(ent['mimeentityid'], [])
        if kids:
            b = boundary(hdr) or b'=_boundary_'
            body = b''
            for k in kids:
                body += b'--' + b + b'\r\n' + render(k) + b'\r\n'
            body += b'--' + b + b'--\r\n'
            return hdr + b'\r\n' + body
        content = archive.get(ent['content_container'], ent['content_entry']) or b''
        return hdr + b'\r\n' + content
    if not roots: return None
    return render(roots[0])
