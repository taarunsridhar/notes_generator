"""Headless-Chrome check of a built subject file.

usage: python _studio/tools/render_check.py <subject.html> [--shots <dir>] [--lessons id,id]
Walks every route (home, each module, each lesson, revision, practice + each set, info) inside the page,
counts KaTeX errors, console/JS errors, empty diagrams, clicks through worked-example steps and one MCQ,
then optionally saves light/dark/phone screenshots and prints the revision tab to PDF (page count).
Exit code 1 on any failure.
"""
import json, os, re, subprocess, sys, tempfile, html as H
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"

PROBE = r"""<script>
window.__errs=[];window.addEventListener('error',function(e){__errs.push('JS '+e.message+' @'+e.lineno)});
(function(){var ce=console.error;console.error=function(){__errs.push('CE '+[].join.call(arguments,' '));ce.apply(console,arguments)}})();
window.addEventListener('load',function(){setTimeout(function(){
 var S=window.SUBJECT,R={routes:[],errs:null},routes=['#/'];
 S.subject.modules.forEach(function(m){routes.push('#/m/'+m.id)}); S.lessons.forEach(function(l){routes.push('#/l/'+l.id)});
 routes.push('#/revise','#/practice'); (S.practice.sets||[]).forEach(function(s){routes.push('#/p/'+s.id)}); routes.push('#/info');
 routes.forEach(function(r){ location.hash=r; window.dispatchEvent(new HashChangeEvent('hashchange'));
   var app=document.getElementById('app'), rec={r:r, katexErr:app.querySelectorAll('.katex-error').length, katex:app.querySelectorAll('.katex').length,
     textLen:app.textContent.length, emptyDiagrams:[].filter.call(app.querySelectorAll('.dg .db'),function(d){return !d.textContent.trim() && !d.querySelector('svg')}).length,
     rawMarkup:/\*\*|==|\\\(|\\\[/.test(app.textContent.replace(/\s+/g,' '))};
   if(r.indexOf('#/l/')===0){ var ex=app.querySelector('.ex'); if(ex){ var hidBefore=ex.querySelectorAll('.hid').length; ex.querySelector('[data-s="all"]').click(); rec.steps=[hidBefore, ex.querySelectorAll('.hid').length]; } }
   if(r.indexOf('#/p/')===0){ var li=app.querySelector('.mcq li'); if(li){ li.click(); rec.mcq=li.closest('.mcq').classList.contains('done'); } }
   R.routes.push(rec); });
 R.errs=__errs; var p=document.createElement('pre'); p.id='RC_OUT'; p.textContent=JSON.stringify(R); document.body.appendChild(p);
},700)});
</script>"""


def chrome(args):
    return subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars"] + args, capture_output=True, text=True, encoding="utf8", errors="ignore")


