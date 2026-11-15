import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pylib"))
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

def log(*a):
    print(*a); sys.stdout.flush()

fbclient = sys.argv[1]
fg_db    = sys.argv[2]        # MailStoreFileGroup.fdb (copy, with its .key beside it)
out_db   = sys.argv[3]        # output sqlite path
os.environ["FIREBIRD"] = os.path.dirname(fbclient)

log("=== MailStore index build ===")
log("fbclient:", fbclient)
log("source  :", fg_db)
log("output  :", out_db)
log("python  :", sys.version.split()[0])

from firebird.driver import connect, driver_config
driver_config.fb_client_library.value = fbclient

def tostr(v):
    if v is None: return None
    if hasattr(v, "read"): v = v.read()
    if isinstance(v, (bytes, bytearray)):
        b = bytes(v)
        for enc in ("utf-8", "utf-16-le", "latin-1"):
            try: return b.decode(enc)
            except Exception: pass
        return b.hex()
    return str(v)

def dt(v):
    if v is None: return None
    if isinstance(v, (datetime.datetime, datetime.date)): return v.isoformat(sep=" ")
    return str(v)

con = connect(fg_db, user="SYSDBA", password="masterkey", charset="UTF8", no_db_triggers=True)
log("connected; engine", con.info.engine_version)
cur = con.cursor()

if os.path.exists(out_db): os.remove(out_db)
db = sqlite3.connect(out_db)
db.executescript("""
PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
CREATE TABLE folder(folderid INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE mail(mailid INTEGER PRIMARY KEY, folderid INTEGER, messageid TEXT,
  date TEXT, arcdate TEXT, flags INTEGER, size INTEGER, subject TEXT, fromorto TEXT);
CREATE TABLE part(mimeentityid INTEGER PRIMARY KEY, mailid INTEGER, parentid INTEGER, position INTEGER,
  content_container INTEGER, content_entry INTEGER, content_is_decoded INTEGER, content_hash TEXT,
  plaintext_container INTEGER, plaintext_entry INTEGER,
  header_container INTEGER, header_entry INTEGER, header_hash TEXT);
""")

# --- folders ---
cur.execute('select "FOLDERID", "NAME" from "FOLDER"')
frows = [(r[0], tostr(r[1])) for r in cur.fetchall()]
db.executemany("insert into folder values(?,?)", frows)
log("folders:", len(frows))

# --- mail ---
cur.execute('''select "MAILID","FOLDERID","MESSAGEID","DATE","ARCDATE","FLAGS","SIZE",
                      "DISPLAYSUBJECT","DISPLAYFROMORTO" from "MAIL"''')
n = 0
while True:
    batch = cur.fetchmany(20000)
    if not batch: break
    db.executemany("insert into mail values(?,?,?,?,?,?,?,?,?)",
        [(r[0], r[1], tostr(r[2]), dt(r[3]), dt(r[4]), r[5], r[6], tostr(r[7]), tostr(r[8])) for r in batch])
    n += len(batch);
    if n % 100000 == 0: log("  mail", n)
db.commit()
log("mail:", n)

# --- parts (the file index: pointers into the .dat containers) ---
cur.execute('''select "MIMEENTITYID","MAILID","PARENTMIMEENTITYID","POSITION",
                      "CONTENTCONTAINER","CONTENTENTRY","CONTENTISDECODED","CONTENTHASH",
                      "PLAINTEXTCONTAINER","PLAINTEXTENTRY",
                      "HEADERCONTAINER","HEADERENTRY","HEADERHASH" from "MIMEENTITY"''')
m = 0
while True:
    batch = cur.fetchmany(20000)
    if not batch: break
    db.executemany("insert into part values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r[0],r[1],r[2],r[3],r[4],r[5],r[6],tostr(r[7]),r[8],r[9],r[10],r[11],tostr(r[12])) for r in batch])
    m += len(batch)
    if m % 200000 == 0: log("  part", m)
db.commit()
log("part:", m)

con.close()

# --- indexes + FTS over subject/from-or-to ---
log("building indexes + FTS ...")
db.executescript("""
CREATE INDEX mail_folder ON mail(folderid);
CREATE INDEX mail_date   ON mail(date);
CREATE INDEX part_mail   ON part(mailid);
CREATE INDEX part_cc     ON part(content_container, content_entry);
CREATE VIRTUAL TABLE mail_fts USING fts5(subject, fromorto, content='mail', content_rowid='mailid');
INSERT INTO mail_fts(rowid, subject, fromorto) SELECT mailid, subject, fromorto FROM mail;
""")
db.commit()
db.execute("VACUUM")
db.commit()
db.close()

sz = os.path.getsize(out_db)
log("INDEX DONE  mail=%d part=%d folders=%d  db_bytes=%d (%.1f MB)" % (n, m, len(frows), sz, sz/1e6))
