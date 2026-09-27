# _studio: how every subject file is built

All the logic behind the study files lives here. Subjects hold **content** (YAML) and **sources**; the studio turns content into one self-contained `<code>/<code>.html` per subject, INDEX 0-style.

```
_studio/
  engine/      build.py (content → html) · template.html (the app: Learn / Revision / Practice / Info)
               schema.py (validator; the build fails on bad content) · vendor/ (KaTeX block, OFL fonts)
  tools/       extract.py · coverage_check.py · verify_numbers.py · render_check.py · new_subject.py · rebuild_status.py
  tests/       run_all.py · fixture/ (a demo subject that uses every feature: build it after any engine change)
  cache/       regenerable per subject: inventory, page text, page PNGs, reading index, coverage report, screenshots. gitignored
  reference/   index0/ (screenshots of INDEX 0, design-notes.md, sample YAML)
  archive/     past one-off scripts, kept for reuse (e.g. 2026-09-23-mppo-upgrade: drill verifier, headless harnesses)
```

## The loop for a subject

```bash
python _studio/tools/extract.py mppo               # every source → cache/mppo/: inventory.md, text/, compact.txt, pages/*.png
#  write / edit mppo/content/*.yaml (read the text, LOOK at the page PNGs)
python _studio/tools/coverage_check.py mppo        # ledger draft + untaught pages + uncited papers → cache/mppo/coverage_report.md
python _studio/tests/run_all.py mppo               # verify numbers → build (+ WARN lines) → headless render check + screenshots
```

- `extract.py` with no argument does every subject. It reads pdf, pptx (with speaker notes), docx and md, and lists xlsx, csv and images. It skips `inbox/` but reports unfiled files there. Pages with under 25 words are rendered to PNG (every page for a scan), and each run marks sources **new / changed / removed** since the last one, which drives the update protocol.
- `cache/<code>/compact.txt` has one line per page (books over 150 pages excluded) and is the fastest way to scan a subject. `text/<name>.txt` holds the full text with `--- pN` markers.
- `new_subject.py <code> "<Title>" <quant|case>` scaffolds a subject. It creates only missing files.
- `rebuild_status.py <code>` shows where a rebuild stands: planned lesson ids (the comments under each module in `subject.yaml`) against written lessons, Practice sets, the inbox, the cache, and the next step. A module is done only with every planned lesson, its digest, a Practice set with `module: <id>` and a `<id> done` line in the subject's CLAUDE.md log; otherwise it prints what is missing. Run it first in every "continue building" session.
- `run_all.py` skips a subject whose `content/lessons/` is empty (a skeleton).
- `nightly.ps1` is the unattended runner. It runs `continue building <code>` sessions subject by subject and paces them against the plan's usage windows, learning each window's capacity from limit hits (`logs/usage.json`). Options include `-UntilDone` (keep making passes until every subject is complete), `-Model auto|opus|sonnet` and `-Usage buffer|max` (max: no pacing, run to the real limit and sleep to the reset); its header has the full list. One runner at a time (`logs/runner.lock`); each session ends in a checkpoint commit in the subject's repo; waits log a heartbeat every 30 min. It logs every session to `logs/history.md` and each run to `logs/<date>/summary.md`.

Never hand-edit a built `<code>.html`: edit the YAML and rebuild. After changing `engine/`, run `python _studio/tests/run_all.py` (fixture + every subject).

## Layers of a subject

