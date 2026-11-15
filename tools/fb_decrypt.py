#!/usr/bin/env python3
"""A2: decrypt a MailStore .fdb to a plaintext Firebird DB that stock Firebird
opens with no crypt plugin. Decrypt every page whose pag_flags has crypted_page
(0x80) set: AES-256-ECB over page[16:], then clear the 0x80 flag. Finally clear
the header-page crypt state so the engine treats the file as unencrypted."""
import json,base64,hashlib,struct,sys
from Crypto.Cipher import AES
CRYPTED=0x80  # Ods::crypted_page (pag_flags)
def content_key(keyfile):
    k=json.load(open(keyfile,encoding='utf-8-sig')); b=base64.b64decode
    mk=b(k['keys']['masterkey']['key']); ek=b(k['keys']['encryptionkey']['key'])
    dk=hashlib.pbkdf2_hmac('sha1',mk,ek[:16],1000,32)
    return AES.new(dk,AES.MODE_CBC,ek[16:32]).decrypt(ek[32:])[16:48]
def main(fdb,keyfile,out):
    key=content_key(keyfile); d=bytearray(open(fdb,'rb').read())
    ps=struct.unpack_from('<H',d,16)[0]; dec=AES.new(key,AES.MODE_ECB); n=0
    for p in range(len(d)//ps):
        base=p*ps
        if d[base+1] & CRYPTED:
            d[base+16:base+ps]=dec.decrypt(bytes(d[base+16:base+ps]))
            d[base+1] &= ~CRYPTED      # clear crypted_page flag
            n+=1
    # header page (page 0): clear crypt flags + plugin name
    fl=struct.unpack_from('<H',d,42)[0]; struct.pack_into('<H',d,42, fl & ~0x44)  # hdr_encrypted|hdr_crypt_process
    struct.pack_into('<I',d,80,0)          # hdr_crypt_page
    d[84:84+32]=b'\x00'*32                  # hdr_crypt_plugin
    open(out,'wb').write(d)
    print("decrypted %d crypted pages; header crypt flag was %#x -> cleared; wrote %s"%(n,fl,out))
if __name__=='__main__': main(*sys.argv[1:4])
