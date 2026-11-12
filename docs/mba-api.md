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
| `mbaStudyTasks` | `{userId}_{weekStart}_{date}-{type}[-{section}]` (generated), `{userId}_c_{hex}` (custom) | Study-plan tasks, one doc per task (see "Study planner") |
| `mbaNotificationState` | userId | In-app notification read state: `lastSeenAt`, `dismissed` ids (see "Notifications") |
| `mbaPrograms` | institute slug (`iim-ahmedabad`) | Institute + programmes + embedded official minimum CAT thresholds (Phase D) |
| `mbaCutoffs` | — | Not used: cutoff records are embedded in the `mbaPrograms` doc (tens per institute, always read together) |
| `mbaShortlists` | userId | A student's saved institutes, `items` map keyed by slug (Phase D) |
| `mbaAiUsage` | `{userId}_{yyyy-mm-dd}` | AI tutor quota counters |
| `mbaAttemptAnalyses` | attemptId | Cached AI mock-analyst explanation (generated once per submitted attempt) |
| `mbaQuestionReports` | sha256(userId, questionId) | Student issue reports on questions (one per student per question, editable) |
| `mbaLeaderboardPrefs` | userId | Daily-leaderboard opt-in + display name |
| `mbaDailyResults` | `{yyyy-mm-dd}_{userId}` | Opted-in students' daily-challenge results (first answer per question) |
| `mbaGdpiItems` | item id (`pi-personal-why-mba`) | GDPI guidance: WAT topics, GD topics, PI questions (see "GDPI") |
| `mbaGdpiSessions` | auto | AI mock PI / timed WAT sessions with answers and feedback |
| `mbaCounsellorRequests` | auto (uuid hex) | "Talk to my counsellor" requests (see "Application tracker & counsellor requests") |

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

## Application tracker & counsellor requests

### Document checklist 🔒 (`mbaStudent`)
Built on the shortlist: an application = a shortlist entry + a per-institute document checklist. The checklist is
stored on the entry (`mbaShortlists/{userId}.items.<slug>.checklist`, map `itemId → { done, notApplicable, doneAt,
updatedAt, custom?, label?, createdAt? }`); `PUT /me/shortlist/{slug}` keeps it, `DELETE` removes it with the entry.
Default items (ids fixed; `optional` ones may be marked not applicable): `cat-scorecard`, `graduation`, `class-10-12`,
`id-proof`, `category-certificate`*, `work-experience`*, `sop-essays`*, `fee-receipt` (* optional). Students may add up
to 20 custom items (id `c-` + 8 hex). Official dates come from the bundled data files
(`data/mba/{programs,colleges}/<slug>.json` → `keyDates`), never from the student.
```ts
interface ChecklistItem { id: string; label: string; hint: string | null; custom: boolean; optional: boolean /* may be N/A */;
  done: boolean; notApplicable: boolean; doneAt: string | null }
interface OfficialDates { applicationOpens: string | null /* YYYY-MM-DD or YYYY-MM */; applicationDeadline: string | null;
  examDate: string | null; notes: string | null; sourceUrl: string | null }
interface Application extends ShortlistItem {
  officialDates: OfficialDates | null;
  effectiveDeadline: string | null;          // student's deadline, else the official YYYY-MM-DD application deadline
  deadlineSource: "student" | "official" | null;
  checklist: ChecklistItem[];                 // defaults in fixed order, then custom items oldest first
  progress: { done: number; total: number } } // not-applicable items excluded from both
```
- `GET /me/applications` → `{ items: Application[] }` (sorted like the shortlist, by `effectiveDeadline`)
- `GET /me/applications/{slug}` → `Application` | 404 (not in shortlist)
- `PATCH /me/applications/{slug}/checklist/{itemId}` body `{ done?: boolean; notApplicable?: boolean }` (at least one)
  → `Application`. `notApplicable: true` also clears `done`. 404 not shortlisted / unknown item; 422 empty body,
  unknown field, or `notApplicable` on a required or custom item.
- `POST /me/applications/{slug}/checklist` body `{ label: string /*1-120, whitespace collapsed*/ }` → 201 `Application`.
  409 duplicate label (case-insensitive) or 20 custom items already; 404 not shortlisted.
