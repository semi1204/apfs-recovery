# Mac side: hash a reproducible sample of the recovered copy, for cross-checking the Windows extraction.
# Output sample_hashes.json = {"files": {path: sha256}, "chunks": {path: {offset: sha256}}}
import os, json, random, hashlib
R = "/Volumes/Recovered/CrawlVMs"
rows = [r for r in json.load(open("out/tree.json")) if r["type"] == "file" and not r["path"].startswith((".Spotlight-V100", ".fseventsd"))]
def local(p): return os.path.join(R, "_Trashes" + p[len(".Trashes"):] if p.startswith(".Trashes") else p)
random.seed(2026)
small = [r for r in rows if 0 < r["size"] <= 20 << 20]
pick = random.sample(small, 3000)
must = [r for r in rows if r["path"].endswith(("NOTE.MD", "Manifest.db", "Info.plist", "config.pvs", ".patch", ".bundle"))]
out = {"files": {}, "chunks": {}}
for r in pick + must:
    out["files"][r["path"]] = hashlib.sha256(open(local(r["path"]), "rb").read()).hexdigest()
big = sorted((r for r in rows if r["size"] > 500 << 20), key=lambda r: -r["size"])[:12]
for r in big:
    offs = sorted({0, (r["size"] - 1) // (1 << 20) * (1 << 20)} | {random.randrange(0, r["size"]) // (1 << 20) * (1 << 20) for _ in range(40)})
    with open(local(r["path"]), "rb") as f:
        out["chunks"][r["path"]] = {str(o): (f.seek(o), hashlib.sha256(f.read(1 << 20)).hexdigest())[1] for o in offs}
json.dump(out, open("sample_hashes.json", "w"))
print(f"files hashed: {len(out['files'])}, big files chunk-hashed: {len(out['chunks'])} "
      f"({sum(len(v) for v in out['chunks'].values())} chunks)")
