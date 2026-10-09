# Windows side: compare the Windows extraction against the Mac sample hashes + check every file's size.
# usage: python compare_win.py tree.json sample_hashes.json C:\SSD-Recovery\CrawlVMs
import os, sys, json, hashlib, unicodedata
tree, samp, dest = sys.argv[1:4]
BADCH = dict.fromkeys(map(ord, '<>:"\\|?*'), "_") | {i: "_" for i in range(32)}
def winpath(p):
    if p.startswith(".Trashes"): p = "_Trashes" + p[len(".Trashes"):]
    parts = [unicodedata.normalize("NFC", s).translate(BADCH).rstrip(" .") or "_" for s in p.split("/")]
    return "\\\\?\\" + os.path.join(os.path.abspath(dest), *parts)
rows = [r for r in json.load(open(tree, encoding="utf-8")) if r["type"] == "file" and not r["path"].startswith((".Spotlight-V100", ".fseventsd"))]
missing = [r["path"] for r in rows if not os.path.exists(winpath(r["path"]))]
wrong = [r["path"] for r in rows if os.path.exists(winpath(r["path"])) and os.path.getsize(winpath(r["path"])) != r["size"]]
print(f"files expected {len(rows)} | missing {len(missing)} | size mismatch {len(wrong)}")
s = json.load(open(samp, encoding="utf-8"))
fb = [p for p, hv in s["files"].items() if hashlib.sha256(open(winpath(p), "rb").read()).hexdigest() != hv]
print(f"sample full-file hashes: {len(s['files']) - len(fb)}/{len(s['files'])} match")
cb = 0; ct = 0
for p, offs in s["chunks"].items():
    with open(winpath(p), "rb") as f:
        for o, hv in offs.items():
            f.seek(int(o)); ct += 1
            if hashlib.sha256(f.read(1 << 20)).hexdigest() != hv: cb += 1
print(f"big-file chunk hashes: {ct - cb}/{ct} match")
for p in (missing + wrong + fb)[:10]: print("  PROBLEM:", p)
print("RESULT:", "ALL MATCH" if not (missing or wrong or fb or cb) else "MISMATCH - do NOT update firmware")