- `DELETE /me/applications/{slug}/checklist/{itemId}` → `Application` (custom items only; 422 for a default item, 404 unknown).
Every checklist write bumps the entry's `updatedAt` (optimistic concurrency, like the shortlist).

### Counsellor requests
```ts
type CounsellorTopic = "shortlisting" | "applications" | "wat-pi" | "other";
type CounsellorRequestStatus = "open" | "assigned" | "done";
interface CounsellorRequest { id: string; topic: CounsellorTopic; preferredTime: string | null; note: string | null;
  slug: string | null /* institute it is about */; status: CounsellorRequestStatus; assignedTo: string | null /* counsellor name/email, free text */;
  createdAt: string; updatedAt: string; assignedAt: string | null; doneAt: string | null }
interface AdminCounsellorRequest extends CounsellorRequest { userId: string; studentName: string | null; phoneNumber: string | null;
  email: string | null; adminNote: string | null; updatedBy: string | null /* admin email */;
  history: { at: string; by: string /* "student" or admin email */; summary: string }[] /* last 30 */ }
```
Student 🔒:
- `POST /me/counsellor-requests` body `{ topic: CounsellorTopic; preferredTime?: string|null /*≤120*/; note?: string|null /*≤1000*/; slug?: string|null }`
  → 201 `CounsellorRequest` (`status "open"`). 422 bad topic/slug/length or unknown field; 409 when the student already
  has 3 open/assigned requests. Name, phone and email are copied from the student's account.
- `GET /me/counsellor-requests` → `{ requests: CounsellorRequest[] }` newest first.

Admin 🛡 (same auth and roles as "Admin content review": `MBA_CONTENT_ADMIN_ROLES`, default `superAdmin,COURSE`):
- `GET /admin/counsellor-requests?status=&topic=&q=` → `{ requests: AdminCounsellorRequest[]; counts: { open; assigned; done } }`
  newest first; `counts` ignore the filters; `q` = substring of name / phone / email / assignee / note / slug. 422 bad filter.
- `PATCH /admin/counsellor-requests/{id}` body `{ status?: CounsellorRequestStatus; assignedTo?: string|null /*≤200*/; adminNote?: string|null /*≤2000*/ }`
  → `AdminCounsellorRequest`. Without `status`, setting `assignedTo` on an open request makes it `assigned` and clearing it
  re-opens an assigned one. `assigned` without an assignee → 422. `done` sets `doneAt` (cleared on re-open). Empty body 422,
  unknown id 404. A patch that changes nothing writes nothing. Each change appends a `history` entry.

## GDPI — WAT / GD / PI preparation 🔒 (`mbaStudent`)

**Content.** ProCounsel-original guidance (no copied coaching material, no dated news or statistics) in
`data/mba/gdpi/{wat,gd,pi}.json` → `scripts/mba/import_gdpi.py` → `mbaGdpiItems/{id}` (`status: "published"` by
default; idempotent `set`; items dropped from the files are archived, never deleted). Students only see `published`
items. Sessions live in `mbaGdpiSessions/{auto id}` = `{ userId, kind, status, title, focus, background,
durationMinutes, startedAt, endsAt, completedAt, questions: GdpiItem-snapshot[], answers: { [questionId]: {
answerText, wordCount, overtime, feedback, answeredAt } }, updatedAt }`.

