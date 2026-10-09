# Read-only: scan the old APFS container for FS-tree leaf records and volume superblocks -> SQLite.
# usage: scan.py /dev/rdiskN out.db LO_GiB HI_GiB
import os, sys, struct, sqlite3, time
DEV, OUT = sys.argv[1], sys.argv[2]
LO, HI = float(sys.argv[3]), float(sys.argv[4])
START = int(os.environ.get("START_LBA", 409640)) * 512; BS = 4096; CH = 2048; M = 0xFFFFFFFF

def fl64(blk):
    w = memoryview(blk).cast("I")[2:]; n = len(w)
    s1 = sum(w) % M
    s2 = sum((n - i) * x for i, x in enumerate(w)) % M
    c1 = M - (s1 + s2) % M; c2 = M - (s1 + c1) % M
    return c2 << 32 | c1

def ok(blk): return fl64(blk) == struct.unpack_from("<Q", blk)[0]

if __name__ == "__main__":
    db = sqlite3.connect(OUT)
    db.executescript("""
    create table if not exists node(pblk integer primary key, oid integer, xid integer, level integer);
    create table if not exists rec(pblk integer, xid integer, typ integer, id integer, k blob, v blob);
    create table if not exists apsb(pblk integer primary key, xid integer, blk blob);
    """)
    fd = os.open(DEV, os.O_RDONLY)
    b0, b1 = int(LO * 2**30) // BS, int(HI * 2**30) // BS
    t0 = time.time()
    for base in range(b0, b1, CH):
        buf = os.pread(fd, CH * BS, START + base * BS)
        mv = memoryview(buf).cast("I")
        ty, st = mv[6::1024].tolist(), mv[7::1024].tolist()
        for j, t in enumerate(ty):
            if t == 0xd and buf[j * BS + 32:j * BS + 36] == b"APSB": kind = "apsb"
            elif t in (2, 3) and st[j] == 0xe: kind = "fs"
            else: continue
            blk = buf[j * BS:(j + 1) * BS]
            if not ok(blk): continue
            pblk = base + j
            oid, xid = struct.unpack_from("<QQ", blk, 8)
            if kind == "apsb":
                db.execute("insert or replace into apsb values(?,?,?)", (pblk, xid, blk)); continue
            flags, level, nkeys = struct.unpack_from("<HHI", blk, 32)
            db.execute("insert or replace into node values(?,?,?,?)", (pblk, oid, xid, level))
            if level: continue
            toff, tlen = struct.unpack_from("<HH", blk, 40)
            kbase = 56 + toff + tlen; vend = BS - (40 if flags & 1 else 0)
            for i in range(nkeys):
                ko, kl, vo, vl = struct.unpack_from("<HHHH", blk, 56 + toff + 8 * i)
                k = blk[kbase + ko:kbase + ko + kl]
                v = blk[vend - vo:vend - vo + vl] if vo != 0xFFFF else b""
                h = struct.unpack_from("<Q", k)[0]
                db.execute("insert into rec values(?,?,?,?,?,?)", (pblk, xid, h >> 60, h & (1 << 60) - 1, k[8:], v))
        if (base - b0) // CH % 128 == 0:
            db.commit(); el = time.time() - t0
            print(f"{base * BS / 2**30:.1f}GiB {(base - b0) * BS / el / 1e6 if el else 0:.0f}MB/s", flush=True)
    db.commit()
    print(f"done {time.time() - t0:.0f}s", flush=True)