`source/` (raw inputs; `inbox/` unfiled, `_superseded/` replaced or duplicate files, not extracted) → `_studio/cache/<code>/` (machine extraction) → `<code>/digest/<module>.md` (Claude's organised, cited notes per module: every examinable point, the clashes resolved, the numbers to verify, the paper questions) → `content/*.yaml` (the lessons, written from the digest) → `<code>.html` (built). Updates flow in the same direction: a new input changes the digest first, then the lessons.

## Content layout (`<code>/content/`)

| file | holds |
|---|---|
| `subject.yaml` | `code`, `brand` (header wordmark), `title`, `profile` (quant \| case), `eyebrow`, `blurb`, `hero_diagram`, `modules: [{id, title, group, blurb}]` (group = the exam it belongs to) |
| `lessons/<id>-<slug>.yaml` | one lesson (schema below). `id` = the topic code in `PROGRESS.md`, lowercase (`i2`, `v3`), so the tracker, the wrong list and `#/l/<id>` links agree. Order comes from module + `order` |
| `practice.yaml` | `sets: [{id, module, group, title, kind, intro, source, minutes, ...}]`; kinds: `mcq` (items: q + options {t, ok, why}), `problems` (items: level 1–3, q, hint, solution, source, verify), `case` (case text + questions {q, marks, model}), `paper` (same as case, for a real past paper; a question may carry `label: "1.3"` to print Q1.3 instead of its position), `drill` (drill: name → `drills.js`) |
| `revision.yaml` | `title`, `intro`, optional `a4: {title, note, sides: [{label, blocks: [{h, lines}]}]}` |
| `info.yaml` | `title`, `intro`, `sections: [{title, body?, list?, table?: {head, rows}}]`: exam facts, coverage ledger (status cells start with ✓ / partial / ✗), still to upload, errata, patterns. Study time is added automatically |
| `drills.js` | `window.DRILLS.<name> = function(box, U){…}` (quant subjects). Pair with `drill_tests.py` that re-implements the formulas and asserts on samples |

## Lesson schema (INDEX 0 order)

```yaml
id: attribution            # stable, used in links (#/l/attribution)
module: m1
order: 2
minutes: 45                # honest study time; feeds Info and the module cards
title: "Attribution: Is It Them or the Situation?"
subtitle: optional one line
kind: case                 # optional: a case-prep lesson (sections relabelled: what this case tests, what class will ask,
session: "S05 (29 Sep)"    #   the case in brief, the facts that matter, the questions solved, my position, weak answers, cold-calls)
big_idea: "one sentence, **bold** the key term"          # shown in the BIG IDEA card and the module list
why: ["why this exists / why it matters, 2–4 bullets"]
story: |                   # the analogy, a short story
  ...
concepts: ["the teaching, 6–12 dense points; **term** = teal bold, ==warning== = orange bold, \\( maths \\)"]
formulas: [{name, tex, read, use}]                        # quant: every formula; KaTeX, \cf \rt \tm \gr macros
diagrams: [{type, title, caption?, ...}]                  # see below
definitions: [{term, meaning}]
examples: [{title, source, question, steps: [...], answer, verify: [{expr, equals, tol}]}]   # steps reveal one at a time
key_points: ["the recap; default content of the Revision card"]
mistakes: ["common mistakes that cost marks"]
try_it: "a small thing to do before moving on"
questions: [{q, a}]                                       # check yourself, answers hidden
revise: {points: [...], diagram: 0 | table: {head, rows}, mistakes: [...], formulas: false | [0, 2]}   # Revision-card overrides (formulas: none, or only these indices)
sources: ["S02 p9–23", "R02-03 §perception", "PAPER-2020-endterm Q2"] # provenance: not shown in the lesson. Cite by the
                           # file's code (S02, C09, R04, PS3) or its full stem for papers, so coverage_check can match it
```

Diagram types: `compare` (left/right columns) · `pipeline` (steps with notes) · `flow` (nodes + edges, auto-layered) · `cycle` · `plot` (series of points or `fn: "expression in x"` sampled at build; `dots: true` draws a scatter, `dashed: true` a dashed line; `color: 1–4` fixes the series colour and a series without `label` stays out of the legend (e.g. the lower half of a band); `marks: [{x, y, label}]` labels points) · `table` · `matrix` (2×2 with axes) · `timeline` · `stack` (pyramid, top → bottom) · `formula` (KaTeX + parts).

Markdown in any text field: `**bold**`, `==highlight==`, `*italic*`, `` `code` ``, `\\( inline maths \\)`, `\\[ display \\]`, `[text](#/l/lesson-id)` links. Blank line = paragraph break. A paragraph whose every line starts with `|` renders as a table (first row = header, `|---|` rows skipped): use it for Excel/JASP output in Practice items and papers.

## What the build computes
- `stats`: learn time (sum of `minutes`) and an estimate of **Revision reading time**: what the Revision tab renders, at 100 words/min, plus 1 min per formula or diagram. Both are shown in Info → Study time; the Revision header shows the time for the selected exam.
- Warnings (non-fatal): a lesson without minutes, sources, a worked example, mistakes or questions; a quant lesson without formulas; concept counts outside 4–14; a revision card over 12 min; learn time outside 14–26 h; Revision over 3 h.

## Checks the tests run
- schema valid (unknown fields, missing sections, MCQs with exactly one right answer and a `why` on every option);
- every `verify` number recomputed; `fn` plots sampled in Python;
- headless Chrome walks every route: no KaTeX or JS errors, no raw `**`/`==` left, no empty diagram, worked-example reveal and MCQ clicks work;
- screenshots (dark, light, phone 390 px via iframe) and a Revision print-to-PDF page count into `cache/shots/<code>/`.

## Design
Taken from INDEX 0 (`reference/index0/design-notes.md`): near-black ground, 1 px `#212328` card borders, 12 px radius, Share Tech Mono throughout, teal `#1cd6ac` for key terms and section labels (with a leading dot), orange for the BIG IDEA label, warnings and diagram titles. A light theme and a reading-font toggle (mono / sans / serif) are ours. Fonts: Share Tech Mono, Inter, Lora (SIL Open Font License), embedded as base64.
