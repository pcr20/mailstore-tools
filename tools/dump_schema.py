import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pylib"))
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

def log(*a):
    print(*a); sys.stdout.flush()

fbclient = sys.argv[1]
dbs = sys.argv[2:]
os.environ["FIREBIRD"] = os.path.dirname(fbclient)

log("=== MailStore Firebird schema dump ===")
log("fbclient :", fbclient)
log("python   :", sys.version.split()[0], "(64-bit)" if sys.maxsize > 2**32 else "(32-bit)")

from firebird.driver import connect, driver_config
driver_config.fb_client_library.value = fbclient

TYPE = {7:"SMALLINT",8:"INTEGER",10:"FLOAT",12:"DATE",13:"TIME",14:"CHAR",
        16:"BIGINT/NUMERIC",23:"BOOLEAN",27:"DOUBLE",35:"TIMESTAMP",
        37:"VARCHAR",261:"BLOB",40:"CSTRING"}
combos = [("SYSDBA","masterkey"),("SYSDBA",""),("SYSDBA",None),(None,None)]

def attach(db):
    for user, pw in combos:
        try:
            kw = dict(charset="UTF8", no_db_triggers=True)
            if user is not None: kw["user"] = user
            if pw is not None: kw["password"] = pw
            con = connect(db, **kw)
            log("  CONNECTED user=%r pw=%r" % (user, pw))
            return con
        except Exception as e:
            log("  fail user=%r pw=%r -> %s" % (user, pw, str(e).replace(chr(10)," ")[:160]))
    return None

for db in dbs:
    log("\n" + "="*70)
    log("DATABASE:", db)
    con = attach(db)
    if not con:
        log("  *** could not attach ***"); continue
    cur = con.cursor()
    def q(sql): cur.execute(sql); return cur.fetchall()
    try:
        log("  engine:", q("select rdb$get_context('SYSTEM','ENGINE_VERSION') from rdb$database")[0][0])
    except Exception as e: log("  engine ver err:", e)

    tabs = q("""select trim(rdb$relation_name),
                       case when rdb$view_blr is not null then 1 else 0 end
                from rdb$relations where coalesce(rdb$system_flag,0)=0 order by 1""")
    log("\n  USER TABLES/VIEWS (%d):" % len(tabs))
    for name, isview in tabs:
        log("    %-42s %s" % (name, "VIEW" if isview else "table"))

    cols = q("""select trim(rf.rdb$relation_name), rf.rdb$field_position, trim(rf.rdb$field_name),
                       f.rdb$field_type, f.rdb$field_sub_type, f.rdb$character_length, rf.rdb$null_flag
                from rdb$relation_fields rf
                join rdb$fields f on rf.rdb$field_source=f.rdb$field_name
                join rdb$relations r on r.rdb$relation_name=rf.rdb$relation_name
                where coalesce(r.rdb$system_flag,0)=0
                order by rf.rdb$relation_name, rf.rdb$field_position""")
    cur_t=None
    log("\n  COLUMNS:")
    for tbl,pos,col,ft,fst,clen,nn in cols:
        if tbl!=cur_t: log("\n    [%s]"%tbl); cur_t=tbl
        t=TYPE.get(ft,"t%s"%ft)
        if ft in (14,37,40) and clen: t="%s(%s)"%(t,clen)
        if ft==261: t="BLOB(sub %s)"%fst
        log("      %2d %-30s %-16s %s"%(pos,col,t,"NOT NULL" if nn else ""))

    log("\n  ROW COUNTS:")
    for name, isview in tabs:
        if isview: continue
        try: log("    %-42s %s"%(name, q('select count(*) from "%s"'%name)[0][0]))
        except Exception as e: log("    %-42s count err: %s"%(name,str(e)[:60]))
    con.close()

log("\n=== DONE ===")
