"""Content schema for a subject (see _studio/README.md). validate(subject) -> list of error strings."""

LESSON_REQUIRED = ["id", "module", "order", "title", "big_idea", "why", "concepts", "key_points"]
LESSON_OPTIONAL = ["story", "diagrams", "formulas", "definitions", "examples", "mistakes", "try_it",
                   "questions", "revise", "sources", "minutes", "subtitle", "kind", "session"]
DIAGRAM_TYPES = {
    "compare": ["left_label", "left_points", "right_label", "right_points"],
    "pipeline": ["steps"],            # steps: [{label, note}]
    "flow": ["nodes", "edges"],       # nodes: [{id, label}], edges: [{from, to, label?}]
    "cycle": ["steps"],               # steps: [label] or [{label, note}]
    "plot": ["series"],               # series: [{label, points | fn, color?}], x_min.. optional
    "table": ["head", "rows"],
    "matrix": ["x_label", "y_label", "cells"],   # cells: [[tl, tr], [bl, br]] each {title, note}
    "timeline": ["events"],           # events: [{when, label}]
    "stack": ["layers"],              # layers top→bottom: [{label, note}]
    "formula": ["tex"],               # tex + optional parts: [{sym, meaning}]
}
PRACTICE_KINDS = {"mcq", "problems", "case", "drill", "paper"}


def _need(obj, keys, where, errs):
    for k in keys:
        if k not in obj or obj[k] in (None, "", []):
            errs.append("%s: missing '%s'" % (where, k))


def validate(S):
    errs = []
    _need(S["subject"], ["code", "title", "profile", "modules"], "subject.yaml", errs)
    mods = {m["id"] for m in S["subject"].get("modules", [])}
    ids = set()
    for L in S["lessons"]:
        w = "lesson %s" % L.get("id", "?")
        _need(L, LESSON_REQUIRED, w, errs)
        for k in L:
            if k not in LESSON_REQUIRED + LESSON_OPTIONAL:
                errs.append("%s: unknown field '%s'" % (w, k))
        if L.get("kind") not in (None, "case"):
            errs.append("%s: kind must be 'case' or absent" % w)
        if L.get("id") in ids:
            errs.append("%s: duplicate id" % w)
        ids.add(L.get("id"))
        if L.get("module") not in mods:
            errs.append("%s: module '%s' not in subject.yaml" % (w, L.get("module")))
        for i, d in enumerate(L.get("diagrams") or []):
            t = d.get("type")
            if t not in DIAGRAM_TYPES:
                errs.append("%s diagram %d: unknown type '%s'" % (w, i, t))
            else:
                _need(d, DIAGRAM_TYPES[t], "%s diagram %d (%s)" % (w, i, t), errs)
        for i, e in enumerate(L.get("examples") or []):
            _need(e, ["title", "question", "steps", "answer"], "%s example %d" % (w, i), errs)
        for i, q in enumerate(L.get("questions") or []):
            _need(q, ["q", "a"], "%s question %d" % (w, i), errs)
        for i, f in enumerate(L.get("formulas") or []):
            _need(f, ["name", "tex"], "%s formula %d" % (w, i), errs)
    for s in S["practice"].get("sets", []):
        w = "practice set %s" % s.get("id", "?")
        _need(s, ["id", "title", "kind"], w, errs)
        if s.get("kind") not in PRACTICE_KINDS:
            errs.append("%s: kind must be one of %s" % (w, sorted(PRACTICE_KINDS)))
        if s.get("kind") == "mcq":
            for i, it in enumerate(s.get("items", [])):
                oks = [o for o in it.get("options", []) if o.get("ok")]
                if len(oks) != 1:
                    errs.append("%s item %d: exactly one option needs ok: true" % (w, i))
                for o in it.get("options", []):
                    if not o.get("why"):
                        errs.append("%s item %d: every option needs a 'why'" % (w, i))
        if s.get("kind") == "drill":
            _need(s, ["drill"], w, errs)
    return errs
