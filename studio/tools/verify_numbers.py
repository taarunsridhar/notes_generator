"""Recompute every number a subject's content asserts, without building.

usage: python _studio/tools/verify_numbers.py <content_dir>
1. every lesson example's `verify: [{expr, equals, tol}]` is evaluated (same rule the build enforces);
2. every practice problem's `verify:` likewise;
3. if <content_dir>/drill_tests.py exists, it is run: it should import nothing from the page, re-implement the
   drill formulas independently, and assert on sampled cases (pattern from archive/2026-09-23-mppo-upgrade).
"""
import glob, math, os, runpy, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml

SAFE = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
SAFE.update(abs=abs, min=min, max=max, round=round, sum=sum)


def check(items, where):
    n, bad = 0, []
    for it in items:
        for v in it.get("verify") or []:
            n += 1
            got = eval(v["expr"], {"__builtins__": {}}, dict(SAFE))
            if abs(got - float(v["equals"])) > float(v.get("tol", 1e-6)):
                bad.append("%s: %s = %r, content says %r" % (where, v["expr"], got, v["equals"]))
    return n, bad


def main(cdir):
    total, bad = 0, []
    for f in sorted(glob.glob(os.path.join(cdir, "lessons", "*.yaml"))):
        L = yaml.safe_load(open(f, encoding="utf8"))
        n, b = check(L.get("examples") or [], L["id"]); total += n; bad += b
    p = os.path.join(cdir, "practice.yaml")
    if os.path.exists(p):
        for s in (yaml.safe_load(open(p, encoding="utf8")) or {}).get("sets", []):
            n, b = check(s.get("items") or [], "practice " + s["id"]); total += n; bad += b
    dt = os.path.join(cdir, "drill_tests.py")
    if os.path.exists(dt):
        runpy.run_path(dt); print("drill_tests.py passed")
    print("%d asserted numbers checked, %d mismatches" % (total, len(bad)))
    for b in bad:
        print("  ", b)
    return not bad


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
