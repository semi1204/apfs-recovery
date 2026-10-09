# Copy files out of the old APFS area (read-only on the source) using the rebuilt tree.json.
# usage: extract.py tree.json DEST_DIR [path-prefix ...]   (prefixes = what to copy, in this order)
# Resumable: finished files are listed in DEST_DIR/.recovered_done
import os, sys, json, time

SRC = "/dev/rdisk4"; START = 53248 * 512; BS = 4096; CH = 8 << 20  # real CrawlVMs container start (old GPT)
SKIP = (".Spotlight-V100", ".fseventsd")
tree, dest = sys.argv[1], sys.argv[2]
order = sys.argv[3:] or [""]
rows = [r for r in json.load(open(tree)) if not r["path"].startswith(SKIP)]

def out(p):  # keep the old trash visible instead of a hidden .Trashes
    return os.path.join(dest, "_Trashes" + p[len(".Trashes"):] if p.startswith(".Trashes") else p)

src = os.open(SRC, os.O_RDONLY)
donef = os.path.join(dest, ".recovered_done")
done = set(open(donef).read().splitlines()) if os.path.exists(donef) else set()
log = open(os.path.join(dest, ".recovered_errors.tsv"), "a")
dl = open(donef, "a")

sel, seen = [], set()
for pre in order:
    for r in rows:
        if r["path"].startswith(pre) and r["id"] not in seen:
            sel.append(r); seen.add(r["id"])
total = sum(r["size"] for r in sel if r["type"] == "file" and r["path"] not in done)
print(f"{len(sel)} entries, {total / 1e9:.1f}GB to copy", flush=True)

for r in sel:
    if r["type"] == "dir": os.makedirs(out(r["path"]), exist_ok=True)

copied = 0; t0 = time.time(); last = 0
for r in sel:
    p = r["path"]
    if r["type"] == "dir" or p in done: continue
    dst = out(p); os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if r["type"] == "link":
            target = bytes.fromhex(r["xattrs"]["com.apple.fs.symlink"]["data"]).rstrip(b"\0").decode()
            if os.path.lexists(dst): os.remove(dst)
            os.symlink(target, dst)
        else:
            with open(dst, "wb") as f:
                for laddr, length, pblk in r["extents"]:
                    if not pblk or laddr >= r["size"]: continue   # hole / beyond EOF
                    length = min(length, -(-(r["size"] - laddr) // BS) * BS)
                    for o in range(0, length, CH):
                        n = min(CH, length - o)
                        b = os.pread(src, n, START + pblk * BS + o)
                        if len(b) != n: raise IOError(f"short read at block {pblk}")
                        f.seek(laddr + o); f.write(b)
                        copied += n
                        if time.time() - last > 30:
                            last = time.time(); el = last - t0; rate = copied / el
                            print(f"{copied / 1e9:7.1f}/{total / 1e9:.1f}GB {rate / 1e6:5.1f}MB/s "
                                  f"ETA {(total - copied) / rate / 60:5.0f}min  {p[:80]}", flush=True)
                f.truncate(r["size"])
            if r["mtime"]: os.utime(dst, ns=(r["mtime"], r["mtime"]))
        dl.write(p + "\n"); dl.flush()
    except Exception as e:
        log.write(f"{p}\t{e}\n"); log.flush()
        print(f"ERROR {p}: {e}", flush=True)
print(f"done: {copied / 1e9:.1f}GB in {(time.time() - t0) / 60:.0f}min", flush=True)
