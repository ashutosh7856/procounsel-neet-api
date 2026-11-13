# MBA content format and scripts

Content reaches Firestore only through the scripts in `scripts/mba/`. They write via
`api.db.get_db()` into the registered `mba*` collections, are idempotent (fixed document
ids, overwrite on re-run) and have a `--dry-run` that validates without touching the
database. Firestore is production: dry-run first, always.

## Exam config — `seed_exam.py`

```bash
.venv/bin/python -m scripts.mba.seed_exam --dry-run
.venv/bin/python -m scripts.mba.seed_exam
```

Loads `data/mba/cat_exam.json` as-is into `mbaExams/cat` (sources in `data/mba/SOURCES.md`).
If the file is missing the script exits with a message and writes nothing; it never fills
in values. The file must match the `Exam` shape in `docs/mba-api.md`:

```json
{ "id": "cat", "name": "...", "conductingBody": "...", "officialUrl": "https://iimcat.ac.in",
  "versions": [ { "year": 2025,
    "sections": [ { "id": "VARC", "name": "...", "questionCount": 24, "durationMinutes": 40 } ],
    "marking": [ { "type": "MCQ", "correct": 3, "incorrect": -1, "unanswered": 0 },
                 { "type": "TITA", "correct": 3, "incorrect": 0, "unanswered": 0 } ],
    "totalDurationMinutes": 120, "sectionOrderLocked": true,
    "source": { "kind": "official", "title": "...", "url": "https://...", "year": 2025, "retrievedAt": "2026-11-11" } } ] }
```

Checks: schema; `questionCount` may be `null` (not announced yet, e.g. 2026); every version
has a `source.url`, MCQ and TITA marking rules, unique year, and section durations that add
up to `totalDurationMinutes`.

### Other MBA exams — `data/mba/exams-config/<examId>.json`

```bash
.venv/bin/python -m scripts.mba.seed_exam --exam xat --dry-run
.venv/bin/python -m scripts.mba.seed_exam --all --dry-run     # CAT + xat, snap, nmat, cmat, mat, gmat, mah-mba-cet
.venv/bin/python -m scripts.mba.seed_exam --exam xat          # writes mbaExams/xat
```

Same `Exam` shape (docs/mba-api.md → Shared types) plus the multi-exam fields; every value comes from the exam
body's own site or bulletin (sources: `data/mba/SOURCES.md` §6.5; unknown → `null`, never estimated):

```json
{ "id": "xat", "name": "Xavier Aptitude Test (XAT)", "conductingBody": "...", "officialUrl": "https://xatonline.in/",
  "adaptive": false,
  "versions": [ { "year": 2027,
    "sections": [ { "id": "VALR", "name": "Verbal Ability and Logical Reasoning", "questionCount": 26, "durationMinutes": null },
                  { "id": "GK", "name": "General Knowledge", "questionCount": 20, "durationMinutes": 10, "countsInTotal": false } ],
    "timerBlocks": [ { "id": "PART1", "name": "Part 1", "sectionIds": ["VALR", "DM", "QADI"], "durationMinutes": 170 },
                     { "id": "GK", "name": "Part 2: General Knowledge", "sectionIds": ["GK"], "durationMinutes": 10 } ],
    "marking": [ { "type": "MCQ", "correct": 1, "incorrect": -0.25, "unanswered": 0, "sections": ["VALR", "DM", "QADI"] },
                 { "type": "MCQ", "correct": 1, "incorrect": 0, "unanswered": 0, "sections": ["GK"] } ],
    "unansweredPenalty": { "sections": ["VALR", "DM", "QADI"], "freeCount": 12, "marks": -0.1 },
    "totalDurationMinutes": 180, "sectionOrderLocked": true,
    "scoring": "official", "scoringNote": "plain-language summary shown on the start screen",
    "source": { "kind": "official", "title": "...", "url": "https://...", "year": 2027, "retrievedAt": "2026-11-11" } } ] }
```

- `timerBlocks`: sections that share one timer (free movement between them). Omit it when every section has its own
  `durationMinutes` (CAT, NMAT, GMAT). A one-section block has that section's id. Blocks must cover every section once
  and add up to `totalDurationMinutes`.
- `sectionOrderLocked: false` lets the student pick the block order before starting (NMAT, GMAT).
- `marking[].sections` limits a rule to some sections; `countsInTotal: false` scores a section separately.
- `scoring: "practice"` marks a scheme that is not the exam's own score (NMAT/GMAT are adaptive and scaled; MAT does
  not state marks per correct answer) and `scoringNote` says so in plain words; `adaptive: true` for adaptive exams.
- Section ids: `^[A-Z][A-Z0-9]{0,11}$`, never VARC/DILR/QA (reserved for CAT, whose CAT-only features key on them).

## Papers / mocks — `import_paper.py`

