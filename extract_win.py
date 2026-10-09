# Windows port of extract.py: read the old APFS area straight from the raw disk (read-only) using tree.json,
# write files under DEST, and record size + SHA-256 per file.
# usage (admin): python extract_win.py tree.json \\.\PhysicalDriveN C:\SSD-Recovery\CrawlVMs [path-prefix ...]
# Resumable: finished files are listed in DEST\.recovered_done ; hashes in DEST\.recovered_sha256.tsv
import os, sys, json, time, hashlib, unicodedata

START = 53248 * 512; BS = 4096; CH = 8 << 20
SKIP = (".Spotlight-V100", ".fseventsd")
BADCH = dict.fromkeys(map(ord, '<>:"\\|?*'), "_") | {i: "_" for i in range(32)}
tree, srcdev, dest = sys.argv[1], sys.argv[2], sys.argv[3]
order = sys.argv[4:] or [""]
rows = [r for r in json.load(open(tree, encoding="utf-8")) if not r["path"].startswith(SKIP)]

def winpath(p):
    if p.startswith(".Trashes"): p = "_Trashes" + p[len(".Trashes"):]
    parts = [unicodedata.normalize("NFC", s).translate(BADCH).rstrip(" .") or "_" for s in p.split("/")]
    return "\\\\?\\" + os.path.join(os.path.abspath(dest), *parts)

src = open(srcdev, "rb", buffering=0)
def pread(n, off):
    src.seek(off); out = bytearray()
    while len(out) < n:
        b = src.read(n - len(out))
        if not b: break
        out += b
    return bytes(out)

os.makedirs(dest, exist_ok=True)
donef = os.path.join(dest, ".recovered_done")
done = set(open(donef, encoding="utf-8").read().splitlines()) if os.path.exists(donef) else set()
dl = open(donef, "a", encoding="utf-8")
hl = open(os.path.join(dest, ".recovered_sha256.tsv"), "a", encoding="utf-8")
log = open(os.path.join(dest, ".recovered_errors.tsv"), "a", encoding="utf-8")

sel, seen = [], set()
for pre in order:
    for r in rows:
        if r["path"].startswith(pre) and r["id"] not in seen:
            sel.append(r); seen.add(r["id"])
total = sum(r["size"] for r in sel if r["type"] == "file" and r["path"] not in done)
print(f"{len(sel)} entries, {total / 1e9:.1f}GB to copy", flush=True)
for r in sel:
    if r["type"] == "dir": os.makedirs(winpath(r["path"]), exist_ok=True)

copied = 0; t0 = time.time(); last = 0
for r in sel:
    p = r["path"]
    if r["type"] == "dir" or p in done: continue
    dst = winpath(p); os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if r["type"] == "link":
            target = bytes.fromhex(r["xattrs"]["com.apple.fs.symlink"]["data"]).rstrip(b"\0").decode()
            with open(dst + ".symlink.txt", "w", encoding="utf-8") as f: f.write(target + "\n")
            hl.write(f"{p}\tLINK\t{target}\n")
        else:
            h = hashlib.sha256()
            with open(dst, "wb") as f:
                pos = 0
                for laddr, length, pblk in r["extents"]:
                    if not pblk or laddr >= r["size"]: continue
                    length = min(length, -(-(r["size"] - laddr) // BS) * BS)
                    for o in range(0, length, CH):
                        n = min(CH, length - o)
                        b = pread(n, START + pblk * BS + o)
                        if len(b) != n: raise IOError(f"short read at block {pblk}")
                        if laddr + o != pos:            # hole before this extent: hash the zeros too
                            h.update(bytes(laddr + o - pos)); pos = laddr + o
                        keep = b[:max(0, min(n, r["size"] - pos))]
                        f.seek(pos); f.write(b); h.update(keep); pos += len(keep)
                        copied += n
                        if time.time() - last > 30:
                            last = time.time(); el = last - t0; rate = copied / el
                            print(f"{copied / 1e9:7.1f}/{total / 1e9:.1f}GB {rate / 1e6:6.1f}MB/s "
                                  f"ETA {(total - copied) / rate / 60:5.0f}min  {p[:70]}", flush=True)
                f.truncate(r["size"])
                if pos < r["size"]: h.update(bytes(r["size"] - pos))
            if r["mtime"]: os.utime(dst, ns=(r["mtime"], r["mtime"]))
            hl.write(f"{p}\t{r['size']}\t{h.hexdigest()}\n")
        hl.flush(); dl.write(p + "\n"); dl.flush()
    except Exception as e:
        log.write(f"{p}\t{e}\n"); log.flush()
        print(f"ERROR {p}: {e}", flush=True)
print(f"done: {copied / 1e9:.1f}GB in {(time.time() - t0) / 60:.0f}min", flush=True)
