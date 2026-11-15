#!/usr/bin/env python3
"""Read messages from a MailStore Home archive in place (no export, read-only).

Uses the SQLite index (from build_index.py) for the MIME-entity tree and the
decryption library (mailstore_lib.py) to decode the content containers.

Usage:
  python mailstore_read.py <keyfile> <data_dir> <index.db> search "<fts>" [limit]
  python mailstore_read.py <keyfile> <data_dir> <index.db> eml <mailid> [out.eml]
  python mailstore_read.py <keyfile> <data_dir> <index.db> text <mailid>

<data_dir> is the folder holding the <n>.dat containers (e.g. ...\\Mailstore\\Data).
Nothing in the archive is modified.
"""
import sys, sqlite3, email
from mailstore_lib import content_key_from_keyfile, Archive, reassemble

def parts_for(db, mailid):
    rows = db.execute("""select mimeentityid, parentid, position,
                                content_container, content_entry,
                                header_container, header_entry
                         from part where mailid=? order by position""", (mailid,)).fetchall()
    return [dict(mailid=mailid, mimeentityid=r[0], parentid=r[1], position=r[2],
                 content_container=r[3], content_entry=r[4],
                 header_container=r[5], header_entry=r[6]) for r in rows]

def main():
    keyfile, data_dir, dbpath, cmd = sys.argv[1:5]
    a = sys.argv[5:]
    ck = content_key_from_keyfile(keyfile)
    arc = Archive(data_dir, ck)
    db = sqlite3.connect(dbpath); db.row_factory = sqlite3.Row

    if cmd == "search":
        q = a[0]; lim = int(a[1]) if len(a) > 1 else 20
        for r in db.execute("""select m.mailid, m.date, m.subject, m.fromorto
                               from mail_fts x join mail m on m.mailid=x.rowid
                               where mail_fts match ? order by m.date desc limit ?""", (q, lim)):
            print(f"[{r['mailid']}] {str(r['date'])[:19]}  {r['fromorto']}  |  {r['subject']}")
        return

    mailid = int(a[0])
    raw = reassemble(parts_for(db, mailid), arc)
    if raw is None:
        print("no parts for mail", mailid); return
    if cmd == "eml":
        out = a[1] if len(a) > 1 else f"mail_{mailid}.eml"
        open(out, "wb").write(raw)
        print(f"wrote {out} ({len(raw)} bytes)")
    elif cmd == "text":
        msg = email.message_from_bytes(raw)
        print("Subject:", msg['subject']); print("From   :", msg['from'])
        print("To     :", msg['to']);      print("Date   :", msg['date']); print()
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                try: print(p.get_payload(decode=True).decode(p.get_content_charset() or "latin-1", "replace"))
                except Exception: print(p.get_payload())
                break
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