```bash
.venv/bin/python -m scripts.mba.import_paper data/mba/content/pc-cat-mock-01 --dry-run
.venv/bin/python -m scripts.mba.import_paper data/mba/content/pc-cat-mock-01            # status "draft"
.venv/bin/python -m scripts.mba.import_paper data/mba/content/pc-cat-mock-01 --publish  # after faculty review
```

The argument is a content directory (preferred) or a single JSON file.

### Content directory `data/mba/content/<paperId>/`

`paper.json`:

```json
{ "id": "pc-cat-mock-01", "title": "ProCounsel CAT Mock 01", "examVersionYear": 2025,
  "year": null, "slot": null,
  "source": { "kind": "original", "title": "ProCounsel original (CAT pattern)", "retrievedAt": "2026-11-11" } }
```

- `id`: lowercase letters, digits, `-` (3–81 chars). For an official paper with `year` and
  `slot` it may be omitted and becomes `cat-{year}-slot{slot}`.
- `examVersionYear`: which `mbaExams/<examId>` version's pattern, timing and marking apply. It must
  exist in the exam's config file. Defaults to `year` when omitted.
- `year`, `slot`: integers or `null` (ProCounsel original mocks have none).
- `examId`: defaults to `"cat"` (config `data/mba/cat_exam.json`); any other exam needs
  `data/mba/exams-config/<examId>.json`, e.g. `{ "id": "pc-xat-mock-01", "examId": "xat", "examVersionYear": 2027, … }`.

Section fragments, one per section, named `<sectionId lowercased>.json` (at least one; no other `.json` files
allowed): `varc.json`, `dilr.json`, `qa.json` for CAT; for other exams the ids in their config, e.g. XAT
`valr.json`, `dm.json`, `qadi.json`, `gk.json`; SNAP `ge.json`, `alr.json`, `qdids.json`, `emv.json`; NMAT `ls.json`,
`qs.json`, `lrs.json`; CMAT `qtdi.json`, `lrc.json`, `lc.json`, `ga.json`, `ie.json`. Every question type must have a
marking rule for its section in that exam version (the other exams have MCQ rules only).

```json
{ "sets": [ { "key": "rc1", "kind": "passage", "title": "Optional", "contentHtml": "<p>Passage…</p>" } ],
  "questions": [
    { "key": "VARC-01", "section": "VARC", "number": 1, "type": "MCQ", "setKey": "rc1",
      "topic": "Reading Comprehension", "subtopic": "Inference", "difficulty": "medium",
      "stemHtml": "<p>…</p>",
      "options": [ { "id": "A", "textHtml": "…" }, { "id": "B", "textHtml": "…" },
                   { "id": "C", "textHtml": "…" }, { "id": "D", "textHtml": "…" } ],
      "answer": "B", "solutionHtml": "<p>…</p>",
      "source": { "kind": "original", "title": "ProCounsel original (CAT pattern)" } },
    { "key": "VARC-05", "section": "VARC", "type": "TITA", "stemHtml": "<p>…</p>", "answer": "3142",
      "solutionHtml": "<p>…</p>", "topic": "Para jumbles", "difficulty": "hard",
      "source": { "kind": "original", "title": "ProCounsel original (CAT pattern)" } } ] }
```

- The section comes from the file name; a `section` given on a set/question must match it.
- Set `kind`: `passage` | `dilr_set` | `data`; optional `images` (http(s) URLs). A question's
  `setKey` must name a set in the same section.
- Question `key`: unique within the paper (letters, digits, `-`). `type`: `MCQ` | `TITA`.
- MCQ: at least 2 `options` with unique short alphanumeric ids; `answer` must be one of them.
- TITA: no `options`; `answer` is required (string or number, ≤ 50 chars). Scoring trims, and
  compares numerically when both the student's and the stored answer are numbers.
- `number` is optional. If given it must be given for every question in that section and be
  1..n without gaps; questions are ordered by it. Otherwise the order in the file is used.
  Either way the stored `number` is the position within the section.
- `difficulty`: `easy` | `medium` | `hard` (optional). `topic`, `subtopic`, `solutionHtml`
  optional strings (a missing solution is a warning — the AI tutor then has only the key).
- `alternativeApproaches` (optional): up to 5 non-empty HTML strings, other ways to solve the
  question (e.g. "plug in the options", a shortcut). Shown after the main solution.
- `videoUrl` (optional): a video solution link; must start with `https://` (a YouTube link
  is typical). Like the solution, both are only shown after the student has answered.
