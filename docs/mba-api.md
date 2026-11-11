# ProCounsel MBA — API contract (v1)

Source of truth for backend (procounsel-neet-api) and frontend (Website). Change this
file first, then the code. Base path: `/api/v1/mba`. JSON, camelCase.

## Principles
- **Real data only.** Every question, exam rule, cutoff, fee or placement figure stores a
  `source` (`{kind, title, url, year, retrievedAt}`). Nothing is invented. Missing data is
  shown as missing (e.g. an exam section's `questionCount` is `null` until officially announced).
- **Question bank = ProCounsel originals.** Official CAT past papers are not publicly
  available, so questions are ProCounsel ORIGINAL CAT-pattern questions (`source.kind:
  "original"`, AI-drafted, faculty-reviewed). Content has `status: "draft" | "published" |
  "archived"`; students only ever see `published` content.
- **Publishing gates visibility.** A question is visible to students only when it AND its paper are published (practice, daily, tests).
- **Answers are protected.** Answer keys/solutions are never returned while a mock is in
  progress. Practice reveals them only after the student answers.
- **Server owns test state.** Attempt timing, responses and scoring live on the server.
  Autosave is idempotent; submit is idempotent.
- **Auth:** endpoints marked 🔒 need `Authorization: Bearer <jwtToken>` (Java login JWT) and
  role `mbaStudent`. Public endpoints need nothing. 🛡 admin endpoints (Admin repo) need the
  Admin panel's login JWT (see "Admin content review").
- **Errors:** `{ "detail": string }` with 400/401/403/404/409/422/429/503 (429 = AI tutor daily quota).

## Collections (Firestore, all new, all `mba*`)
| Collection | Doc id | Purpose |
|---|---|---|
| `mbaExams` | `cat` | Exam config (versioned pattern per year) |
| `mbaPapers` | `pc-cat-mock-01` | Paper / ProCounsel original mock: title, examVersionYear, year?, slot?, sections → ordered question ids, source, status |
| `mbaQuestionSets` | `{paperId}-{setKey}` | Shared passage / DILR set / chart for a group of questions |
| `mbaQuestions` | `{paperId}-{key}` | Questions (answer + solution stored here, stripped in responses); `status` draft/published/archived |
| `mbaTests` | slug | Reserved. Tests are currently derived on the fly from published papers (not stored) |
| `mbaAttempts` | auto | One attempt of a test by a student (state, responses, result) |
| `mbaProfiles` | userId | Onboarding + goals |
| `mbaQuestionStats` | `{userId}_{questionId}` | Per-student practice history (attempts, correct, bookmarked, mistake info) |
| `mbaStudyTasks` | auto | Study-plan tasks |
| `mbaPrograms` | institute slug (`iim-ahmedabad`) | Institute + programmes + embedded official minimum CAT thresholds (Phase D) |
| `mbaCutoffs` | — | Not used: cutoff records are embedded in the `mbaPrograms` doc (tens per institute, always read together) |
| `mbaShortlists` | userId | A student's saved institutes, `items` map keyed by slug (Phase D) |
| `mbaAiUsage` | `{userId}_{yyyy-mm-dd}` | AI tutor quota counters |

## Shared types
```ts
type Source = { kind: "official" | "licensed" | "faculty" | "original"; title: string; url?: string; year?: number; retrievedAt?: string };
// url is required for "official" and "licensed"; optional for "original" / "faculty".
type SectionId = "VARC" | "DILR" | "QA";
type QuestionType = "MCQ" | "TITA";

interface ExamSection { id: SectionId; name: string; questionCount: number | null /* null = not announced */; durationMinutes: number }
interface MarkingRule { type: QuestionType; correct: number; incorrect: number; unanswered: number }
interface ExamVersion { year: number; sections: ExamSection[]; marking: MarkingRule[]; totalDurationMinutes: number; sectionOrderLocked: boolean; source: Source }
interface Exam { id: "cat"; name: string; conductingBody: string; officialUrl: string; versions: ExamVersion[] }

interface QuestionSet { id: string; kind: "passage" | "dilr_set" | "data"; title?: string; contentHtml: string; images?: string[] }
interface QuestionPublic {        // what students receive
  id: string; examId: "cat"; paperId?: string; section: SectionId; topic?: string; subtopic?: string;
  type: QuestionType; stemHtml: string; options?: { id: string; textHtml: string }[];  // MCQ only
  setId?: string; set?: QuestionSet; difficulty?: "easy" | "medium" | "hard";
  year?: number; slot?: number; source: Source;
}
interface QuestionReveal { correctAnswer: string; solutionHtml?: string; isCorrect?: boolean }  // MCQ: option id; TITA: exact string
```

## Public endpoints
- `GET /exams` → `{ exams: Exam[] }`
- `GET /exams/{examId}` → `Exam`
- `GET /papers?examId=cat` → `{ papers: { id, title, examVersionYear, year: number|null, slot: number|null, questionCount, sections: {id, questionCount}[], source }[] }`
  Only papers whose paper doc and every question are `published` are listed.

## Student endpoints 🔒
### Profile / onboarding
- `GET /me/profile` → `MbaProfile | 404` (404 = not onboarded)
- `PUT /me/profile` body `MbaProfileInput` → `MbaProfile`
```ts
interface MbaProfileInput { targetExam: "cat"; examDate?: string /*YYYY-MM-DD*/; targetPercentile?: number /*0-100*/;
  currentLevel: "beginner" | "intermediate" | "advanced"; weeklyStudyHours: number /*1-80*/; studyDays: number[] /*0=Sun..6*/;
  targetPrograms?: string[] }
interface MbaProfile extends MbaProfileInput { userId: string; createdAt: string; updatedAt: string }
```
### Dashboard
- `GET /me/dashboard` →
```ts
{ profile: MbaProfile | null; daysToExam: number | null;
  sections: { id: SectionId; attempted: number; correct: number; accuracy: number | null }[];
  totals: { questionsAttempted: number; correct: number; bookmarked: number; mistakesDue: number; mocksCompleted: number };
  recentAttempts: AttemptSummary[]; inProgressAttempt: AttemptSummary | null;
  priorities: { kind: "resume_mock" | "review_mistakes" | "practice_weak_section" | "take_diagnostic" | "daily_challenge"; title: string; detail: string; href: string }[];  // max 3
  streak: { current: number; lastActiveDate: string | null } }
```
### Practice
- `GET /questions?section=&topic=&year=&slot=&paperId=&filter=all|unsolved|incorrect|bookmarked&limit=20&cursor=` → `{ questions: QuestionPublic[]; nextCursor: string | null }`
  Each returned question also has `bookmarked: boolean`. `accuracy` fields everywhere are fractions 0–1.
- `POST /practice/answers` body `{ questionId, answer, timeSpentMs }` → `QuestionReveal & { stats: { attempts, correct } }`
- `PUT /me/bookmarks/{questionId}` / `DELETE /me/bookmarks/{questionId}` → `{ bookmarked: boolean }`
- `GET /me/mistakes?section=&due=true` → `{ items: { question: QuestionPublic; lastAnswer: string; category?: MistakeCategory; note?: string; nextReviewAt?: string; retries: number }[] }`
- `PATCH /me/mistakes/{questionId}` body `{ category?: MistakeCategory; note?: string }` → item
  `type MistakeCategory = "concept" | "calculation" | "misread" | "selection" | "time_pressure" | "guess"`
- `GET /daily` → `{ date: string; questions: QuestionPublic[]; completed: number }` (5–10 published questions, same for everyone per day, deterministic; `date` and `completed` use India time)

### Tests & attempts
- `GET /tests` → `{ tests: { id, title, kind: "full_mock" | "sectional", paperId, sections: SectionId[], durationMinutes, questionCount }[] }`
  Derived from each offered paper: `{paperId}-full` plus `{paperId}-varc|dilr|qa`. Durations/marking
  from the exam version `paper.examVersionYear`. Empty if the exam config is not seeded.
- `POST /attempts` body `{ testId }` → `Attempt` — returns the existing in-progress attempt for this test if any (resume), else creates.
  409 while another in-progress attempt of the student shares questions with this test (e.g. the paper's
  full mock is running and a sectional of the same paper is requested) — submitting it would reveal live answers.
- `GET /attempts/{id}` → `Attempt` (questions without answers; `serverNow` + `sectionEndsAt` for timers)
- `PATCH /attempts/{id}/responses` body `{ seq: number; responses: { questionId, answer: string | null, markedForReview: boolean, timeSpentMs: number }[] }` → `{ savedSeq: number }`. Ignores stale `seq`. Rejects after the section time is over (409).
- `POST /attempts/{id}/sections/{sectionId}/submit` → `Attempt` (moves to next section; auto-applied by server when time is up)
- `POST /attempts/{id}/submit` → `AttemptResult` (idempotent: second call returns same result)
- `GET /attempts/{id}/result` → `AttemptResult` (404 until submitted)
- `GET /me/attempts` → `{ attempts: AttemptSummary[] }`
```ts
interface Attempt { id: string; testId: string; title: string; status: "in_progress" | "submitted";
  currentSection: SectionId; sectionOrder: SectionId[]; sectionEndsAt: string; serverNow: string;
  questions: (QuestionPublic & { sectionIndex: number })[];
  responses: Record<string, { answer: string | null; markedForReview: boolean; timeSpentMs: number }>; savedSeq: number }
interface AttemptSummary { id; testId; title; status; startedAt; submittedAt?: string; score?: number; maxScore?: number }
interface AttemptResult { id; testId; title; submittedAt; score; maxScore;
  sections: { id: SectionId; score; maxScore; attempted; correct; incorrect; unanswered; accuracy: number | null; timeSpentMs }[];
  questions: (QuestionPublic & QuestionReveal & { yourAnswer: string | null; timeSpentMs: number; marks: number })[] }
```

### AI tutor 🔒
- `POST /ai/hint` body `{ questionId, level: 1 | 2 | 3, studentAnswer?: string }` → `{ text: string; level; remainingToday: number; grounded: true }`
  Level 1 = nudge, 2 = approach, 3 = full worked explanation. Only for questions the student
  has already answered in practice or in a submitted attempt (403 otherwise — no help during a
  live mock — also 403 while the question is in one of the student's in-progress attempts). The
  prompt includes the answer key and solution; the model must not contradict the answer key.
  Daily per-user quota (`mbaAiUsage`, India-time day, `MBA_AI_DAILY_LIMIT`, default 30) →
  **429** when exhausted. 503 when the tutor is not configured or the model call fails.

## Admin content review 🛡
Base `/api/v1/mba/admin`. Used by the Admin panel ("MBA Content"). Auth: `Authorization: Bearer
<jwtToken>` where the token comes from the Java `POST /api/auth/adminSignin` (HS256, same key as
student logins, subject = admin email = `admins` doc id). The caller must exist in `admins`
(read-only) and its `role` must be in `MBA_CONTENT_ADMIN_ROLES` (default `superAdmin,COURSE`;
`*` = any admin). 401 = missing/invalid/expired token, 403 = not an admin / role not allowed.
These endpoints read every status (not the published-only cache) and clear the content cache
after every write, so students see changes immediately on that instance (other serverless
instances within `MBA_BANK_TTL_SECONDS`). Writes only touch `mbaQuestions`, `mbaQuestionSets`, `mbaPapers`.

```ts
type ContentStatus = "draft" | "published" | "archived";
// draft = not flagged draft, flagged = draft flagged by a reviewer, archived = rejected (or dropped by a re-import),
// missing = id listed in the paper but no question doc
interface StatusCounts { draft: number; flagged: number; published: number; archived: number; missing: number }
interface AdminPaper { id; title; status: ContentStatus; examVersionYear: number|null; year: number|null; slot: number|null;
  questionCount: number; counts: StatusCounts; sections: { id: SectionId; questionCount: number; counts: StatusCounts }[];
  readyToPublish: boolean /* ≥1 question and all published */; source: Source|null;
  updatedAt: string|null; publishedAt: string|null; publishedBy: string|null }
interface AdminSet { id; kind: "passage"|"dilr_set"|"data"; title: string|null; contentHtml: string; images: string[]|null; version: number; updatedAt: string|null }
interface HistoryEntry { version: number; editedBy: string /* admin id */; editedAt: string; changes: string[] /* field names */; summary: string }
interface AdminQuestion { id; key: string|null; paperId: string|null; section: SectionId; number: number|null; type: QuestionType;
  stemHtml: string; options: {id; textHtml}[]|null; setId: string|null; set: AdminSet|null; topic: string|null; subtopic: string|null;
  difficulty: "easy"|"medium"|"hard"|null; correctAnswer: string; solutionHtml: string|null; source: Source;
  status: ContentStatus; flagged: boolean; reviewAction: "approved"|"rejected"|"flagged"|null; reviewNote: string|null;
  reviewedBy: string|null; reviewedAt: string|null; version: number /* 1 for imported content */; history: HistoryEntry[] /* last 50 */;
  updatedAt: string|null }
```

- `GET /papers` → `{ papers: AdminPaper[] }` — every paper, any status (sorted like the public list).
- `GET /papers/{paperId}/questions` → `{ paper: AdminPaper; questions: AdminQuestion[] }` — questions in
  paper order (section, then number); includes the answer key, solution and set. 404 unknown paper.
- `PATCH /questions/{id}` body (only sent fields change; `null` clears an optional one)
  `{ stemHtml?; options?: {id; textHtml}[]; answer?: string|number; solutionHtml?: string|null; topic?: string|null;
  subtopic?: string|null; difficulty?: "easy"|"medium"|"hard"|null; expectedVersion?: number }` → `AdminQuestion`.
  The merged question is validated with the importer's rules (stem required; MCQ ≥2 options with unique short
  alphanumeric ids and `answer` one of them; TITA no options, answer 1–50 chars) → 422 with the problems joined by
  `; `. Unknown fields 422; empty body 422. `type`, `section`, `source` are not editable. A real change bumps `version`
  and appends a `history` entry; an edit that changes nothing is a no-op. `expectedVersion` ≠ current → 409.
  Status is not changed by edits (re-review is a separate action). 404 unknown id.
- `PATCH /sets/{id}` body `{ contentHtml?; title?: string|null; expectedVersion? }` → `AdminSet` (same version/history,
  409 and 404 rules; empty `contentHtml` 422).
- `POST /questions/{id}/review` body `{ action: "approve"|"reject"|"flag"; note?: string (≤2000) }` → `AdminQuestion`.
  approve → `status "published"` (422 if the question fails validation); reject → `"archived"`; flag → `"draft"` with
  `flagged: true` (a note is required, 422 otherwise; flagging a published question takes it out of student use).
  Every action sets `reviewAction`, `reviewNote` (= the note, `null` if none), `reviewedBy` (admin id), `reviewedAt`.
- `POST /papers/{paperId}/publish` → `AdminPaper`. 409 unless the paper has questions and **every** one is
  `published` (`detail` says how many are not). Sets `status "published"`, `publishedAt`, `publishedBy`. Idempotent.
- `POST /papers/{paperId}/unpublish` → `AdminPaper` (`status "draft"`, `unpublishedAt/By`). Idempotent.

Notes: students only get a paper (and its tests) while the paper and all its questions are published, so
rejecting/flagging a question of a published paper hides the paper until it is fixed. Answer-key edits apply to
scoring from then on (attempts are scored against the current key). Re-running the importer overwrites
reviewed content (status, edits, history) — after review, edit in the Admin panel instead of re-importing.

## Phase D — programmes, official CAT minimums, eligibility tool, shortlist

**Data rules.** Every fee / intake / median-salary figure and every cutoff record carries an
`OfficialSource` (`kind: "official"`, `title`, `url`, `year`, `retrievedAt`) taken from the IIM's own
admission policy / website or its NIRF data on nirfindia.org. No coaching or aggregator sites. Unknown =
`null`. Data: `data/mba/programs/<slug>.json` → `scripts/mba/import_programs.py` → `mbaPrograms/{slug}`
(sources and gaps: `data/mba/SOURCES.md` §5).

**The thresholds are MINIMUM ELIGIBILITY THRESHOLDS** that an IIM publishes for its first, CAT-based
shortlisting stage. They are **not** closing percentiles / final cut-offs — the percentiles needed for an
interview call are usually much higher. Where an IIM has not yet published its 2027-29 policy, the
latest official one (2026-28) is used and `policyBatch` says so.

```ts
type OfficialSource = { kind: "official"; title: string; url: string; year: number | null; retrievedAt: string };
type Category = "General" | "EWS" | "NC-OBC" | "SC" | "ST";        // PwD is the separate `pwd` flag
type DataFreshness = { retrievedAt: string | null /* latest source retrieval, YYYY-MM-DD */;
  cutoffPolicyBatches: string[] /* e.g. ["2026-28","2027-29"] */; note: string };
interface ProgramKeyFacts { code: string; name: string; durationYears: number | null; feeTotal: number | null /* INR, whole programme */;
  intake: number | null; medianSalary: number | null /* INR p.a. */; medianSalaryYear: number | null /* graduating year */ }
interface ProgramDetail extends ProgramKeyFacts { feeNote: string | null; feeSource: OfficialSource | null;
  intakeNote: string | null /* e.g. NIRF figure covers all 2-year PG programmes */; intakeSource: OfficialSource | null; salaryNote: string | null; salarySource: OfficialSource | null }
interface Cutoff { policyBatch: string /* "2027-29" */; stage: "shortlisting"; programCode: string /* resolved, never null when the institute has programmes */;
  category: Category; pwd: boolean; gender: "Male" | "Female" | "Transgender" | null /* null = all genders */; overall: number | null; varc: number | null; dilr: number | null; qa: number | null;
  notes: string | null /* e.g. Class X/XII minimums, positive raw score rule */; source: OfficialSource }
interface InstituteSummary { slug: string; name: string; shortName: string; city: string | null; state: string | null;
  website: string | null; programs: ProgramKeyFacts[]; hasCutoffs: boolean; dataFreshness: DataFreshness }
interface InstituteDetail extends InstituteSummary { programs: ProgramDetail[]; cutoffs: Cutoff[];
  cutoffNotes: string | null /* e.g. why no thresholds are on record */; sources: OfficialSource[] /* distinct, all used on the page */ }
```

### Public
- `GET /programs?state=&q=` → `{ institutes: InstituteSummary[]; dataFreshness: DataFreshness }`
  Sorted by `shortName`. `state` = exact state name (case-insensitive); `q` = substring of name / short name /
  city / state / slug / programme name or code. Empty list when nothing is imported.
- `GET /programs/{slug}` → `InstituteDetail` | 404
- `POST /eligibility` body `{ category: Category; pwd?: boolean /*default false*/; gender?: "Male" | "Female" | "Transgender"; overall: number /*0-100*/; varc?: number; dilr?: number; qa?: number }` (422 on invalid) →
```ts
{ input: EligibilityInput;
  results: { slug; name; shortName; programCode: string | null; programName: string | null; policyBatch: string | null;
    status: "meets_minimum" | "below_minimum" | "unknown";
    failedOn: ("overall" | "VARC" | "DILR" | "QA")[];      // below the published minimum
    notChecked: ("overall" | "VARC" | "DILR" | "QA")[];    // a minimum exists but no percentile was given
    thresholds: { overall; varc; dilr; qa } | null;        // the minimums used (number | null each)
    notes: string | null; source: OfficialSource | null }[];
  counts: { meets_minimum: number; unknown: number; below_minimum: number };
  methodology: string; limitations: string;   // show both verbatim near the results
  dataFreshness: DataFreshness }
```
  One result per programme that has published thresholds (e.g. IIM Lucknow MBA, MBA-ABM, MBA-SM), else one
  `unknown` result per institute. Uses the institute's latest `policyBatch` and the record for exactly
  `(category, pwd)` — no fallback between categories. Some IIMs (e.g. Jammu, Sirmaur) publish gender-specific
  minimums: the record for the given `gender` is used, else a gender-neutral one; with no `gender` and only
  gender-specific records the result is `unknown` (note asks for gender). A value **equal to** the minimum passes.
  `below_minimum` if any given percentile is below its minimum; otherwise `unknown` if a minimum exists for a
  section the student left out, or no record exists for the category; otherwise `meets_minimum`.
  Sorted meets_minimum → unknown → below_minimum, then by `shortName`. **No admission-probability claims**:
  the status only says whether the published minimums are met. Non-CAT criteria (Class X/XII/graduation
  marks, positive sectional raw score, work experience for MBA-SM) are in `notes` but not checked.

### Student 🔒 (`mbaStudent`)
```ts
type ShortlistStatus = "interested" | "shortlisted" | "applied" | "interview" | "offer" | "declined";
interface ShortlistItem { slug: string; name: string | null; shortName: string | null /* null if the institute is no longer listed */;
  status: ShortlistStatus; deadline: string | null /* YYYY-MM-DD */; notes: string | null; createdAt: string; updatedAt: string }
```
- `GET /me/shortlist` → `{ items: ShortlistItem[] }` (dated deadlines first, earliest first; then undated, most recently updated first)
- `GET /me/shortlist/{slug}` → `ShortlistItem` | 404 (not in shortlist)
- `PUT /me/shortlist/{slug}` body `{ status?: ShortlistStatus /*default "interested"*/; deadline?: string | null; notes?: string | null /*≤2000*/ }`
  → `ShortlistItem`. Full replace of that entry (keeps `createdAt`). 404 if `slug` is not an imported institute,
  422 for a bad status/date, 409 when the shortlist already holds 100 institutes.
- `DELETE /me/shortlist/{slug}` → `{ removed: boolean }` (false if it was not there)

Storage: `mbaShortlists/{userId}` = `{ userId, items: { [slug]: { status, deadline, notes, createdAt, updatedAt } }, updatedAt }`,
written with optimistic concurrency. Programmes are cached in-process for `MBA_BANK_TTL_SECONDS`.

## Exam rules (CAT)
Pattern, durations and marking come from `mbaExams/cat` (seeded from `data/mba/cat_exam.json`,
researched from iimcat.ac.in, with source; versions 2024/2025/2026). Scoring uses the version named
by the paper's `examVersionYear` (snapshotted into the attempt when it starts). Section order is locked when
`sectionOrderLocked` is true; each section has its own timer.

## Implementation notes (backend, v1)
- Practice: `POST /practice/answers` returns 403 for a question that is in the student's
  in-progress attempt (no answer reveal during a live mock). MCQ answers must be an option id (422).
- Attempts: `PATCH responses` → 400 for a question not in the attempt, 409 for a question
  outside the current section or after submission, 422 for an MCQ answer that is not an option id.
  A stale `seq` (≤ `savedSeq`) is ignored and returns the current `savedSeq`. Submitting the last
  section submits the attempt (status `submitted`). When the last section's time is over the
  next read/write scores and submits it. Attempts of other users are 404.
- `Attempt.questions` contains every section's questions (with `sectionIndex`); the client must
  only show the current section.
- Optional fields are returned as `null` when absent (not omitted).
- Mistakes: wrong answer (practice or submitted mock) → due in 1 day; each later answer is a retry;
  correct retries step through 3 → 7 → 14 days, the 4th correct retry clears it, a wrong retry resets to 1 day.
- Dashboard `sections[].attempted/correct` and `totals.questionsAttempted/correct` count distinct
  questions (correct = last answer correct). `mocksCompleted` = submitted attempts (any kind).
  Priority hrefs: `/mba/mocks/attempts/{id}`, `/mba/mocks`, `/mba/mistakes?due=true`,
  `/mba/practice?section=QA`, `/mba/daily`.
- Content is cached in-process for `MBA_BANK_TTL_SECONDS` (default 300).