def check(path, shots=None, lessons=()):
    src = open(path, encoding="utf8").read()
    tmp = os.path.join(tempfile.gettempdir(), "rc_" + os.path.basename(path))
    open(tmp, "w", encoding="utf8").write(src.replace("<head>", "<head>" + PROBE, 1))
    out = chrome(["--virtual-time-budget=15000", "--dump-dom", "file:///" + tmp.replace("\\", "/")]).stdout
    m = re.search(r'<pre id="RC_OUT">(.*?)</pre>', out, re.S)
    if not m:
        print("FAIL: page produced no probe output"); return False
    R = json.loads(H.unescape(m.group(1)))
    ok = True
    for r in R["routes"]:
        bad = []
        if r["katexErr"]: bad.append("%d katex errors" % r["katexErr"])
        if r["textLen"] < 40: bad.append("empty view")
        if r["emptyDiagrams"]: bad.append("%d empty diagrams" % r["emptyDiagrams"])
        if r["rawMarkup"]: bad.append("raw ** / == / \\( left in text")
        if "steps" in r and r["steps"][1] != 0: bad.append("example reveal broken %s" % r["steps"])
        if r.get("mcq") is False: bad.append("mcq click broken")
        print(("  ok  " if not bad else "  FAIL") + " %-28s katex=%-3d %s" % (r["r"], r["katex"], "; ".join(bad)))
        ok &= not bad
    if R["errs"]:
        print("  FAIL console/JS errors:", R["errs"]); ok = False
    print("  routes checked:", len(R["routes"]))
    if shots:
        os.makedirs(shots, exist_ok=True)
        url = "file:///" + os.path.abspath(path).replace("\\", "/")
        for name, route, size, theme in [("home-dark", "#/", "1440,1300", "dark"), ("lesson-dark", "#/l/" + first_lesson(src), "1440,4200", "dark"),
                                         ("lesson-light", "#/l/" + first_lesson(src), "1440,4200", "light"), ("revise", "#/revise", "1440,2600", "dark"),
                                         ("practice", "#/practice", "1440,1300", "dark"), ("info", "#/info", "1440,1600", "light"), ("phone", "#/l/" + first_lesson(src), "390,2600", "dark")]:
            page = src.replace('<html lang="en" data-theme="dark">', '<html lang="en" data-theme="%s">' % theme)
            page = page.replace("root.setAttribute('data-theme', store.get('theme'", "root.setAttribute('data-theme', '%s' || store.get('theme'" % theme)
            t2 = os.path.join(tempfile.gettempdir(), "shot_%s.html" % name); open(t2, "w", encoding="utf8").write(page)
            if name == "phone":  # headless Chrome won't lay out below ~500px, so frame the page at 390px
                fr = os.path.join(tempfile.gettempdir(), "shot_phone_frame.html")
                inner = "file:///" + t2.replace(os.sep, "/") + route
                open(fr, "w", encoding="utf8").write('<body style="margin:0;background:#333"><iframe src="%s" style="width:390px;height:2600px;border:0;display:block"></iframe>' % inner)
                chrome(["--window-size=500,2600", "--virtual-time-budget=8000", "--screenshot=" + os.path.abspath(os.path.join(shots, name + ".png")), "file:///" + fr.replace(os.sep, "/")])
                continue
            chrome(["--window-size=" + size, "--virtual-time-budget=6000", "--screenshot=" + os.path.abspath(os.path.join(shots, name + ".png")), "file:///" + t2.replace("\\", "/") + route])
        for lid in lessons:  # extra dark screenshots of named lessons (--lessons p2,p3)
            page = src.replace('<html lang="en" data-theme="dark">', '<html lang="en" data-theme="dark">')
            t2 = os.path.join(tempfile.gettempdir(), "shot_lesson_%s.html" % lid); open(t2, "w", encoding="utf8").write(page)
            chrome(["--window-size=1440,6500", "--virtual-time-budget=6000", "--screenshot=" + os.path.abspath(os.path.join(shots, "lesson-%s-dark.png" % lid)), "file:///" + t2.replace("\\", "/") + "#/l/" + lid])
        pdf = os.path.abspath(os.path.join(shots, "revise.pdf"))
        chrome(["--virtual-time-budget=6000", "--print-to-pdf=" + pdf, "--no-pdf-header-footer", url + "#/revise"])
        try:
            import fitz; print("  revision prints to %d pages" % fitz.open(pdf).page_count)
        except Exception as e:
            print("  pdf check skipped:", e)
    return ok


def first_lesson(src):
    m = re.search(r'"lessons": \[\{"id": "([^"]+)"', src) or re.search(r'"lessons":\s*\[\s*\{\s*"id":\s*"([^"]+)"', src)
    return m.group(1) if m else ""


if __name__ == "__main__":
    a = sys.argv[1:]
    shots = a[a.index("--shots") + 1] if "--shots" in a else None
    lessons = a[a.index("--lessons") + 1].split(",") if "--lessons" in a else ()
    sys.exit(0 if check(a[0], shots, lessons) else 1)
