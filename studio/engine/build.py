"""Build one self-contained study file from a subject's content folder.

usage: python _studio/engine/build.py <content_dir> [<out.html>]
default out: <content_dir>/../<code>.html
"""
import base64, glob, json, math, os, re, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from schema import validate


def load(cdir):
    def y(name, default):
        p = os.path.join(cdir, name)
        return yaml.safe_load(open(p, encoding="utf8")) if os.path.exists(p) else default
    S = {"subject": y("subject.yaml", {}), "practice": y("practice.yaml", {}) or {},
         "info": y("info.yaml", {}) or {}, "revision": y("revision.yaml", {}) or {}}
    S["lessons"] = [yaml.safe_load(open(p, encoding="utf8")) for p in sorted(glob.glob(os.path.join(cdir, "lessons", "*.yaml")))]
    order = {m["id"]: i for i, m in enumerate(S["subject"].get("modules", []))}
    S["lessons"].sort(key=lambda L: (order.get(L.get("module"), 99), L.get("order", 0)))
    dj = os.path.join(cdir, "drills.js")
    S["drills_js"] = open(dj, encoding="utf8").read() if os.path.exists(dj) else ""
    return S


SAFE = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
SAFE.update(abs=abs, min=min, max=max, round=round, sum=sum)


def expand_plots(S):
    """plot series may give fn: 'expression in x' -> sampled points (computed here, not by hand)."""
    for L in S["lessons"]:
        for d in L.get("diagrams") or []:
            if d.get("type") != "plot":
                continue
            x0, x1 = float(d.get("x_min", 0)), float(d.get("x_max", 1))
            for s in d["series"]:
                if "fn" in s and "points" not in s:
                    n = int(s.get("samples", 60))
                    pts = []
                    for i in range(n + 1):
                        x = x0 + (x1 - x0) * i / n
                        pts.append([round(x, 6), round(eval(s["fn"], {"__builtins__": {}}, dict(SAFE, x=x)), 6)])
                    s["points"] = pts


def verify_examples(S):
    """examples may carry verify: [{expr: '...', equals: number, tol: 1e-6}] -> build fails on mismatch."""
    errs = []
    for L in S["lessons"]:
        for e in L.get("examples") or []:
            for v in e.get("verify") or []:
                got = eval(v["expr"], {"__builtins__": {}}, dict(SAFE))
                if abs(got - float(v["equals"])) > float(v.get("tol", 1e-6)):
                    errs.append("lesson %s example '%s': %s = %r, content says %r" % (L["id"], e["title"], v["expr"], got, v["equals"]))
            e.pop("verify", None)
    return errs


WPM = 100          # careful reading of dense revision text
FIG_MIN = 1.0      # minutes per formula / diagram / table row block on the Revision tab


def _words(x):
    t = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return len(re.findall(r"[A-Za-z0-9]+", re.sub(r"\\(.*?\\)|\\[.*?\\]", " x ", t)))


def stats(S):
    """Learn time (from lesson minutes) and an estimate of Revision reading time (what revisePage renders)."""
    words, figs, per = 0, 0, {}
    for L in S["lessons"]:
        rv = L.get("revise") or {}
        w = _words(L.get("big_idea", "")) + _words(rv.get("points") or L.get("key_points") or [])
        ms = rv.get("mistakes") or (L.get("mistakes") or [])[:2]
        w += _words(ms)
        fs = rv.get("formulas")
        f = len(fs) if isinstance(fs, list) else len(L.get("formulas") or []) if fs is not False else 0
        if rv.get("diagram") is not None or rv.get("table"):
            f += 1
        words += w; figs += f
        per[L["id"]] = round(w / WPM + f * FIG_MIN, 1)
    a4 = (S["revision"].get("a4") or {})
    words += _words(a4.get("sides") or [])
    return {"learn_min": sum(L.get("minutes", 0) for L in S["lessons"]),
            "revise_min": round(words / WPM + figs * FIG_MIN), "revise_words": words, "revise_per_lesson": per}


def warnings(S, st):
    """Quality nudges from CLAUDE.md that don't break the build."""
    W, quant = [], S["subject"].get("profile") == "quant"
    for L in S["lessons"]:
        i = L["id"]
        if not L.get("minutes"):
            W.append("%s: no minutes" % i)
        if not L.get("sources"):
            W.append("%s: no sources (the Info ledger can't be checked)" % i)
        if not L.get("examples"):
            W.append("%s: no worked example" % i)
        if not L.get("mistakes"):
            W.append("%s: no common mistakes" % i)
        if not L.get("questions"):
            W.append("%s: no check-yourself questions" % i)
        if quant and L.get("kind") != "case" and not L.get("formulas") and not L.get("revise", {}).get("table"):
            W.append("%s: quant lesson without formulas" % i)
        n = len(L.get("concepts") or [])
        if n and not 4 <= n <= 14:
            W.append("%s: %d concept points (aim 6-12)" % (i, n))
        if st["revise_per_lesson"].get(i, 0) > 12:
            W.append("%s: revision card ~%.0f min; condense revise.points" % (i, st["revise_per_lesson"][i]))
    h = st["learn_min"] / 60
    if S["lessons"] and not 14 <= h <= 26:
        W.append("learn time %.1f h (target ~20 h)" % h)
    if st["revise_min"] > 180:
        W.append("revision ~%.1f h (target 2-3 h): condense revise.points" % (st["revise_min"] / 60))
    return W


def fonts_css():
    out = []
    for fam, fn, w in [("Share Tech Mono", "sharetechmono-latin.woff2", "400"),
                       ("Inter", "inter-latin-var.woff2", "100 900"),
                       ("Lora", "lora-latin-var.woff2", "400 700")]:
        b = base64.b64encode(open(os.path.join(HERE, "vendor", "fonts", fn), "rb").read()).decode()
        out.append("@font-face{font-family:'%s';font-weight:%s;font-display:swap;src:url(data:font/woff2;base64,%s) format('woff2')}" % (fam, w, b))
    return "\n".join(out)


def build(cdir, out=None):
    S = load(cdir)
    errs = validate(S)
    expand_plots(S)
    errs += verify_examples(S)
    if errs:
        raise SystemExit("BUILD FAILED\n  " + "\n  ".join(errs))
    code = S["subject"]["code"]
    out = out or os.path.join(os.path.dirname(os.path.abspath(cdir)), "%s.html" % code)
    st = stats(S)
    data = {k: S[k] for k in ("subject", "lessons", "practice", "info", "revision")}
    data["stats"] = st
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf8").read()
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (tpl.replace("{{TITLE}}", S["subject"]["title"])
               .replace("/*__FONTS__*/", fonts_css())
               .replace("/*__DATA__*/", "window.SUBJECT = " + js + ";")
               .replace("/*__DRILLS__*/", S["drills_js"])
               .replace("<!--__KATEX__-->", open(os.path.join(HERE, "vendor", "katex_block.html"), encoding="utf8").read()))
    open(out, "w", encoding="utf8", newline="\n").write(html)
    print("built %s: %d lessons, %d practice sets, learn %.1f h, revision ~%.1f h (%d words), %d KB" % (
        out, len(S["lessons"]), len(S["practice"].get("sets", [])), st["learn_min"] / 60, st["revise_min"] / 60, st["revise_words"], len(html) // 1024))
    for w in warnings(S, st):
        print("  WARN", w)
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