```ts
type GdpiKind = "wat" | "gd" | "pi";
type TopicGroup = "business" | "economy" | "technology" | "society" | "abstract";            // WAT + GD
type PiGroup = "personal" | "academics" | "work" | "current_affairs" | "hobbies" | "situational" | "stress";
type Background = "engineering" | "commerce" | "arts" | "science";                          // PI academics only
interface GdpiItem { id: string; kind: GdpiKind; group: TopicGroup | PiGroup; prompt: string /* topic or question */;
  framing: string /* WAT/GD: framing note; PI: what the panel is assessing */;
  lookFor: string[] /* WAT/GD: what evaluators look for */; angles: { angle: string; forView: string; againstView: string }[] /* GD: 3-4 */;
  structure: string[] /* strong answer / essay structure */; avoid: string[] /* pitfalls */; background: Background | null;
  source: { kind: "original"; title: string } }
interface FeedbackScores { structure: number; clarity: number; relevance: number; completeness: number }   // integers 1-5
interface Feedback { scores: FeedbackScores | null /* null only when fallback */; strengths: string[]; improvements: string[];
  betterOutline: string[]; fallback: boolean /* AI reply unusable: outline = the question's guidance; not counted against quota; may resubmit */ }
interface SessionAnswer { questionId: string; answerText: string; wordCount: number; overtime: boolean /* WAT: > endsAt + 60 s */; feedback: Feedback; answeredAt: string }
interface GdpiSession { id: string; kind: "pi" | "wat"; status: "in_progress" | "completed"; title: string; focus: string | null;
  background: Background | null; durationMinutes: 15 | 20 | null /* WAT */; startedAt: string; endsAt: string | null /* WAT */; serverNow: string;
  completedAt: string | null; questions: GdpiItem[] /* PI: 5, WAT: 1 */; answers: SessionAnswer[] /* in question order */;
  summary: { answered: number; total: number; averageScores: FeedbackScores | null; overall: number | null /* mean, 1 dp */ } }
interface GdpiSessionSummary { id; kind; status; title; focus: string | null; answered: number; total: number; overall: number | null; startedAt: string; completedAt: string | null }
```

- `GET /gdpi/items?kind=wat|gd|pi&group=&background=` → `{ items: GdpiItem[] }` (all filters optional; sorted kind,
  group, background, id; 422 for an unknown kind / group / background). Cached in-process for `MBA_BANK_TTL_SECONDS`.
- `POST /me/gdpi/sessions` body `{ kind: "pi" | "wat"; focus?: string; background?: Background /*PI*/; itemId?: string /*WAT topic*/;
  durationMinutes?: 15 | 20 /*WAT, default 15*/ }` → `GdpiSession`.
  PI picks 5 distinct questions from the bank: no focus → personal, personal, academics (of `background`; any background
  when omitted — the profile has no background field, so the client sends it), situational, one of work / hobbies /
  current affairs / stress. `focus` (a `PiGroup`) → personal, 3 × focus, situational (academics when focus is situational;
  focus personal → 3 personal + academics + situational). WAT uses `itemId` (404 if not a published WAT topic) or a random
  topic of `focus` (a `TopicGroup`) and sets `endsAt = startedAt + durationMinutes`. 422 for a bad focus or a field of the
  other kind; 409 when the bank is not imported; **503 when `OPENAI_API_KEY` is not set**.
