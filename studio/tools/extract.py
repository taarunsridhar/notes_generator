"""Extract every source of a subject into text Claude can read, render the pages it can't, and keep an inventory.

usage: python _studio/tools/extract.py <code> [--render=S03,S04]
       --render=<name parts>  also render EVERY page of the sources whose file name contains one of the parts
                              (annotated class decks: handwriting is embedded as images, so the low-text rule misses it)
reads  <code>/source/** (everything except inbox/ and _superseded/): pdf, pptx, docx, md, txt, xlsx/csv (listed only), images (listed)
writes _studio/cache/<code>/
         inventory.json / inventory.md   every source: folder, type, pages, words, low-text pages, changed since last run
         text/<name>.txt                 full text per source, one "--- p<N>" marker per page / slide
         compact.txt                     one line per page, every source except books (> BOOK_PAGES pages): [<tag> p<N>] text
         pages/<name>_p<N>.png           pages with < MIN_WORDS words (image-only slides, scans, handwriting): LOOK at them
         readings_index.json             per reading / book: headings + key terms (markdown **bold**; PDF title-case lines)
A fully scanned PDF gets every page rendered (capped at MAX_RENDER), so a scan is never silently skipped.
"""
import glob, hashlib, json, os, re, sys, zipfile
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_WORDS = 25
BOOK_PAGES = 150
MAX_RENDER = 120
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def clean(t):
    t = re.sub(r"[ \t]+", " ", t or "").strip()
    return re.sub(r"\n\s*\n+", "\n", t)


def xml_text(x, para_tag):
    x = re.sub(r"</%s>" % para_tag, "\n", x)
    return re.sub(r"<[^>]+>", "", x).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")


def read_pages(f):
    """-> list of page texts (None for binary types we only list), pdf document or None"""
    ext = f.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        import fitz
        d = fitz.open(f)
        return [clean(p.get_text()) for p in d], d
    if ext == "pptx":
        z = zipfile.ZipFile(f)
        names = sorted([n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)], key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for n in names:
            t = clean(xml_text(z.read(n).decode("utf8", "ignore"), "a:p"))
            nn = n.replace("slides/slide", "notesSlides/notesSlide")
            if nn in z.namelist():
                note = clean(xml_text(z.read(nn).decode("utf8", "ignore"), "a:p"))
                if len(note.split()) > 3:
                    t += "\n[speaker notes] " + note
            out.append(t)
        return out, None
    if ext == "docx":
        x = zipfile.ZipFile(f).read("word/document.xml").decode("utf8", "ignore")
        return [clean(xml_text(x, "w:p"))], None
    if ext in ("md", "txt"):
        return [open(f, encoding="utf8", errors="ignore").read()], None
    return None, None


def md_index(t):
    heads = [h.strip() for h in re.findall(r"^#{1,4}\s+(.+)$", t, re.M)]
    terms = []
    for x in re.findall(r"\*\*([^*]{2,60})\*\*", t):
        x = x.strip(" :.").strip()
        if x and x.lower() not in [y.lower() for y in terms]:
            terms.append(x)
    return heads, terms