- Images: put `<img src="https://…">` in `stemHtml` / `solutionHtml` / set `contentHtml`
  (or a set's `images`); no extra field is needed.
- `source` on every question (defaults its `title` to the paper source title):
  `kind` is `official` | `licensed` | `faculty` | `original`; `url` is **required** for
  `official` and `licensed`, optional otherwise.
- Unknown fields are errors.

### Single-file alternative

One JSON file `{ "paper": { …paper.json… }, "sets": [ … ], "questions": [ … ] }` with the same
fields; here every set needs a `section` too.

The Admin panel (MBA Content → *Import JSON*) takes this single-file form and imports it as a NEW
draft paper through the same `paper_format.build_paper_docs` (docs/mba-api.md → "Admin authoring");
*Export JSON* on a paper gives back this form. Papers can also be authored question by question in
the Admin panel — the per-item checks (`check_paper`, `check_set`, `check_question`) are the ones the
importer uses.

### What gets written

| Collection | Doc id | Notes |
|---|---|---|
| `mbaQuestionSets` | `{paperId}-{setKey lowercased}` | |
| `mbaQuestions` | `{paperId}-{key lowercased}` | stores `correctAnswer` (from `answer`), `solutionHtml`, `alternativeApproaches`, `videoUrl`; the API strips them until the question is answered |
| `mbaPapers` | `{paperId}` | `title`, `examVersionYear`, `year`, `slot`, `source`, `sections: [{id, questionIds}]`, `questionCount` (written last) |

- Every document gets `status: "draft"`, or `"published"` with `--publish`. Re-running
  overwrites the same ids, so a draft import after a published one un-publishes it.
- Questions/sets of the same paper that are no longer in the content are set to
  `status: "archived"` (never deleted).
- Students see only `published` questions; a paper (and its full + sectional tests) is
  offered only when the paper and **all** of its questions are `published`.
- ProCounsel originals for other exams: `data/mba/content/pc-xat-mock-01`, `pc-snap-mock-01`, `pc-nmat-mock-01`,
  `pc-cmat-mock-01` (full length, `source.kind: "original"`, AI-drafted and answer-checked, pending faculty review).
- Warnings (not errors): section sizes that differ from the exam version's `questionCount`,
  unused sets, missing solutions.
- Faculty review happens in the Admin panel ("MBA Content", `/api/v1/mba/admin`, see
  `docs/mba-api.md`): import as draft, approve/reject/flag and edit there, then publish the paper.
  Re-importing afterwards overwrites those reviews and edits.
- The API caches content for `MBA_BANK_TTL_SECONDS` (default 300 s), so changes appear within
  five minutes.

## Programmes and official CAT minimums — `import_programs.py` (Phase D)

```bash
.venv/bin/python -m scripts.mba.import_programs --dry-run
.venv/bin/python -m scripts.mba.import_programs                    # every data/mba/programs/*.json
.venv/bin/python -m scripts.mba.import_programs data/mba/programs/iim-ahmedabad.json
```

One file per institute, `data/mba/programs/<slug>.json` (file name = `slug` = document id in `mbaPrograms`).
Overwrites with `set` (idempotent); never deletes institutes. Sources and gaps: `data/mba/SOURCES.md` §5.

```json
{ "slug": "iim-ahmedabad", "name": "Indian Institute of Management Ahmedabad", "shortName": "IIM Ahmedabad",
  "city": "Ahmedabad", "state": "Gujarat", "website": "https://www.iima.ac.in",
  "programs": [ { "code": "PGP", "name": "...", "durationYears": 2,
      "feeTotal": 2600000, "feeNote": "what it includes", "feeSource": { "kind": "official", "...": "..." },
      "intake": 400, "intakeSource": { "...": "..." },
      "medianSalary": 3400000, "medianSalaryYear": 2025, "salaryNote": "...", "salarySource": { "...": "..." } } ],
  "cutoffs": [ { "policyBatch": "2027-29", "stage": "shortlisting", "programCode": null,
      "category": "General", "pwd": false, "overall": 95, "varc": 85, "dilr": 85, "qa": 85,
      "notes": "non-CAT minimums etc.", "source": { "kind": "official", "title": "...", "url": "https://...",
      "year": 2026, "retrievedAt": "2026-11-11", "quote": "verbatim text the numbers come from" } } ],
  "cutoffNotes": "why thresholds are missing, if they are" }
```

Rules (checked by the importer): every source is `kind: "official"` with an `http(s)` url and `retrievedAt`;
a non-null `feeTotal` / `intake` / `medianSalary` needs `feeSource` / `intakeSource` / `salarySource`
(and `medianSalaryYear`); unknown values are `null`, never estimated. Cutoffs are the published
**minimum** percentiles for the CAT-based shortlisting stage (not closing percentiles):
`category` ∈ General, EWS, NC-OBC, SC, ST; PwD rows use `pwd: true` (a single PwD row in a policy is
expanded to all five categories); a single "sectional" minimum is written to each of varc/dilr/qa.
Optional `gender` ("Male" | "Female" | "Transgender", default null = all) for gender-specific minimums.
`programCode: null` = the first (flagship) programme. One record per (batch, programme, category, pwd, gender).
Optional notes: `feeNote`, `intakeNote`, `salaryNote` (what a figure covers, e.g. NIRF intake = all 2-year PG programmes).
`quote` is stored for audit but never returned by the API.

## Re-importing after review

Re-running `import_paper` never overwrites faculty work: questions/sets with `reviewedAt` set or `version > 1`, and a paper that is already published, are skipped (the summary prints how many). Pass `--force` only to deliberately replace reviewed content.
