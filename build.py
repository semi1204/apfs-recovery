# Rebuild the CrawlVMs file tree from scanned FS-tree records (apfs.db) -> tree.json + listing.tsv
# usage: build.py apfs.db outdir
import sqlite3, struct, sys, json, os, collections

DB, OUT = sys.argv[1], sys.argv[2]
BS = 4096
INODE, XATTR, EXTENT, DREC = 3, 4, 8, 9
DT_DIR, DT_REG, DT_LNK = 4, 8, 10
ROOT = 2
db = sqlite3.connect(DB)

def latest(typ):
    # one row per (id, key-rest): the version with the highest xid (SQLite bare-column max semantics)
    return db.execute("select id, k, v, max(xid) from rec where typ=? group by id, k", (typ,))

def xfields(blob):
    out = {}
    if len(blob) < 4: return out
    n, _ = struct.unpack_from("<HH", blob, 0)
    data = 4 + 4 * n
    for i in range(n):
        t, _, sz = struct.unpack_from("<BBH", blob, 4 + 4 * i)
        out[t] = blob[data:data + sz]
        data += (sz + 7) & ~7
    return out

inodes = {}
for id_, k, v, xid in latest(INODE):
    parent, private, ctime, mtime = struct.unpack_from("<QQQQ", v, 0)
    bsd_flags, = struct.unpack_from("<I", v, 68)
    mode, = struct.unpack_from("<H", v, 80)
    xf = xfields(v[92:])
    size = struct.unpack_from("<Q", xf[8])[0] if 8 in xf else 0
    name = xf[4].split(b"\0")[0].decode("utf-8", "replace") if 4 in xf else None
    inodes[id_] = dict(parent=parent, private=private, mtime=mtime, mode=mode, size=size,
                       name=name, compressed=bool(bsd_flags & 0x20), xid=xid)

# directory entries: several stale versions may name the same file; keep the newest
drec = {}
for id_, k, v, xid in latest(DREC):
    nl_h, = struct.unpack_from("<I", k, 0)
    if 4 + (nl_h & 0x3FF) == len(k): name = k[4:]
    else: name = k[2:2 + struct.unpack_from("<H", k, 0)[0]]
    name = name.split(b"\0")[0].decode("utf-8", "replace")
    fid, _, flags = struct.unpack_from("<QQH", v, 0)
    cand = (xid, id_, name, flags & 0xF)
    ino = inodes.get(fid)
    # prefer the entry that agrees with the inode's own parent pointer
    score = (ino is not None and ino["parent"] == id_, xid)
    if fid not in drec or score > drec[fid][0]: drec[fid] = (score, cand)

extents = collections.defaultdict(list)
for id_, k, v, xid in latest(EXTENT):
    laddr, = struct.unpack_from("<Q", k, 0)
    lf, pblk = struct.unpack_from("<QQ", v, 0)
    extents[id_].append((laddr, lf & ((1 << 56) - 1), pblk))

xattrs = collections.defaultdict(dict)
for id_, k, v, xid in latest(XATTR):
    nl, = struct.unpack_from("<H", k, 0)
    name = k[2:2 + nl].split(b"\0")[0].decode("utf-8", "replace")
    flags, dlen = struct.unpack_from("<HH", v, 0)
    data = v[4:4 + dlen]
    if flags & 1:  # XATTR_DATA_STREAM: data lives in its own extents
        sid, ssize = struct.unpack_from("<QQ", data, 0)
        xattrs[id_][name] = {"stream": sid, "size": ssize}
    else:
        xattrs[id_][name] = {"data": data.hex()}

def entry(fid):
    if fid in drec:
        _, (xid, parent, name, dtype) = drec[fid]
        return parent, name, dtype
    ino = inodes.get(fid)
    if ino and ino["name"]:
        return ino["parent"], ino["name"], DT_DIR if ino["mode"] & 0o170000 == 0o040000 else DT_REG
    return None

def path(fid, seen=()):
    if fid == ROOT: return ""
    e = entry(fid)
    if e is None or fid in seen: return f"_orphans/dir_{fid}"
    parent, name, _ = e
    p = path(parent, seen + (fid,))
    return f"{p}/{name}" if p else name

ids = set(drec) | {i for i, n in inodes.items() if n["name"]}
rows = []
for fid in ids:
    e = entry(fid)
    if e is None: continue
    _, name, dtype = e
    ino = inodes.get(fid, {})
    ex = sorted(extents.get(ino.get("private", fid), []))
    xa = {}
    for n, x in xattrs.get(fid, {}).items():
        if n in ("com.apple.decmpfs", "com.apple.ResourceFork", "com.apple.fs.symlink"):
            xa[n] = dict(x, extents=sorted(extents.get(x["stream"], []))) if "stream" in x else x
    rows.append(dict(id=fid, path=path(fid), type={DT_DIR: "dir", DT_REG: "file", DT_LNK: "link"}.get(dtype, str(dtype)),
                     size=ino.get("size", 0), has_inode=bool(ino), compressed=ino.get("compressed", False),
                     extents=ex, mtime=ino.get("mtime", 0), xattrs=xa))
rows.sort(key=lambda r: r["path"])
os.makedirs(OUT, exist_ok=True)
with open(f"{OUT}/tree.json", "w") as f: json.dump(rows, f)
with open(f"{OUT}/listing.tsv", "w") as f:
    for r in rows:
        mapped = sum(l for _, l, p in r["extents"] if p)
        f.write(f"{r['type']}\t{r['size']}\t{mapped}\t{len(r['extents'])}\t{int(r['has_inode'])}\t{int(r['compressed'])}\t{r['path']}\n")
files = [r for r in rows if r["type"] == "file"]
print(f"inodes={len(inodes)} drecs={len(drec)} extent-owners={len(extents)} entries={len(rows)} "
      f"dirs={sum(r['type']=='dir' for r in rows)} files={len(files)} "
      f"files_with_inode={sum(r['has_inode'] for r in files)} files_with_extents={sum(bool(r['extents']) for r in files)} "
      f"orphans={sum(r['path'].startswith('_orphans') for r in rows)} "
      f"total_file_bytes={sum(r['size'] for r in files)/1e9:.1f}GB compressed={sum(r['compressed'] for r in files)}")