def main(code, render=()):
    src = os.path.join(ROOT, code, "source")
    out = os.path.join(ROOT, "_studio", "cache", code)
    for d in ("text", "pages"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    old = {}
    if os.path.exists(os.path.join(out, "inventory.json")):
        old = {r["path"]: r for r in json.load(open(os.path.join(out, "inventory.json"), encoding="utf8"))}
    inv, compact, rindex, rendered = [], [], {}, 0
    files = sorted(f for f in glob.glob(os.path.join(src, "**", "*"), recursive=True)
                   if os.path.isfile(f) and os.sep + "inbox" + os.sep not in f and os.sep + "_superseded" + os.sep not in f
                   and not os.path.basename(f).startswith("."))
    for f in files:
        rel = os.path.relpath(f, os.path.join(ROOT, code)).replace("\\", "/")
        folder = rel.split("/")[1] if rel.count("/") > 1 else "ref"
        name = os.path.splitext(os.path.basename(f))[0]
        sha = hashlib.sha1(open(f, "rb").read()).hexdigest()[:12]
        row = {"path": rel, "folder": folder, "type": f.rsplit(".", 1)[-1].lower(), "sha": sha,
               "status": "new" if rel not in old else ("changed" if old[rel]["sha"] != sha else "")}
        pages, doc = read_pages(f)
        if pages is None:
            row.update(pages=0, words=0, low_text=[])
            inv.append(row); continue
        low = [i for i, t in enumerate(pages, 1) if len(t.split()) < MIN_WORDS]
        row.update(pages=len(pages), words=sum(len(t.split()) for t in pages), low_text=low)
        with open(os.path.join(out, "text", name + ".txt"), "w", encoding="utf8") as fh:
            for i, t in enumerate(pages, 1):
                fh.write("\n--- p%d\n%s\n" % (i, t))
        book = len(pages) > BOOK_PAGES
        if not book and row["type"] != "md":
            compact.append("\n=== %s (%d pages)" % (rel, len(pages)))
            for i, t in enumerate(pages, 1):
                compact.append("[%s p%d] %s" % (name, i, t.replace("\n", " | ")))
        want = list(range(1, len(pages) + 1)) if any(r and r in name for r in render) else low
        if doc is not None and want:
            scanned = len(low) == len(pages)
            for i in want[:MAX_RENDER]:
                png = os.path.join(out, "pages", "%s_p%d.png" % (name, i))
                if not os.path.exists(png) or row["status"]:
                    doc[i - 1].get_pixmap(dpi=90 if scanned or folder != "slides" else 60).save(png)
                    rendered += 1
        if folder == "readings" or book or row["type"] == "md":
            full = "\n".join(pages)
            if row["type"] == "md":
                h, t = md_index(full)
            else:
                h = [l.strip() for l in full.splitlines() if 3 < len(l.strip()) < 70 and re.match(r"^(\d+(\.\d+)*\s+)?[A-Z][A-Za-z,:'&\- ]+$", l.strip()) and l.strip().istitle()]
                h = list(dict.fromkeys(h))[:600]
                t = []
            rindex[rel] = {"headings": h, "terms": t}
        inv.append(row)
    gone = [p for p in old if p not in {r["path"] for r in inv}]
    json.dump(inv, open(os.path.join(out, "inventory.json"), "w", encoding="utf8"), indent=1, ensure_ascii=False)
    json.dump(rindex, open(os.path.join(out, "readings_index.json"), "w", encoding="utf8"), indent=1, ensure_ascii=False)
    open(os.path.join(out, "compact.txt"), "w", encoding="utf8").write("\n".join(compact))
    md = ["# Source inventory: %s\n" % code, "| source | type | pages | words | low-text pages (rendered) | since last run |", "|---|---|---|---|---|---|"]
    for r in inv:
        lt = r["low_text"]
        lts = ("all %d (scan?)" % len(lt)) if lt and len(lt) == r["pages"] else (", ".join(map(str, lt[:12])) + (" …" if len(lt) > 12 else ""))
        md.append("| %s | %s | %s | %s | %s | %s |" % (r["path"], r["type"], r["pages"] or "–", r["words"] or "–", lts or "–", r["status"] or ""))
    if gone:
        md.append("\nRemoved since last run: " + ", ".join(gone))
    inbox = [os.path.basename(p) for p in glob.glob(os.path.join(src, "inbox", "*")) if not os.path.basename(p).startswith(".")]
    if inbox:
        md.append("\n**Unfiled in inbox:** " + ", ".join(inbox))
    open(os.path.join(out, "inventory.md"), "w", encoding="utf8").write("\n".join(md) + "\n")
    new = [r["path"] for r in inv if r["status"]]
    print("%s: %d sources, %d pages, %d page images rendered, %d new/changed%s -> %s" % (
        code, len(inv), sum(r["pages"] for r in inv), rendered, len(new),
        (" (" + ", ".join(new[:8]) + (" …" if len(new) > 8 else "") + ")") if new and old else "", os.path.relpath(out, ROOT)))
    if inbox:
        print("  unfiled in inbox:", ", ".join(inbox))
    scans = [r["path"] for r in inv if r["pages"] and len(r["low_text"]) == r["pages"]]
    if scans:
        print("  image-only (read the PNGs):", ", ".join(scans))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    render = [x for a in sys.argv[1:] if a.startswith("--render=") for x in a.split("=", 1)[1].split(",")]
    for c in args or [os.path.basename(os.path.dirname(os.path.dirname(p))) for p in glob.glob(os.path.join(ROOT, "*", "source", "inbox"))]:
        main(c, render)
