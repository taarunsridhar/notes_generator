# notes_generator

Turns a folder of course sources (slides, textbook chapters, readings, cases, past papers) into **one self-contained, offline study file per subject** — an INDEX 0-style app with a Learn roadmap, a 2–3 hour Revision cheat sheet, graded Practice sets, and an Info tab tracking exam facts and source coverage.

This repo holds the generator itself: the build engine, the content schema, the extraction and coverage tools, and the test suite. It does not include any actual course content, sources, or PDFs — those live in a separate, private per-subject repo and are fed into this engine as YAML.

## How it works

```
source/            raw inputs: slides, readings, cases, problem sets, past papers
  → studio/tools/extract.py        every source → page-marked text + page PNGs (for scans/diagrams)
  → content/*.yaml                 lessons, practice, revision and info, written by hand or by an LLM
  → studio/engine/build.py         content → one self-contained <code>.html
  → studio/tools/coverage_check.py checks every source page and every past-paper question is taught somewhere
  → studio/tests/run_all.py        validates the schema, verifies every numeric claim, renders and screenshots the file
```

The built file is a single HTML page (fonts, KaTeX and vendored JS inlined) with four tabs:

- **Learn** — a roadmap of modules → lessons. Every lesson follows a fixed order: big idea, why it matters, an analogy, the dense concept teaching, formulas, diagrams, key terms, worked examples (revealed step by step), key points, common mistakes, and check-yourself questions.
- **Revision** — the whole subject condensed to a true cheat sheet, filterable by exam, printable, targeting 2–3 hours end to end.
- **Practice** — MCQs (with the trap named in each wrong option), graded problem sets, drills with fresh randomized numbers, case questions, and real past papers as timed sets, each with a model answer.
- **Info** — exam format and weights, the examiner's pattern, a coverage ledger (source → lessons, ✓/partial/✗), errata, and what's still to upload.

## Layout

```
studio/
  engine/      build.py (content → html), schema.py (validates content), template.html (the app shell), vendor/ (KaTeX, fonts)
  tools/       extract.py, coverage_check.py, verify_numbers.py, render_check.py, new_subject.py, rebuild_status.py
  tests/       run_all.py, fixture/ (a demo subject exercising every feature — build it after any engine change)
```

Content for a subject (kept in its own repo, not here) is plain YAML:

| file | holds |
|---|---|
| `subject.yaml` | subject metadata, profile (`quant` \| `case`), modules and their exam group |
| `lessons/<id>-<slug>.yaml` | one lesson, in the fixed order above |
| `practice.yaml` | MCQ / problem / drill / case / past-paper sets |
| `revision.yaml` | the cheat-sheet content and optional A4 exam-sheet draft |
| `info.yaml` | exam facts, coverage ledger, errata, what's still to upload |
| `drills.js` + `drill_tests.py` | randomized-number drills and their formula tests (quant subjects) |

## Running it

```bash
python studio/tools/new_subject.py <code> "<Title>" <quant|case>   # scaffold a new subject
python studio/tools/extract.py <code>                              # sources → cache/<code>/ (text + page PNGs)
python studio/tools/coverage_check.py <code>                        # what's untaught or uncited
python studio/tests/run_all.py <code>                               # validate, verify numbers, build, screenshot
```

`studio/tests/fixture/` is a self-contained demo subject; running `run_all.py` with no argument builds it and every subject with lessons, and is the fastest way to confirm the engine still works after a change.

## Design notes

- One idea = one point, table row, or diagram — density over length.
- Every number in a worked example carries a `verify:` (recomputed at build time) or a drill test.
- Every lesson lists its `sources:` with page references; `coverage_check.py` flags any source page or past-paper question that nothing cites.
- No AI scaffolding: no reflex lists, "every trap" lists, mastery meters, or meta chatter inside lessons — just the same calm lesson structure every time.
