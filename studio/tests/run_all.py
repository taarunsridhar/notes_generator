"""Validate, verify numbers, build and render-check the fixture and every subject that has a content/ folder.

usage: python _studio/tests/run_all.py [code ...]   (no args = fixture + all subjects)
"""
import glob, os, subprocess, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY = sys.executable


def run(args):
    r = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True, encoding="utf8", errors="ignore")
    print(r.stdout.rstrip()); print(r.stderr.rstrip()) if r.returncode else None
    return r.returncode == 0


def targets(codes):
    t = [("fixture", "_studio/tests/fixture/content", "_studio/tests/fixture/fixture.html")]
    for c in sorted(glob.glob(os.path.join(ROOT, "*", "content", "subject.yaml"))):
        code = os.path.basename(os.path.dirname(os.path.dirname(c)))
        t.append((code, "%s/content" % code, "%s/%s.html" % (code, code)))
    return [x for x in t if not codes or x[0] in codes]


def main(codes):
    ok = True
    for code, cdir, out in targets(codes):
        print("\n=== %s" % code)
        if not glob.glob(os.path.join(ROOT, cdir, "lessons", "*.yaml")):
            print("skeleton (no lessons yet): not built. Rebuild it per CLAUDE.md -> Rebuilding a subject.")
            continue
        ok &= run(["_studio/tools/verify_numbers.py", cdir])
        ok &= run(["_studio/engine/build.py", cdir, out])
        ok &= run(["_studio/tools/render_check.py", out, "--shots", "_studio/cache/shots/%s" % code])
    print("\nALL OK" if ok else "\nFAILURES ABOVE")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1:]) else 1)
