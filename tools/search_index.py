#!/usr/bin/env python3
"""Search the MailStore header/file index built by build_index.py.

Usage:
  python search_index.py <mailstore_index.db> stats
  python search_index.py <db> folders [min_count]
  python search_index.py <db> fts "<fts5 query>" [limit]      # subject+sender full-text
  python search_index.py <db> subject "<substring>" [limit]
  python search_index.py <db> from "<substring>" [limit]
  python search_index.py <db> year <YYYY> [limit]
  python search_index.py <db> parts <mailid>                  # file-index: container pointers
"""
import sqlite3, sys, textwrap

def main():
    if len(sys.argv) < 3:
        print(textwrap.dedent(__doc__)); return
    db = sqlite3.connect(sys.argv[1]); db.row_factory = sqlite3.Row
    cmd = sys.argv[2].lower()
    a = sys.argv[3:]

    def folder_name():
        return {r["folderid"]: r["name"] for r in db.execute("select folderid,name from folder")}

    if cmd == "stats":
        for q,label in [("select count(*) c from mail","messages"),
                        ("select count(*) c from part","mime parts"),
                        ("select count(*) c from folder","folders")]:
            print(f"{label:12}: {db.execute(q).fetchone()['c']:,}")
        r = db.execute("select min(date) a, max(date) b from mail").fetchone()
        print("date range  :", r["a"], "->", r["b"])
        print("total size  : %.1f GB" % ((db.execute("select sum(size) s from mail").fetchone()["s"] or 0)/1e9))

    elif cmd == "folders":
        mn = int(a[0]) if a else 1
        rows = db.execute("""select f.name, count(*) c from mail m
                             left join folder f on f.folderid=m.folderid
                             group by m.folderid having c>=? order by c desc""",(mn,)).fetchall()
        for r in rows: print(f"{r['c']:>8,}  {r['name']}")
        print(f"({len(rows)} folders with >= {mn})")

    elif cmd in ("fts","subject","from"):
        limit = int(a[1]) if len(a)>1 else 20
        fn = folder_name()
        if cmd=="fts":
            rows = db.execute("""select m.mailid,m.date,m.folderid,m.subject,m.fromorto
                                 from mail_fts x join mail m on m.mailid=x.rowid
                                 where mail_fts match ? order by m.date desc limit ?""",(a[0],limit)).fetchall()
        else:
            col = "subject" if cmd=="subject" else "fromorto"
            rows = db.execute(f"""select mailid,date,folderid,subject,fromorto from mail
                                  where {col} like ? order by date desc limit ?""",(f"%{a[0]}%",limit)).fetchall()
        for r in rows:
            print(f"[{r['mailid']}] {str(r['date'])[:19]}  {fn.get(r['folderid'],'?')}")
            print(f"      from/to: {r['fromorto']}")
            print(f"      subject: {r['subject']}")

    elif cmd == "year":
        limit = int(a[1]) if len(a)>1 else 20
        fn = folder_name()
        rows = db.execute("""select mailid,date,folderid,subject,fromorto from mail
                             where date like ? order by date limit ?""",(f"{a[0]}%",limit)).fetchall()
        for r in rows:
            print(f"[{r['mailid']}] {str(r['date'])[:19]}  {r['fromorto']}  |  {r['subject']}")

    elif cmd == "parts":
        rows = db.execute("""select position,parentid,content_container,content_entry,content_is_decoded,
                             content_hash,plaintext_container,plaintext_entry,header_container,header_entry
                             from part where mailid=? order by position""",(int(a[0]),)).fetchall()
        print(f"parts for mail {a[0]}:")
        for r in rows:
            print(f"  pos {r['position']} parent {r['parentid']}  "
                  f"content=({r['content_container']},{r['content_entry']}) dec={r['content_is_decoded']}  "
                  f"plaintext=({r['plaintext_container']},{r['plaintext_entry']})  "
                  f"header=({r['header_container']},{r['header_entry']})")
        print("  (container,entry) point into Data\\<container>.dat")

    else:
        print("unknown command:", cmd); print(__doc__)

if __name__ == "__main__":
    main()
