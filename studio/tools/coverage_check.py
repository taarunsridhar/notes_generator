"""Check a subject's content against every extracted source: what is not yet taught, per source and per page.

usage: python _studio/tools/coverage_check.py <code>
needs  _studio/cache/<code>/ from extract.py
reads  <code>/content/**/*.yaml (all text) + each lesson's / item's `source(s)` fields
writes _studio/cache/<code>/coverage_report.md:
  1. ledger draft: one row per source with the share of its text pages taught -> ✓ (>= 90%) / partial / ✗ (< 30%),
     and whether any content `source:` cites it (past papers and cases must be cited). Paste-ready for info.yaml.
  2. reading / book terms (markdown **bold**) and headings not found in content;
  3. every page whose distinctive words are mostly absent (< 60% found).
A miss is a prompt to look, not proof of a gap: an idea may be taught under another name. Image-only pages
can't be scored; they are listed so they get looked at.
"""
import glob, json, os, re, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STOP = set("the a an and or of to in for on with by is are be as at this that it from your you we our their its not how what why when which who can will do does into than more most about these those there have has was were been all any each other such also may should session slide page".split())


def words(s):
    return [w for w in re.findall(r"[a-z][a-z\-]{3,}", s.lower()) if w not in STOP]


def cited(data):
    out = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("source", "sources"):
                    out.extend(v if isinstance(v, list) else [v])
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    return " ".join(str(s) for s in out).lower()


def main(code):
    cache = os.path.join(ROOT, "_studio", "cache", code)
    if not os.path.exists(os.path.join(cache, "inventory.json")):
        raise SystemExit("run: python _studio/tools/extract.py %s" % code)
    docs = [yaml.safe_load(open(f, encoding="utf8")) for f in glob.glob(os.path.join(ROOT, code, "content", "**", "*.yaml"), recursive=True)]
    content = re.sub(r"\s+", " ", json.dumps(docs, ensure_ascii=False).lower())
    cw, cites = set(words(content)), cited(docs)
    inv = json.load(open(os.path.join(cache, "inventory.json"), encoding="utf8"))
    ledger, pages_rep = [], []
    for r in inv:
        if not r["pages"]:
            ledger.append((r["path"], "–", "listed only (%s)" % r["type"], "")); continue
        name = os.path.splitext(os.path.basename(r["path"]))[0]
        text = open(os.path.join(cache, "text", name + ".txt"), encoding="utf8").read()
        pages = re.split(r"\n--- p\d+\n", text)[1:]
        scored = hit = 0
        misses = []
        for i, t in enumerate(pages, 1):
            ws = set(words(t))
            if len(ws) < 8:
                continue
            scored += 1
            f = len(ws & cw) / len(ws)
            if f >= 0.6:
                hit += 1
            elif r["pages"] <= 150:
                misses.append("  - p%d (%.0f%%): %s" % (i, f * 100, re.sub(r"\s+", " ", t)[:150]))
        share = hit / scored if scored else 0
        stem = re.sub(r"-(solutions|graded|key|template|solution)$", "", name.lower())
        key = re.sub(r"^(paper|ref|ps\d*|r\d+|s\d+|tj\d+|c\d+)-?", "", stem)
        is_cited = stem in cites or (len(key) > 3 and key in cites) or any(tok in cites for tok in re.findall(r"(?:jd|tj|c|s|r)\d{2}\b|ps\d+\b", stem))
        mark = "✓" if share >= 0.9 else "✗" if share < 0.3 else "partial"
        need_cite = r["folder"] in ("past-papers", "cases", "problem-sets")
        ledger.append((r["path"], "%d/%d" % (hit, scored) if scored else "image-only: %d pages" % r["pages"],
                       ("image-only, look at the PNGs" if not scored else "%s %.0f%%" % (mark, share * 100)),
                       ("cited" if is_cited else ("**NOT cited**" if need_cite else ""))))
        if misses:
            pages_rep.append("\n### %s\n%s" % (r["path"], "\n".join(misses)))
    rep = ["# Coverage check: %s\n" % code, "## 1. Ledger draft (pages taught / pages with text)\n",
           "| source | pages | taught | cited in content |", "|---|---|---|---|"]
    rep += ["| %s | %s | %s | %s |" % row for row in ledger]
    ri = os.path.join(cache, "readings_index.json")
    if os.path.exists(ri):
        rep.append("\n## 2. Reading and book terms not found\n")
        for f, v in json.load(open(ri, encoding="utf8")).items():
            miss = [t for t in v["terms"] if t.lower() not in content]
            hmiss = [h for h in v["headings"] if len(words(h)) >= 2 and not set(words(h)) <= cw]
            rep.append("**%s**: %d/%d terms found. Missing: %s" % (f, len(v["terms"]) - len(miss), len(v["terms"]), " · ".join(miss) or "none"))
            if hmiss and not v["terms"]:
                rep.append("  headings with unseen words (%d): %s" % (len(hmiss), " · ".join(hmiss[:60])))
    rep.append("\n## 3. Pages mostly not taught (< 60% of distinctive words found)")
    rep += pages_rep or ["none"]
    out = os.path.join(cache, "coverage_report.md")
    open(out, "w", encoding="utf8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:len(ledger) + 4]))
    print("... full report ->", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main(sys.argv[1])
