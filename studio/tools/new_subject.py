"""Scaffold a subject folder in the term2 layout. Creates only what is missing; never overwrites a file.

usage: python _studio/tools/new_subject.py <code> "<Full title>" <quant|case>
creates <code>/CLAUDE.md, .gitignore, source/inbox/.gitkeep, dumps/README.md,
        content/{subject,info,practice,revision}.yaml + content/lessons/
Then follow CLAUDE.md -> "Rebuilding a subject" (or "Setting up a new subject").
"""
import os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SUBJECT = """# The subject's roadmap. Modules are grouped by the exam they belong to (group), in teaching order.
# Lesson ids = the topic codes used in PROGRESS.md, lowercase (e.g. v1); files are lessons/<id>-<slug>.yaml.
code: {code}
brand: {brand}
title: "{title}"
profile: {profile}            # quant | case
eyebrow: "{eyebrow}"
blurb: ""
# hero_diagram: {{type: pipeline, title: "...", steps: [{{label: "...", note: "..."}}]}}
modules: []
#  - {{id: m1, title: "...", group: "Mid-term", blurb: "..."}}
"""

INFO = """title: "About these notes"
intro: ""
sections:
  - title: "The exam"
    list: []                   # format, dates, weights, allowed aids, what full marks need
  - title: "How the examiner marks"
    list: []                   # each claim tagged **observed** (2+ papers) / **inferred** (1 paper) / **guess**
  - title: "What these notes cover"
    table: {{head: ["source", "taught in", "status"], rows: []}}   # status starts with ✓ / partial / ✗
  - title: "Still to upload"
    table: {{head: ["source", "what it adds", "lessons it changes", "priority"], rows: []}}
  - title: "Errata and source inconsistencies"
    list: []
  - title: "How to use this file"
    list:
      - "**Learn**: lessons in order; each ends with check-yourself questions."
      - "**Practice**: attempt before opening hints and solutions."
      - "**Revision**: the whole subject as a cheat sheet, filtered by exam."
"""

PRACTICE = """title: "Practice"
intro: ""
sets: []
"""

REVISION = """title: "The whole subject in one pass"
intro: ""
# a4: {{title: "A4 sheet draft", note: "...", sides: [{{label: "Side 1", blocks: [{{h: "...", lines: ["..."]}}]}}]}}
"""

CLAUDE = """# {CODE}: {title}

The system (goal, lesson structure, tabs, update protocol) is in `../CLAUDE.md`; the build machinery in `../_studio/README.md`; progress in `../PROGRESS.md`. This file holds only {CODE} facts and rules.

**Profile:** {profile}. **Study file:** `{code}.html`, built from `content/`.

## Course facts

## How it is examined (what full marks need)

## Sources

```
source/inbox/        drop zone
source/REF-*         outline, formula sheets, cribs
source/slides/       S<NN>-<slug>
source/problem-sets/ PS<N>-<topic>
source/cases/        C<NN>-<slug> (NN = session)
source/readings/     R<NN>-<slug>
source/past-papers/  PAPER-<year>-<exam>[-solutions]
dumps/               raw dated dumps, never edited
```

## Standing rules for this subject

## Log
"""

GITIGNORE = ".DS_Store\nThumbs.db\nsource/inbox/*\n!source/inbox/.gitkeep\n"
DUMPS = "Raw brain dumps live here, one file per dump: YYYY-MM-DD-topic.md.\n\nNever edited after the fact, never deleted. The study file holds the polished version;\nthis folder is the unedited record of what I actually thought at the time.\n"


def put(path, text):
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf8", newline="\n").write(text)
    print("  created", os.path.relpath(path, ROOT))
    return True


def main(code, title, profile):
    assert profile in ("quant", "case"), "profile must be quant or case"
    d = os.path.join(ROOT, code)
    kw = dict(code=code, CODE=code.upper(), title=title, profile=profile, brand=code.upper(), eyebrow="PGP Term 2")
    put(os.path.join(d, "CLAUDE.md"), CLAUDE.format(**kw))
    put(os.path.join(d, ".gitignore"), GITIGNORE)
    put(os.path.join(d, "source", "inbox", ".gitkeep"), "")
    put(os.path.join(d, "dumps", "README.md"), DUMPS)
    put(os.path.join(d, "content", "subject.yaml"), SUBJECT.format(**kw))
    put(os.path.join(d, "content", "info.yaml"), INFO.format(**kw))
    put(os.path.join(d, "content", "practice.yaml"), PRACTICE.format(**kw))
    put(os.path.join(d, "content", "revision.yaml"), REVISION.format(**kw))
    os.makedirs(os.path.join(d, "content", "lessons"), exist_ok=True)
    print("%s scaffolded. Next: python _studio/tools/extract.py %s" % (code, code))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