- `GET /me/gdpi/sessions` → `{ sessions: GdpiSessionSummary[] }` (newest first, max 50).
- `GET /me/gdpi/sessions/{id}` → `GdpiSession` (404 if not the caller's).
- `POST /me/gdpi/sessions/{id}/answers` body `{ questionId: string; answerText: string }` → `{ answer: SessionAnswer; session: GdpiSession; remainingToday: number }`.
  `answerText` is trimmed; 20 – 2,000 characters for PI, 20 – 3,000 for a WAT essay (422). 404 unknown session / question,
  409 when the question already has (non-fallback) feedback. AI feedback (OpenAI JSON mode, validated; scores clamped to
  1–5; outcome claims filtered) is grounded only in the student's text and the question's guidance — it must not invent
  facts about the student, add statistics/news or predict admission outcomes. Each successful feedback counts once against
  the **shared** AI quota (`mbaAiUsage`, same counter and `MBA_AI_DAILY_LIMIT` as `/ai/hint`) → **429** when exhausted
  (checked before the model call). 503 when not configured or the model call fails. The session becomes `completed`
  when every question has an answer. A WAT essay submitted after `endsAt` (+60 s grace) is accepted with `overtime: true`.

## Study planner 🔒 (`mbaStudent`)
Deterministic, rule-based weekly plan (`planner-v1`, no AI); the rules applied are returned in `basis.rules`.
Weeks run Monday–Sunday (India time); `week` is any date in the week (default: this week).
Rules: weekly hours split evenly over `studyDays` (others = rest days); nothing on/after the exam date, light
revision only the day before; mocks/week by weeks left: > 8 → 1, 5–8 → 2, final 4 → 3 (1 with no date), never on
back-to-back days, ≤ 60% of the week's time (full → sectional, then dropped); first mock is a full diagnostic if
none submitted; beginners > 8 weeks out get sectionals of their weakest section; practice blocks weighted per
section `1 + 2·max(0, 0.75 − accuracy)` (≥ 5 answered, else 1) and name the weakest topic (≥ 3 answered, < 60%);
due mistakes → revision every third study day; daily challenge (10 min) on study days with ≥ 30 min; learn sessions
(30 min) beginner 2 / intermediate 1 / advanced 0 a week, none in the final 4 weeks. Exam date = profile `examDate`,
else the official CAT date from `data/mba/exams/cat.json`.
```ts
type PlanTaskType = "practice" | "sectional_mock" | "full_mock" | "revise_mistakes" | "daily_challenge" | "learn" | "custom";
interface PlanTask { id: string; date: string /*YYYY-MM-DD*/; type: PlanTaskType; title: string; detail: string | null;
  section: SectionId | null; topic: string | null; questionCount: number | null; minutes: number;
  href: string | null /* /mba/practice?section=QA, /mba/mocks, /mba/mistakes?due=true, /mba/daily, /mba/learn */;
  status: "pending" | "done" | "skipped"; source: "generated" | "custom"; generatedBy: string | null /* "planner-v1" */;
  edited: boolean; autoCompleted: boolean; completedAt: string | null; createdAt: string; updatedAt: string }
interface WeekPlan { weekStart: string; weekEnd: string; today: string; generated: boolean; canGenerate: boolean;
  days: { date: string; weekday: number /*0=Sun*/; rest: boolean; examDay: boolean; plannedMinutes: number; tasks: PlanTask[] }[]; // 7, Mon..Sun
  summary: { planned: number; done: number; skipped: number; pending: number; plannedMinutes: number; doneMinutes: number }; // minutes exclude skipped
  basis: { ruleVersion: string; examDate: string | null; examDateSource: "profile" | "official" | null; weeksToExam: number | null;
    weeklyStudyHours: number; studyDays: number[]; minutesPerStudyDay: number; level: string; mocksThisWeek: number; mistakesDue: number;
    sections: { id: SectionId; attempted: number; accuracy: number | null; weight: number }[]; rules: string[] } }
```
- `GET /me/plan?week=YYYY-MM-DD` → `WeekPlan`. Does not generate. Auto-completes pending tasks from real activity:
  a mock submitted that week completes one planned mock of the same kind (full/sectional); a practice task is done
  once that many distinct questions of its section were answered that day; the daily challenge once all of that
  day's questions are answered; a revision task once that many earlier mistakes were retried that day.
- `POST /me/plan/generate?week=` → `WeekPlan`. Idempotent. Creates/replaces only pending, unedited, generated tasks
  dated today or later; removes such tasks the new plan no longer has. Done, skipped, edited (moved/renamed) and custom
  tasks are never changed and count against their day's time and the week's mocks. 409: week already over, or no profile.
- `PATCH /me/plan/tasks/{id}` body `{ status?: "pending"|"done"|"skipped"; date?: YYYY-MM-DD /*reschedule, ±1 year*/; title?: string(1-120); minutes?: 5-600 }`
  → `PlanTask` (moving/renaming sets `edited`). 404 not found / not yours, 422 empty or invalid body.
- `POST /me/plan/tasks` body `{ date; title; minutes; type?: PlanTaskType /*default custom*/; section?; href?: "/mba/..."; detail?: string(≤500) }`
  → 201 `PlanTask` (`source: "custom"`). 409 over 50 custom tasks in that week; 422 invalid (e.g. external href).
- `DELETE /me/plan/tasks/{id}` → `{ deleted: true }` — custom tasks only (409 for planned tasks: skip them instead).

## Notifications 🔒 (`mbaStudent`)
Computed on each request from real state (no cron): `resume_mock` (in-progress attempt), `plan_today` (pending tasks
today), `plan_overdue` (pending tasks from earlier this week), `mistakes_due`, `cat_countdown` (30/14/7/1 day
milestones and exam day; profile date, else official), `shortlist_deadline` (shortlist deadline within 7 days, not
declined/offer), `new_mock` (paper `publishedAt` within 14 days and not attempted).
```ts
interface MbaNotification { id: string /* stable while the condition lasts; day-scoped ones change daily */;
  kind: "plan_today" | "plan_overdue" | "mistakes_due" | "resume_mock" | "cat_countdown" | "shortlist_deadline" | "new_mock";
  title: string; detail: string; href: string /* in-app path */; at: string /* ISO */; unread: boolean }
```
- `GET /me/notifications` → `{ items: MbaNotification[] /* unread first, newest first */; unreadCount: number; lastSeenAt: string | null }`
  `unread` = `at` after `lastSeenAt`. Dismissed ids are left out.
- `PATCH /me/notifications/seen` body (optional) `{ dismissIds?: string[] /*≤50*/ }` → `{ lastSeenAt: string; dismissed: number }`
  Sets `lastSeenAt` = now and hides the given ids (last 200 kept). Storage: `mbaNotificationState/{userId}`.

## Mock analyst, insights, question reports, daily leaderboard 🔒 (`mbaStudent`; admin parts 🛡)

### Mock analyst
The analysis is **deterministic** (computed from recorded data only); the AI is an optional explanation
layer on top of it. Neither ever includes answer keys or solutions, and both are 404 until the attempt is submitted
(also 404 for another student's attempt).
```ts
type Outcome = "correct" | "incorrect" | "skipped";
interface QuestionRef { questionId: string; section: SectionId; number: number /* 1-based within the section, as on the result page */;
  topic: string | null; difficulty: "easy" | "medium" | "hard" | null; outcome: Outcome; timeSpentMs: number }
interface Bucket { total: number; attempted: number; correct: number; incorrect: number; skipped: number; accuracy: number | null /* 0-1 */ }
interface PracticeLink { id: string /* "section:QA" | "topic:QA:Algebra" | "mistakes" */; label: string; href: string /* in-app */ }
interface DeterministicAnalysis { attemptId; title; submittedAt; score; maxScore; questionCount: number; attempted: number;
  lowEvidence: boolean /* attempted < 10 */; evidenceNote: string | null;
  sections: { id: SectionId; questionCount; score; maxScore; attempted; correct; incorrect; unanswered; accuracy: number | null;
    timeSpentMs; medianTimeMs: number | null /* null with < 3 timed questions */ }[];
  byDifficulty: (Bucket & { difficulty: "easy" | "medium" | "hard" | "unrated" })[];
  byTopic: (Bucket & { section: SectionId; topic: string; timeSpentMs: number })[];
  missedEasy: QuestionRef[];                 // easy questions skipped or wrong (max 8)
  timeSinks: (QuestionRef & { sectionMedianMs: number; ratio: number })[];  // wrong/skipped, time > 2× section median (max 8, longest first)
  selection: { easySkipped; easyIncorrect; hardAttempted; hardCorrect; timeOnIncorrectMs; timeOnHardIncorrectMs; timeSinkCount };
  links: PracticeLink[] }                    // the only destinations the AI may point to
interface AiAnalysis { summary: string /* ≤120 words */; strengths: string[] /* ≤3; fewer when the facts don't support 3 */;
  priorities: { title: string; detail: string; nextSteps: string[] /* ≤3 */; link: PracticeLink }[] /* 1-3 */;
  selectionAdvice: string; generatedAt: string; model: string }
interface AttemptAnalysisResponse { attemptId: string; analysis: DeterministicAnalysis; ai: AiAnalysis | null; remainingToday: number | null }
```
- `GET /me/attempts/{id}/analysis` → `AttemptAnalysisResponse` (`ai` = the cached explanation or `null`; never calls the model).
- `POST /me/attempts/{id}/analysis` → `AttemptAnalysisResponse`. Generates the explanation once and caches it in
  `mbaAttemptAnalyses/{attemptId}`; later calls return the cache (no quota). The model sees only the deterministic facts
  (no ids, answers or solutions); its link choices are mapped onto `links` (unknown → "mistakes"); HTML is stripped.
  **503** not configured / model failed / unreadable output, **429** daily AI quota (shared with the tutor, `mbaAiUsage`).
  On 503/429 the client keeps showing the `GET` analysis.

### Insights (weakness detector)
- `GET /me/insights` →
```ts
{ topics: { section: SectionId; topic: string; questions: number /* distinct answered */; attempts: number /* all answers, practice+daily+mocks */;
    correct: number; accuracy: number | null; avgTimeMs: number | null /* from submitted mocks only */; timedAnswers: number;
    confidence: "sufficient" | "low" /* attempts ≥ 8 */; status: "weak" | "ok" | "strong" | "low_evidence"; href: string }[];  // sorted section, topic
  weakTopics: Topic[] /* status "weak" (≥ 8 attempts and accuracy < 0.6), worst first, max 5 */; lowEvidenceCount: number;
  trend: { attemptId; title; kind: "full_mock" | "sectional" | string; submittedAt; score; maxScore;
    sections: { id: SectionId; score; maxScore; accuracy: number | null }[] }[] /* last 5 submitted attempts, oldest first */;
  rules: { minAttempts: 8; weakBelow: 0.6; strongFrom: 0.8 } }
```
  Topics with < 8 answers are never flagged weak (`low_evidence`). `href` = `/mba/practice?section=QA&topic=…`
  (the practice page reads `section` and `topic`).

### Question reports
```ts
type ReportCategory = "wrong_answer" | "unclear" | "typo" | "solution_error" | "other";
type ReportStatus = "open" | "resolved" | "rejected";
interface MyReport { questionId; category: ReportCategory; note: string | null; status: ReportStatus; createdAt; updatedAt }
```
- `GET /questions/{id}/reports` → `{ report: MyReport | null }` (the caller's own report).
- `POST /questions/{id}/reports` body `{ category: ReportCategory; note?: string /*≤1000*/ }` → `MyReport`. Creates or edits the
  caller's single report for that question. Only after the answer was revealed to the student (answered in practice/daily,
  or the question was in one of their submitted attempts) → **403** otherwise, and 403 while the question is in their running mock.
  404 unknown/unpublished question, 422 bad body (unknown fields rejected). An unchanged save is a no-op. Editing a
  resolved/rejected report reopens it. **429**: > 20 distinct reports created/edited per IST day, or > 5 saves of one report per day.
- 🛡 `GET /admin/reports?status=&paperId=&questionId=` → `{ reports: AdminReport[]; counts: { open; resolved; rejected } }`
  (`counts` ignore the `status` filter; sorted open → resolved → rejected, newest first). No reporter identity is returned.
```ts
interface AdminReport { id: string /* opaque */; questionId; paperId: string | null; section: SectionId | null; number: number | null;
  stemPreview: string /* ≤160 chars plain text */; category: ReportCategory; note: string | null; status: ReportStatus;
  adminNote: string | null; resolvedBy: string | null /* admin id */; resolvedAt: string | null; createdAt; updatedAt }
```
- 🛡 `PATCH /admin/reports/{id}` body `{ status: ReportStatus; note?: string | null /*≤2000*/ }` → `AdminReport` (404 unknown).
  Same auth as the other admin endpoints (`MBA_CONTENT_ADMIN_ROLES`).

### Daily challenge leaderboard (opt-in)
- `GET /me/leaderboard` → `{ optedIn: boolean; displayName: string; suggestedName: string }` (suggestion = first name + last initial).
- `PUT /me/leaderboard` body `{ optedIn: boolean; displayName?: string /*≤60 in, stored ≤24*/ }` → same. The name keeps letters,
  digits, spaces and `.'-`; a short list of abusive words is dropped; 422 if fewer than 2 characters remain.
- `GET /leaderboard/daily?date=YYYY-MM-DD` (default today IST, within the last 30 days, else 422) →
  `{ date; questionCount; participants; optedIn: boolean /* the caller */; entries: DailyEntry[] /* top 20 */; you: DailyEntry | null; rule: string }`
  with `DailyEntry = { rank; displayName; answered; correct; accuracy /*0-1*/; isYou }`. Ranked by accuracy, then by how many
  of the day's questions were answered (ties share a rank). Only the **first** result per question per day counts.
- `GET /leaderboard/weekly?date=` (week = 7 days ending `date`) → `{ weekStart; weekEnd; participants; optedIn; entries: WeeklyEntry[]; you; rule }`,
  `WeeklyEntry = { rank; displayName; daysActive; answered; accuracy; previousAccuracy: number | null; improvement: number | null /* accuracy − previous week's */; isYou }`.
  Ranked by days active, then improvement, then accuracy.
- Never ranks by volume or study hours; never returns userIds or phone numbers; only opted-in students appear (non-opted
  callers still see the board and `optedIn: false`). Results are recorded into `mbaDailyResults` from `mbaQuestionStats` for the
  current day when a board is read (boards cached ~60 s per instance); past days use only what was recorded on the day.
