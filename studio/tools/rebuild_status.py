"""Where is a subject's rebuild? Run this first in any "continue building <code>" session.

usage: python _studio/tools/rebuild_status.py <code>
reads  <code>/content/subject.yaml (modules + planned lesson ids in the comments under each module),
       <code>/content/lessons/*.yaml, practice.yaml, info.yaml, revision.yaml, the extract cache, the coverage report
prints per module: planned lessons, written lessons, practice sets; then the next step.

A module is done only when every planned lesson exists, digest/<id>.md exists, a Practice set carries `module: <id>`
and the subject's CLAUDE.md log says "<id> done". A session cut off by a usage limit leaves lesson files but not the
rest, so the module stays "started" and the next session finishes it instead of skipping it.
"""
import glob, json, os, re, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _ticked(code):
    """The finish ticks the subject in term2/CLAUDE.md ("- [x] <code>"). The A4 draft is required only where the exam
    allows one, so a ticked subject without an A4 (e.g. ds2: both exams closed book) counts as finished."""
    text = open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf8").read()
    return re.search(r"^- \[x\] " + re.escape(code) + r"(?![\w-])", text, re.M) is not None


def planned(subject_text):
    """module id -> lesson ids listed in the '# id title · id title' comments under it"""
    plan, cur = {}, None
    for line in subject_text.splitlines():
        m = re.match(r"\s*-\s*\{id:\s*([\w-]+)", line)
        if m:
            cur = m.group(1); plan[cur] = []; continue
        if cur and re.match(r"\s+#", line):
            plan[cur] += re.findall(r"(?:#|·)\s*([a-z]{1,4}\d{0,2}[a-z]?)\b(?=[\s:])", line)
    return plan


def main(code):
    c = os.path.join(ROOT, code, "content")
    st = open(os.path.join(c, "subject.yaml"), encoding="utf8").read()
    S = yaml.safe_load(st)
    plan = planned(st)
    lessons = [yaml.safe_load(open(f, encoding="utf8")) for f in glob.glob(os.path.join(c, "lessons", "*.yaml"))]
    by_mod = {}
    for L in lessons:
        by_mod.setdefault(L.get("module"), []).append(L)
    P = (yaml.safe_load(open(os.path.join(c, "practice.yaml"), encoding="utf8")) or {}).get("sets", []) if os.path.exists(os.path.join(c, "practice.yaml")) else []
    cited = json.dumps(P, ensure_ascii=False).lower()
    log = open(os.path.join(ROOT, code, "CLAUDE.md"), encoding="utf8").read() if os.path.exists(os.path.join(ROOT, code, "CLAUDE.md")) else ""
    print("%s: %s  (profile %s)" % (code, S.get("title"), S.get("profile")))
    nxt = None
    for m in S.get("modules", []):
        have = sorted(L["id"] for L in by_mod.get(m["id"], []))
        want = plan.get(m["id"], [])
        missing = [x for x in want if x not in have]
        mins = sum(L.get("minutes", 0) for L in by_mod.get(m["id"], []))
        sets = [s["id"] for s in P if s.get("module") == m["id"] or any(x in json.dumps(s).lower() for x in have)]
        has_digest = os.path.exists(os.path.join(ROOT, code, "digest", m["id"] + ".md"))
        gaps = missing + [g for g, ok in (
            ("digest", has_digest),
            ("practice", any(s.get("module") == m["id"] for s in P)),
            ("log", re.search(r"(?<![\w-])%s\*{0,2}:? (done|complete)" % re.escape(m["id"]), log, re.I)),
        ) if not ok]
        state = "done" if have and not gaps else ("started" if have or has_digest else "todo")
        if state != "done" and nxt is None:
            nxt = m
        dg = "digest" if has_digest else "no digest"
        print("  [%s] %-8s %-40s %s  %s  lessons %d/%d%s  %d min" % (
            {"done": "x", "started": "~", "todo": " "}[state], m["id"], m["title"][:40], m.get("group", ""), dg,
            len(have), len(want) or len(have), (" missing: " + " ".join(gaps)) if gaps and state == "started" else "", mins))
    inv = os.path.join(ROOT, "_studio", "cache", code, "inventory.json")
    if os.path.exists(inv):
        new = [r["path"] for r in json.load(open(inv, encoding="utf8")) if r["status"]]
        print("  cache: extracted%s" % (" (%d sources were new/changed at the last extract)" % len(new) if new else ""))
    else:
        print("  cache: NOT extracted: run extract.py %s" % code)
    inbox = [p for p in glob.glob(os.path.join(ROOT, code, "source", "inbox", "*")) if not os.path.basename(p).startswith(".")]
    if inbox:
        print("  inbox: %d unfiled file(s)" % len(inbox))
    I = yaml.safe_load(open(os.path.join(c, "info.yaml"), encoding="utf8")) or {}
    ledger = [s for s in I.get("sections", []) if "cover" in s.get("title", "").lower()]
    R = yaml.safe_load(open(os.path.join(c, "revision.yaml"), encoding="utf8")) or {} if os.path.exists(os.path.join(c, "revision.yaml")) else {}
    ledger_rows = sum(len((s.get("table") or {}).get("rows", [])) for s in ledger)
    print("  practice sets: %d · info ledger rows: %d · A4 draft: %s · old notes/: %s" % (
        len(P), ledger_rows, "yes" if R.get("a4") else "no",
        "present" if os.path.isdir(os.path.join(ROOT, code, "notes")) else "deleted"))
    if inbox:
        print("NEXT: step 0 (intake): file every inbox file, move duplicates/older versions to source/_superseded/, extract, refresh facts.")
    elif not lessons:
        print("NEXT: step 1 (plan): extract, read the outline + every past paper, fix the roadmap; then module %s." % (nxt or S["modules"][0])["id"])
    elif nxt:
        print("NEXT: step 2 for module %s (%s)." % (nxt["id"], nxt["title"]))
    elif os.path.isdir(os.path.join(ROOT, code, "notes")) or (not R.get("a4") and not _ticked(code)) or not ledger_rows:
        print("NEXT: step 3-4 (finish: revision.yaml A4, Info ledger/pattern, final checks; then retire notes/).")
    else:
        print("NEXT: rebuild complete. Maintain via the update protocol.")


if __name__ == "__main__":
    main(sys.argv[1])
