# ProCounsel MBA — API contract (v1)

Source of truth for backend (procounsel-neet-api) and frontend (Website). Change this
file first, then the code. Base path: `/api/v1/mba`. JSON, camelCase.

## Principles
- **Real data only.** Every question, exam rule, cutoff, fee or placement figure stores a
  `source` (`{kind, title, url, year, retrievedAt}`). Nothing is invented. Missing data is
  shown as missing (e.g. an exam section's `questionCount` is `null` until officially announced).
- **Question bank = ProCounsel originals + previous-year papers.** ProCounsel ORIGINAL CAT-pattern
  questions (`source.kind: "original"`, AI-drafted, faculty-reviewed) and actual past CAT papers
  (PYQs: paper `year` + `slot` set, `source.kind: "official"`; see "Previous-year papers"). Content has `status: "draft" | "published" |
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
| `mbaAttempts` | auto | One attempt of a test by a student (state, responses, result); built tests are attempts with `kind: "drill"` (see "Practice modes") |
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
| `mbaTestScoreStats` | testId | Histogram of every student's FIRST submitted score on a test: `{testId, paperId, count, scores: {"<int score>": n}, updatedAt}` (ProCounsel percentile) |
| `mbaDoubts` | auto (uuid hex) | Doubt threads on a question (`scope: "question"`) and study-group posts (`scope: "group"`), replies embedded (see "Community") |
| `mbaGroupMembers` | userId | The student's study group (`{exam}-{year}`, e.g. `cat-2026`) |
| `mbaCommunityUsage` | `{userId}_{yyyy-mm-dd}` | Per-day post / report / ticket counters + last post time (rate limits) |
| `mbaSupportTickets` | auto (uuid hex) | Help-centre tickets with the message thread |
| `mbaEvents` | auto (uuid hex) | Admin-managed doubt hours and webinars |
| `mbaCounsellorRequests` | auto (uuid hex) | "Talk to my counsellor" requests / MBA leads: pipeline, counsellor assignment, follow-up notes, sharing consent (see "Application tracker & counsellor requests") |
| `mbaApplicationDocs` | 32 hex | Application document metadata; the files live in Firebase Storage under `mba/applications/{userId}/{slug}/{itemId}/{uuid}.{ext}` (see "Application documents") |
| `mbaExamUpdates` | uuid hex | Admin-posted exam updates (admit card, answer key, result...) with a required official source URL (see "Exam updates") |
| `mbaCoachChats` | `{userId}_{varc\|dilr\|quant}`, `{userId}_plan` | AI section coach chats (last 20 turns, 7-day TTL) and the cached "explain my plan" text (see "AI section coaches") |
| `mbaSyllabusProgress` | `{userId}_{subtopicId}` | Syllabus lesson progress per student per subtopic: completed mark, bookmark, private note (see "Syllabus") |

## Shared types
```ts
type Source = { kind: "official" | "licensed" | "faculty" | "original"; title: string; url?: string; year?: number; retrievedAt?: string };
// url is required for "official" and "licensed"; optional for "original" / "faculty".
type SectionId = "VARC" | "DILR" | "QA";   // CAT; CAT-only features (drills, planner, estimator, dashboard rings) use it
type ExamSectionId = string;              // any exam's section id, /^[A-Z][A-Z0-9]{0,11}$/, validated against the exam config
type ExamId = "cat" | "xat" | "snap" | "nmat" | "cmat" | "mat" | "gmat" | "mah-mba-cet";
type QuestionType = "MCQ" | "TITA";

interface ExamSection { id: ExamSectionId; name: string; questionCount: number | null /* null = not announced */;
  durationMinutes: number | null /* null = no timer of its own (shares a timer block) */;
  countsInTotal: boolean /* false: scored and shown on its own, not in score/maxScore (XAT GK) */ }
interface MarkingRule { type: QuestionType; correct: number; incorrect: number; unanswered: number;
  sections: ExamSectionId[] | null /* null = every section; XAT: Part 1 rule vs GK rule */ }
interface TimerBlock { id: string /* a one-section block has that section's id */; name: string | null;
  sectionIds: ExamSectionId[]; durationMinutes: number }   // sections sharing one timer; free movement between them
interface ExamVersion { year: number; sections: ExamSection[]; marking: MarkingRule[]; totalDurationMinutes: number;
  sectionOrderLocked: boolean /* false: the student picks the order of the timer blocks (NMAT, GMAT) */; source: Source;
  timerBlocks: TimerBlock[] | null /* null = every section is its own block (CAT) */;
  unansweredPenalty: { sections: ExamSectionId[]; freeCount: number; marks: number } | null /* XAT: -0.10 per unanswered after 12 */;
  scoring: "official" | "practice" /* practice = not the exam's own scaled/adaptive score (NMAT, GMAT, MAT) */;
  scoringNote: string | null /* plain-language marking/timing summary for the instructions screen */ }
interface Exam { id: ExamId; name: string; conductingBody: string; officialUrl: string; versions: ExamVersion[];
  adaptive: boolean /* the real exam is computer-adaptive (NMAT, GMAT); ours is a fixed-form practice test */ }

interface QuestionSet { id: string; kind: "passage" | "dilr_set" | "data"; title?: string; contentHtml: string; images?: string[] }
interface QuestionPublic {        // what students receive
  id: string; examId: ExamId; paperId?: string; section: ExamSectionId; topic?: string; subtopic?: string;
  type: QuestionType; stemHtml: string; options?: { id: string; textHtml: string }[];  // MCQ only
  setId?: string; set?: QuestionSet; difficulty?: "easy" | "medium" | "hard";
  year?: number; slot?: number; source: Source;
  isPyq: boolean;                 // from an actual past CAT paper — label "CAT {year} Slot {slot}"
}
interface QuestionReveal { correctAnswer: string; solutionHtml?: string; isCorrect?: boolean;  // MCQ: option id; TITA: exact string
  alternativeApproaches?: string[] | null;  // other ways to solve it (HTML, ≤ 5), shown after the main solution
  videoUrl?: string | null }                // video solution, always an https:// URL (YouTube etc.)
// alternativeApproaches / videoUrl are solution content: like solutionHtml they are never in QuestionPublic.
```

## Public endpoints
- `GET /exams` → `{ exams: Exam[] }`
- `GET /exams/{examId}` → `Exam`
- `GET /papers?examId=cat|xat|snap|…` (default `cat`) → `{ papers: { id, title, examVersionYear, year: number|null, slot: number|null, questionCount, sections: {id, questionCount}[], source, isPyq: boolean }[] }`
  Only papers whose paper doc and every question are `published` are listed, and only inside their optional
  schedule window (`availableFrom` ≤ now < `availableUntil`, see "Admin authoring → Scheduling").

## Student endpoints 🔒
### Profile / onboarding
- `GET /me/profile` → `MbaProfile | 404` (404 = not onboarded)
- `PUT /me/profile` body `MbaProfileInput` → `MbaProfile`
```ts
interface MbaProfileInput { targetExam: "cat"; examDate?: string /*YYYY-MM-DD*/; targetPercentile?: number /*0-100*/;
  currentLevel: "beginner" | "intermediate" | "advanced"; weeklyStudyHours: number /*1-80*/; studyDays: number[] /*0=Sun..6*/;
  targetPrograms?: string[];
  targetExams?: ExamId[] | null /* multi-select; de-duplicated, returned in ExamId order; null = CAT only */ }
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
- `GET /questions?examId=cat&section=&topic=&year=&slot=&paperId=&source=all|pyq|original&filter=all|unsolved|incorrect|bookmarked&limit=20&cursor=` → `{ questions: QuestionPublic[]; nextCursor: string | null }`
  Each returned question also has `bookmarked: boolean`. `accuracy` fields everywhere are fractions 0–1.
  `examId` (default `cat`) limits practice to one exam; `section` is any section id of that exam.
- `POST /practice/answers` body `{ questionId, answer, timeSpentMs, confidence?: Confidence }` → `QuestionReveal & { stats: { attempts, correct } }`
- `PUT /me/bookmarks/{questionId}` / `DELETE /me/bookmarks/{questionId}` → `{ bookmarked: boolean }`
- `GET /me/mistakes?examId=&section=&due=true` (no `examId` = every exam) → `{ items: { question: QuestionPublic; lastAnswer: string; category?: MistakeCategory; note?: string; nextReviewAt?: string; retries: number }[] }`
- `PATCH /me/mistakes/{questionId}` body `{ category?: MistakeCategory; note?: string }` → item
  `type MistakeCategory = "concept" | "calculation" | "misread" | "selection" | "time_pressure" | "guess"`
- `GET /daily` → `{ date: string; questions: QuestionPublic[]; completed: number }` (5–10 published CAT questions, same for everyone per day, deterministic; `date` and `completed` use India time)

### Tests & attempts
- `GET /tests?examId=cat&source=all|pyq|original` → `{ tests: { id, title, kind: "full_mock" | "sectional", paperId, paperTitle, sections: ExamSectionId[], durationMinutes, questionCount,
  isPyq: boolean, year: number|null, slot: number|null, examVersionYear: number|null,
  examId: ExamId, timerBlocks: TimerBlock[], sectionOrderLocked: boolean }[] }`
  Derived from each offered paper of the exam (`examId`, default `cat`): `{paperId}-full` plus one sectional
  `{paperId}-{section}` per section that is a timer block of its own (CAT: varc/dilr/qa; NMAT/GMAT: each section;
  XAT: gk only; SNAP/CMAT/MAT/MAH-CET: none, as they state no per-section time). Durations/marking from the exam
  version `paper.examVersionYear`. A paper is not offered while its version lacks a timer for a section or a
  marking rule for a question type. Empty if the exam config is not seeded.
- `POST /attempts` body `{ testId; sectionOrder?: string[] }` → `Attempt` — returns the existing in-progress attempt for this test if any (resume), else creates.
  `sectionOrder` (timer-block ids, each once) is the student's chosen order; honoured only when the test's
  `sectionOrderLocked` is false (NMAT, GMAT), 422 if it does not list every block exactly once, ignored otherwise.
  409 while another in-progress attempt of the student shares questions with this test (e.g. the paper's
  full mock is running and a sectional of the same paper is requested) — submitting it would reveal live answers.
- `GET /attempts/{id}` → `Attempt` (questions without answers; `serverNow` + `sectionEndsAt` for timers)
- `PATCH /attempts/{id}/responses` body `{ seq: number; responses: { questionId, answer: string | null, markedForReview: boolean, timeSpentMs: number, confidence?: Confidence | null }[] }` → `{ savedSeq: number }`. Ignores stale `seq`. Rejects answers outside the current timer block, or after its time is over (409).
- `POST /attempts/{id}/sections/{sectionId}/submit` → `Attempt` (closes the current timer block — `sectionId` may be the
  block id or any section in it — and opens the next; auto-applied by server when time is up)
- `POST /attempts/{id}/submit` → `AttemptResult` (idempotent: second call returns same result)
- `GET /attempts/{id}/result` → `AttemptResult` (404 until submitted)
- `GET /me/attempts` → `{ attempts: AttemptSummary[] }`
```ts
interface Attempt { id: string; testId: string; title: string; status: "in_progress" | "submitted";
  currentSection: ExamSectionId /* first section of the current block */; sectionOrder: ExamSectionId[];
  sectionEndsAt: string /* end of the current timer block */; serverNow: string;
  questions: (QuestionPublic & { sectionIndex: number })[];
  responses: Record<string, { answer: string | null; markedForReview: boolean; timeSpentMs: number; confidence: Confidence | null }>; savedSeq: number;
  examId: ExamId; timerBlocks: TimerBlock[] /* attempt order; CAT: one per section */; currentBlock: string | null }
interface AttemptSummary { id; testId; title; status; startedAt; submittedAt?: string; score?: number; maxScore?: number }
interface AttemptResult { id; testId; title; submittedAt; score; maxScore;
  sections: { id: ExamSectionId; score; maxScore; attempted; correct; incorrect; unanswered; accuracy: number | null; timeSpentMs;
    countsInTotal: boolean /* false: not in score/maxScore (XAT GK) */; penalty: number /* unanswered penalty included in score (XAT) */ }[];
  questions: (QuestionPublic & QuestionReveal & { yourAnswer: string | null; timeSpentMs: number; marks: number; confidence: Confidence | null })[];
  confidence: ConfidenceBreakdown /* see "Practice modes" */;
  isPyq: boolean; year: number | null; slot: number | null;
  procounselPercentile: ProcounselPercentile | null; examId: ExamId }
// Standing among ProCounsel students' FIRST submitted attempts of the same test (never an official CAT percentile).
interface ProcounselPercentile { percentile: number | null /* 0–100; null until ≥ minStudents others */; students: number /* others compared */;
  minStudents: 20; score: number; basis: "first_attempt"; note: string }
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
(read-only) and its `role` must have the endpoint's capability (see "Admin roles" below: reads need
`content` or `tests`; question/set edits and review need `content`; publish/unpublish need `tests`).
401 = missing/invalid/expired token, 403 = not an admin / role not allowed.
These endpoints read every status (not the published-only cache) and clear the content cache
after every write, so students see changes immediately on that instance (other serverless
instances within `MBA_BANK_TTL_SECONDS`). Writes only touch `mbaQuestions`, `mbaQuestionSets`, `mbaPapers`.

```ts
type ContentStatus = "draft" | "published" | "archived";
// draft = not flagged draft, flagged = draft flagged by a reviewer, archived = rejected (or dropped by a re-import),
// missing = id listed in the paper but no question doc
interface StatusCounts { draft: number; flagged: number; published: number; archived: number; missing: number }
interface AdminPaper { id; title; status: ContentStatus; examId: string /* "cat", "xat", … */; examVersionYear: number|null; year: number|null; slot: number|null;
  questionCount: number; counts: StatusCounts; sections: { id: SectionId; questionCount: number; counts: StatusCounts }[];
  readyToPublish: boolean /* ≥1 question and all published */; source: Source|null;
  updatedAt: string|null; publishedAt: string|null; publishedBy: string|null;
  version: number; history: HistoryEntry[] /* paper edits: header, schedule, added/removed/reordered questions */;
  availableFrom: string|null; availableUntil: string|null; schedule: "always"|"upcoming"|"live"|"ended" }
interface AdminSet { id; kind: "passage"|"dilr_set"|"data"; title: string|null; contentHtml: string; images: string[]|null; version: number; updatedAt: string|null;
  key: string|null; section: SectionId|null; status: ContentStatus }
interface HistoryEntry { version: number; editedBy: string /* admin id */; editedAt: string; changes: string[] /* field names */; summary: string }
interface AdminQuestion { id; key: string|null; paperId: string|null; section: SectionId; number: number|null; type: QuestionType;
  stemHtml: string; options: {id; textHtml}[]|null; setId: string|null; set: AdminSet|null; topic: string|null; subtopic: string|null;
  difficulty: "easy"|"medium"|"hard"|null; correctAnswer: string; solutionHtml: string|null;
  alternativeApproaches: string[]|null; videoUrl: string|null; source: Source;
  status: ContentStatus; flagged: boolean; reviewAction: "approved"|"rejected"|"flagged"|null; reviewNote: string|null;
  reviewedBy: string|null; reviewedAt: string|null; version: number /* 1 for imported content */; history: HistoryEntry[] /* last 50 */;
  updatedAt: string|null }
```

- `GET /papers?examId=` → `{ papers: AdminPaper[] }` — every paper, any status (sorted like the public list); `examId`
  (optional) keeps only that exam's papers (papers without `examId` count as `cat`).
- `GET /papers/{paperId}/questions` → `{ paper: AdminPaper; questions: AdminQuestion[]; sets: AdminSet[] }` — questions in
  paper order (section, then number); includes the answer key, solution and set. `sets` = every non-archived set of
  the paper (also ones no question uses yet). 404 unknown paper.
- `PATCH /questions/{id}` body (only sent fields change; `null` clears an optional one)
  `{ stemHtml?; options?: {id; textHtml}[]; answer?: string|number; solutionHtml?: string|null;
  alternativeApproaches?: string[]|null /* ≤ 5 HTML strings; blank entries dropped; [] or null clears */;
  videoUrl?: string|null /* https:// only */; topic?: string|null;
  subtopic?: string|null; difficulty?: "easy"|"medium"|"hard"|null; type?: "MCQ"|"TITA"; setId?: string|null;
  source?: SourceInput; expectedVersion?: number }` → `AdminQuestion`.
  The merged question is validated with the importer's own code (`scripts/mba/paper_format.py::check_question`: stem
  required; MCQ ≥2 options with unique short alphanumeric ids and `answer` one of them; TITA no options, answer 1–50
  chars; set of the same paper and section; source rules) → 422 with the problems joined by `; `. Switching to TITA
  drops the options. Unknown fields 422; empty body 422. `section` is not editable. A real change bumps `version`
  and appends a `history` entry; an edit that changes nothing is a no-op. `expectedVersion` ≠ current → 409.
  Status is not changed by edits (re-review is a separate action). 404 unknown id.
- `PATCH /sets/{id}` body `{ contentHtml?; title?: string|null; kind?: "passage"|"dilr_set"|"data"; images?: string[]|null
  /* http(s) URLs, ≤20 */; expectedVersion? }` → `AdminSet` (same version/history, 409 and 404 rules; validated with
  `check_set`: empty `contentHtml` or a non-http(s) image 422).
- `POST /questions/{id}/review` body `{ action: "approve"|"reject"|"flag"; note?: string (≤2000) }` → `AdminQuestion`.
  approve → `status "published"` (422 if the question fails validation); reject → `"archived"`; flag → `"draft"` with
  `flagged: true` (a note is required, 422 otherwise; flagging a published question takes it out of student use).
  Every action sets `reviewAction`, `reviewNote` (= the note, `null` if none), `reviewedBy` (admin id), `reviewedAt`.
- `POST /papers/{paperId}/publish` → `AdminPaper`. 409 unless the paper has questions and **every** one is
  `published` (`detail` says how many are not); 422 if the whole paper fails the importer's validation
  (`build_paper_docs`). Sets `status "published"`, `publishedAt`, `publishedBy`. Idempotent.
- `POST /papers/{paperId}/unpublish` → `AdminPaper` (`status "draft"`, `unpublishedAt/By`). Idempotent.

### Admin roles 🛡
The role is the `role` field of the Java `admins/{email}` doc (read-only). Four capabilities, each = the roles in
`MBA_CONTENT_ADMIN_ROLES` (default `superAdmin,COURSE`, the old single setting — so existing admins keep full access)
+ one MBA role (override with its env, comma-separated; `*` anywhere = every admin); `superAdmin` always has all:

| capability | unlocks | default extra role | env |
|---|---|---|---|
| `content` | create/edit/archive questions and sets, review (approve/flag/reject) | `mbaFaculty` | `MBA_ADMIN_ROLES_CONTENT` |
| `tests` | create/import/edit/schedule/archive papers, publish/unpublish | `mbaTestManager` | `MBA_ADMIN_ROLES_TESTS` |
| `support` | question reports, counsellor requests | `mbaSupport` | `MBA_ADMIN_ROLES_SUPPORT` |
| `analytics` | MBA ops panel, success metrics | `mbaAnalyst` | `MBA_ADMIN_ROLES_ANALYTICS` |

Reading papers/questions, validate, export and reorder need `content` or `tests`; reports need `support` or `content`.
- `GET /me` (any admin) → `{ adminId; email: string|null; role: string|null; capabilities: ("content"|"tests"|"support"|"analytics")[] }`
  — the Admin panel hides what the role cannot use.

### Admin authoring 🛡
Build a paper in the Admin panel instead of the JSON importer. Every rule is the importer's own code
(`scripts/mba/paper_format.py`: `check_paper`, `check_set`, `check_question`, `build_paper_docs`) — nothing is
re-implemented, and every exam is handled the same way: a paper's `examId` picks its config, which sets the allowed
section ids, their order in the paper, and the marking rules questions are checked against. Nothing is deleted: "delete" archives the doc and takes it out of the paper. Adding, removing or
reordering questions is refused (409) on a **published** paper — unpublish first. Paper changes bump the paper's
`version` and append to its `history` (last 50: who, when, what).
```ts
interface SourceInput { kind: "official"|"licensed"|"faculty"|"original"; title?: string; url?: string; year?: number; retrievedAt?: string; notes?: string }
// url required for official/licensed (same as the content format); a question without source gets the paper's.
```
- `GET /exams` (`content`|`tests`) → `{ exams: Exam[] }` (same `Exam` shape as the public `GET /exams`) — every exam a paper
  can follow, read from the config files the importer validates against (`data/mba/cat_exam.json` first, then
  `data/mba/exams-config/*.json` by id). The panel takes the exam picker, pattern years, section ids/names, marking and
  timing from here.
- `POST /papers` (`tests`) body `{ id?; examId?: string /* default "cat" */; title?; examVersionYear?; year?; slot?; source: SourceInput }`
  → 201 `AdminPaper` (draft, no questions). CAT: `id` defaults to `cat-{year}-slot{slot}` and `title` to `CAT {year} Slot {slot}`;
  other exams need both. `id` must match `^[a-z0-9][a-z0-9-]{2,80}$`; `examVersionYear` (or `year`) must be a version in that
  exam's config. `examId` cannot be changed later. 422 invalid (unknown exam too), 409 id taken.
- `PATCH /papers/{id}` (`tests`) body `{ title?; examVersionYear?; year?: number|null; slot?: number|null; source?;
  availableFrom?: string|null; availableUntil?: string|null; expectedVersion? }` → `AdminPaper`. Header re-validated with
  `check_paper`; year/slot/examVersionYear are copied onto the paper's questions. 409 version conflict, 422 invalid.
- `POST /papers/{id}/archive` (`tests`) → `AdminPaper` (`status "archived"`; 409 if published). `unpublish` restores it to draft.
- `POST /papers/import` (`tests`) body `{ content: {paper, sets, questions} /* docs/mba-content-format.md single-file form */; dryRun?: boolean }`
  → `{ valid; errors: string[]; warnings: string[]; paperId; examId: string|null; questionCount; setCount; paper: AdminPaper|null }`
  (`paper.examId` picks the exam config, any exam of `GET /exams`). Always
  imports as a NEW **draft** paper (everything `draft`, version 1). `dryRun` only validates (errors in the body, 200).
  Without `dryRun`: 422 invalid, 409 if the paper id already exists (change `paper.id`; re-importing over an existing
  paper stays a script job: `scripts.mba.import_paper`, which protects reviewed content).
- `GET /papers/{id}/export` (`content`|`tests`) → the paper as content JSON (same format; archived questions left out).
- `POST /papers/{id}/validate` (`content`|`tests`) → `{ valid; errors: string[]; warnings: string[] }` — the whole paper
  through `build_paper_docs`, exactly as the importer would report it (warnings include pattern question-count gaps,
  missing solutions, unused sets).
- `PUT /papers/{id}/order` (`content`|`tests`) body `{ sections: {id: string /* the paper's exam section ids */; questionIds: string[]}[] /* ≤10 */; expectedVersion? }`
  → `AdminPaper`. Must list exactly the paper's current questions, each in its own section (422 otherwise); question
  `number`s follow the new order.
- `POST /papers/{id}/sets` (`content`) body `{ key?; kind; section /* a section id of the paper's exam */; title?; contentHtml; images?: string[] }` → 201 `AdminSet`
  (draft). `key` defaults to `{section}-{P|S|D}{n}` (passage / DILR set / data). 422 invalid, 409 key taken.
- `DELETE /sets/{id}` (`content`) → `AdminSet` archived. 409 while a question of the paper still uses it.
- `POST /papers/{id}/questions` (`content`) body `{ key?; section /* a section id of the paper's exam */; type: "MCQ"|"TITA"; setId?;
  stemHtml; options?; answer; solutionHtml?; alternativeApproaches?: string[] /* ≤5 HTML, blanks dropped */; videoUrl?: string /* https */;
  topic?; subtopic?; difficulty?; source?: SourceInput; position?: number /* 1-based, default last */ }`
  → 201 `AdminQuestion` (draft, version 1; approve it with `/review`). `key` defaults to `{section}-{nn}`. 422 invalid —
  including a type the paper's pattern has no marking rule for in that section (e.g. TITA in XAT) — 409 key taken or
  paper published.
- `DELETE /questions/{id}` (`content`) → `AdminQuestion` archived and removed from the paper (others renumbered).
  409 if the paper is published.

**Scheduling.** A paper may carry `availableFrom` / `availableUntil` (ISO UTC). Before `availableFrom` a published paper
is not in the content bank at all (no tests, no practice/daily questions); the bank cache reloads itself at the next
`availableFrom`. From `availableUntil` on, its tests are not listed (`GET /tests`, `GET /papers`) and `POST /attempts`
for them returns **409** "This mock is no longer available." (an attempt already in progress still resumes and submits;
results stay). Its questions stay in practice. Both null = always (the default).

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
- `GET /colleges?q=&city=&state=&kind=` → `{ colleges: CollegeSummary[]; total: number /*before filters*/; cities: string[] /*all, for the filter*/ }`
  Every institute a student can shortlist: the IIMs (`mbaPrograms`, `kind "iim"`) then the non-IIM colleges bundled in
  `data/mba/colleges/*.json` (`kind "other"`, read at runtime — keep that folder out of `.vercelignore`); each group by
  `shortName`. `city` / `state` exact (case-insensitive), `kind` `iim|other` (422 otherwise), `q` substring of name /
  short name / slug / city / state / programme name or code.
  ```ts
  interface CollegeProgram { code: string | null /* IIMs only */; name: string; durationYears: number | null; feeTotal: number | null;
    intake: number | null; medianSalary: number | null; salaryYear: string | null }
  interface CollegeSummary { slug: string; name: string; shortName: string; kind: "iim" | "other";
    type: string | null /* bundled: private | government | deemed | university department */; city: string | null; state: string | null;
    website: string | null; examsAccepted: string[]; programs: CollegeProgram[]; hasCutoffs: boolean /* IIM minimums for /eligibility */;
    applicationDeadline: string | null /* official, bundled only */; sourceUrl: string | null /* official admissions page, bundled only */ }
  ```
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

## Exam rules (other MBA exams)
`mbaExams/{xat|snap|nmat|cmat|mat|gmat|mah-mba-cet}` are seeded from `data/mba/exams-config/<examId>.json`
(official sources only, `data/mba/SOURCES.md` §6.5). Section ids never reuse VARC/DILR/QA, so CAT-only features
(drills, planner, score estimator, dashboard section rings, daily challenge) ignore other exams' questions.

| Exam | Sections | Timing | Marking |
|---|---|---|---|
| XAT 2027 | VALR 26, DM 21, QADI 28 ("about"), GK 20 | Part 1 (VALR+DM+QADI) 170 min shared, then GK 10 min | Part 1 +1/−0.25, −0.10 per unanswered after 12; GK +1/0, not in total |
| SNAP 2026 | GE 10, ALR 20, QDIDS 20, EMV 10 | one 60-min block, any order | +1 / −0.25 / 0 |
| NMAT 2026 | LS 36 (28 min), QS 36 (52), LRS 36 (40) | own timer each; student picks order | practice +1/0/0 (real NMAT is adaptive, scaled 12–120) |
| CMAT 2026 | QTDI, LRC, LC, GA, IE (20 each) | one 180-min block | +4 / −1 / 0 |
| MAT 2026 | LCM, ICR, MS, DAS, EBE (30 each) | one 120-min block | practice +1, official −0.25 (marks per correct not stated) |
| GMAT Focus | QR 21, VR 23, DI 20 (45 min each) | own timer each; student picks order | practice +1/0/0 (real GMAT is adaptive, 60–90 per section) |
| MAH-CET 2026 | LOGR 75, ABR 25, QAPT 50, VERB 50 | one 150-min block | +1 / 0 / 0 |

Attempts of these exams store `timerBlocks`, `unansweredPenalty` and `excludedSections` at start; `currentSectionIndex`,
`currentSectionStartedAt` and `sectionLog` then refer to blocks while `sectionPlan` stays one entry per section. CAT
attempt documents are unchanged. The XAT penalty goes to the 13th, 14th… unanswered Part 1 questions in paper order
(per-question `marks` −0.10), so section scores add up to the total.

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
  The item's uploaded documents are deleted with it.
Every checklist write bumps the entry's `updatedAt` (optimistic concurrency, like the shortlist).

`GET /me/applications` also returns `funnel: OutcomeFunnel` and `documents: { enabled: boolean /* false = uploads not
configured on this server */; maxBytes: 5242880; allowedTypes: ["application/pdf", "image/jpeg", "image/png"] }`.
`Application` additionally has `outcome: Outcome & { updatedAt: string | null }` and each `ChecklistItem` has
`documents: ApplicationDocument[]` (ready files, oldest first).

### Application documents 🔒 (`mbaStudent`)
Files go in the existing Firebase Storage bucket (env `BUCKET_NAME`, as in the Java backend; `MBA_DOCS_BUCKET`
overrides) at `mba/applications/{userId}/{slug}/{itemId}/{uuid}.{ext}` and are **private** (no public ACL). Metadata:
`mbaApplicationDocs/{id}` = `{ userId, slug, itemId, itemLabel, path, fileName, contentType, size, status, shareWithCounsellor,
createdAt, uploadedAt, updatedAt }`. PDF / JPG / PNG only, ≤ 5 MB; at most 5 files per checklist item and 100 per student.
Upload = 3 steps: (1) ask for an upload target, (2) the browser POSTs the file **directly to Storage** with a V4 signed
POST policy (pins object name, `Content-Type`, `acl=private` and a 1 B–5 MB size range; the bucket's CORS allows POST),
(3) `complete`, which checks the stored object (size, type, magic bytes) — a bad file is deleted (422).
Pending uploads never completed are removed after 1 hour (on the student's next applications load). Every endpoint
answers **503** when the bucket or service-account credentials are not configured.
```ts
interface ApplicationDocument { id: string; itemId: string; fileName: string; contentType: string; size: number /* bytes */;
  status: "pending" | "ready"; shareWithCounsellor: boolean; uploadedAt: string | null; createdAt: string }
```
- `POST /me/applications/{slug}/checklist/{itemId}/documents` body `{ fileName: string; contentType: string; size: number }`
  → 201 `{ document: ApplicationDocument /* pending */; upload: { url: string; fields: Record<string, string>; expiresAt: string /* 10 min */ }; maxBytes }`.
  Send a `multipart/form-data` POST to `upload.url` with every `fields` entry, then the file as `file` (last); Storage
  answers 201. 422 wrong type / > 5 MB; 404 not shortlisted or unknown item; 409 item or student file limit reached.
- `POST /me/application-docs/{id}/complete` → `Application` (idempotent). The first ready document on an item ticks it
  (unless it is already done or marked not applicable). 409 the file has not arrived; 422 not a valid PDF/JPG/PNG ≤ 5 MB
  (file and metadata deleted).
- `GET /me/application-docs/{id}/download` → `{ url: string /* signed GET, 5 min, inline */; expiresAt }`.
- `PATCH /me/application-docs/{id}` body `{ shareWithCounsellor: boolean }` → `Application`. Per-document consent: only
  shared documents appear in the admin counsellor-request detail (`sharedDocuments`), independent of the request-level
  `shareWithCounsellor` (profile / shortlist / mocks).
- `DELETE /me/application-docs/{id}` → `Application` (file deleted from Storage, then the metadata).
- Removing an institute from the shortlist and "Delete my MBA data" also delete its / all documents (files included).
404 for any document that is not the caller's.

### Admission outcomes 🔒 (`mbaStudent`; aggregate 🛡)
Stored on the shortlist entry as `outcome` (`PUT /me/shortlist/{slug}` keeps it).
```ts
interface Outcome { applied: { date: string | null } | null; shortlisted: { date: string | null } | null /* WAT / GD / PI call */;
  interviewDone: { date: string | null } | null; result: { value: "admit" | "waitlist" | "reject"; date: string | null } | null;
  decision: { value: "accepted" | "declined"; date: string | null } | null }   // null = stage not reached
interface OutcomeFunnel { applications: number /* shortlisted institutes */; applied: number; shortlisted: number; interviewDone: number;
  admit: number; waitlist: number; reject: number; accepted: number; declined: number }
```
- `PUT /me/applications/{slug}/outcome` body `Outcome` (full replace; omitted = null) → `Application`. 422: a call / result
  without `applied`, `interviewDone` without `shortlisted`, a `decision` without an admit, dates not YYYY-MM-DD, in the
  future (India time) or out of stage order, unknown fields. 404 not shortlisted. Same value writes nothing.
- 🛡 `GET /admin/application-outcomes` (capability `analytics`) → `{ colleges: ({ slug; name: string | null; shortName: string | null }
  & Omit<OutcomeFunnel, "applications">)[] /* most applied first */; totals: same shape, slug "all"; generatedAt }`. Anonymous:
  counts only, from every student's shortlist entries that have any recorded stage; no user ids, names or dates.

### Counsellor requests (MBA leads)
Pipeline `new → contacted → in_progress → converted | closed` (closed needs a reason). Assignment is to a real
counsellor from the Java `counsellors` collection (read-only; fields used: `firstName`, `lastName`, `phoneNumber`,
`email`, `verified`, `organisationName`, `photoUrlSmall`); the request keeps the counsellor id plus a name snapshot.
Legacy docs map on read: `open`/`assigned` → `new`, `done` → `closed`, free-text `assignedTo` → counsellor without id,
`adminNote` → the first note.
```ts
type CounsellorTopic = "shortlisting" | "applications" | "wat-pi" | "mock_interview" | "other";
type CounsellorRequestStatus = "new" | "contacted" | "in_progress" | "converted" | "closed";
interface CounsellorRequest { id: string; topic: CounsellorTopic; preferredTime: string | null;
  preferredSlots: { date: string /* YYYY-MM-DD */; time: "morning" | "afternoon" | "evening" /* IST 9-12, 12-4, 4-8 */ }[] /* mock_interview only */;
  note: string | null;
  slug: string | null /* institute it is about */; status: CounsellorRequestStatus; counsellorName: string | null;
  shareWithCounsellor: boolean /* student consent to show profile, shortlist and mock summary */;
  createdAt: string; updatedAt: string; assignedAt: string | null; closedAt: string | null /* converted or closed */;
  timeline: { at: string; text: string }[] /* oldest first, student-facing events only (no internal notes) */ }
interface AdminCounsellorRequest extends CounsellorRequest { userId: string; studentName: string | null; phoneNumber: string | null;
  email: string | null; counsellor: { id: string | null /* null = legacy free text */; name: string; phoneNumber: string | null; email: string | null } | null;
  closeReason: string | null; nextFollowUpAt: string | null /* YYYY-MM-DD */; overdue: boolean /* follow-up before today (IST), not converted/closed */;
  notes: { id: string; at: string; by: string /* admin email */; text: string }[] /* newest first, last 200 */;
  updatedBy: string | null; history: { at: string; by: string /* "student" or admin email */; summary: string }[] /* last 50 */ }
interface SharedStudentData { profile: { targetExam: string; examDate: string | null; targetPercentile: number | null; currentLevel: string;
    weeklyStudyHours: number; targetPrograms: string[] | null } | null;
  shortlist: { slug: string; status: string; deadline: string | null }[] /* student's private notes are never shared */;
  mocksSubmitted: number; recentMocks: { title: string; submittedAt: string | null; score: number | null; maxScore: number | null;
    sections: { id: string; score: number | null; maxScore: number | null; accuracy: number | null }[] }[] /* newest 5 */ }
interface AdminCounsellorRequestDetail extends AdminCounsellorRequest { shared: SharedStudentData | null /* null unless consented */;
  sharedDocuments: { id: string; slug: string; institute: string | null; itemId: string; itemLabel: string; fileName: string;
    contentType: string; size: number; uploadedAt: string | null }[] /* only documents the student shared, each by its own toggle */ }
interface CounsellorOption { id: string; name: string; phoneNumber: string | null; email: string | null;
  organisationName: string | null; photoUrl: string | null; verified: boolean }
```
Student 🔒:
- `POST /me/counsellor-requests` body `{ topic: CounsellorTopic; preferredTime?: string|null /*≤120*/; note?: string|null /*≤1000*/;
  slug?: string|null; shareWithCounsellor?: boolean /*default false*/; preferredSlots?: { date; time }[] /*1-3*/ }` → 201
  `CounsellorRequest` (`status "new"`). 422 bad topic/slug/length or unknown field; 409 when the student already has 3
  requests that are not converted/closed. Name, phone and email are copied from the student's account.
  **Mock interview booking** = topic `mock_interview` with 1-3 `preferredSlots` (required; dates today … +60 days IST;
  duplicates dropped, sorted). Slots are rejected (422) on other topics. The admin pipeline is the same: assign a
  counsellor, who confirms one slot with the student by phone.
- `GET /me/counsellor-requests` → `{ requests: CounsellorRequest[] }` newest first.
- `PATCH /me/counsellor-requests/{id}` body `{ shareWithCounsellor: boolean }` → `CounsellorRequest` (404 not the student's).
  Changing it adds a timeline entry; the same value writes nothing.
- Assignment and status changes appear as `counsellor_update` notifications (see "Notifications").

Admin 🛡 (same auth as "Admin content review"; role capability `support`, see "Admin roles"):
- `GET /admin/counsellors?q=&limit=` → `{ counsellors: CounsellorOption[]; total: number }` — verified first, then by name;
  `q` = substring of name / phone / email / organisation / id; `limit` 1-200 (default 50). Cached 5 min per instance.
- `GET /admin/counsellor-requests?status=&topic=&counsellorId=&overdue=&q=` → `{ requests: AdminCounsellorRequest[];
  counts: Record<CounsellorRequestStatus, number>; overdue: number; unassigned: number /* not converted/closed */;
  byCounsellor: { counsellorId: string | null; name: string; active: number; overdue: number; total: number }[] }`
  newest first; `counts`, `overdue`, `unassigned` and `byCounsellor` ignore the filters. `counsellorId=none` = unassigned;
  `overdue=true` = follow-up date passed; `q` = substring of name / phone / email / counsellor / note / slug. 422 bad filter.
- `GET /admin/counsellor-requests/{id}` → `AdminCounsellorRequestDetail` | 404.
- `PATCH /admin/counsellor-requests/{id}` body `{ status?: CounsellorRequestStatus; closeReason?: string|null /*≤300*/;
  counsellorId?: string|null /* null unassigns */; nextFollowUpAt?: string|null /*YYYY-MM-DD*/ }` → `AdminCounsellorRequestDetail`.
  422: empty body, unknown field, unknown counsellor id, bad date, `closed` without a reason. `closeReason` is kept for
  `closed` (required) and `converted` (optional outcome) and cleared when the request is reopened. A patch that changes
  nothing writes nothing. Each change appends a `history` entry; assignment and status changes also add a student
  timeline entry (and so a notification).
- `GET /admin/counsellor-requests/{id}/documents/{docId}/download` → `{ url; expiresAt }` (signed GET, 5 min). 404 unless the
  document belongs to the request's student and is shared; 503 storage not configured.
- `POST /admin/counsellor-requests/{id}/notes` body `{ text: string /*1-2000, trimmed*/ }` → 201 `AdminCounsellorRequestDetail`.
  Follow-up notes are internal (never shown to the student); author = the admin's email.
- Counsellors are not notified by this service: the Java backend has no endpoint to message one counsellor (only
  broadcast-to-all-users / topic pushes and OTP mails), so admins use the counsellor filter ("My assigned MBA students")
  in the Admin panel. Direct counsellor notification is a follow-up for the Java backend.

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
interface SessionAnswer { questionId: string; mode: "text" | "voice"; answerText: string /* voice: the transcript */; wordCount: number;
  overtime: boolean /* WAT: > endsAt + 60 s */; feedback: Feedback; answeredAt: string;
  delivery: { durationSeconds: number; wordsPerMinute: number; pace: "slow" | "steady" | "fast" /* <110, 110-170, >170 wpm */;
    fillerCount: number; fillers: { word: string; count: number }[]; notes: string[] } | null /* voice only */ }
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
- `POST /me/gdpi/sessions/{id}/answers/voice?questionId=&durationSeconds=` — **voice practice (PI sessions only)**. Body =
  the raw recording, `Content-Type` `audio/webm` | `audio/ogg` | `audio/mp4` | `audio/m4a` | `audio/mpeg` | `audio/wav`
  (codec parameters ignored), ≤ 4 MB (Vercel's request limit is 4.5 MB); `durationSeconds` 3–185 (the client's recording
  length). The audio is sent once to OpenAI speech-to-text (`MBA_TRANSCRIBE_MODEL`, default `gpt-4o-mini-transcribe`,
  prompted to keep filler words) and **discarded — never stored or logged**. The transcript (cut to 2,000 characters) gets
  the same AI feedback as a typed answer, plus deterministic `delivery` stats (filler words counted from the transcript,
  words/min from the recording length). Same shared daily AI quota (checked before transcription, counted once on
  success) → same response as `/answers`. 415 not audio; 413 too large; 422 empty/too short a recording, transcript under
  20 characters, or a WAT session; 404 / 409 / 429 / 503 as for `/answers`.

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
- "Explain my plan" (AI): `GET /me/plan/explain?week=` / `POST /me/plan/explain?week=` — see "AI section coaches".

## AI section coaches 🔒 (`mbaStudent`)
Three chats on top of the AI tutor (`api/mba/coach.py`, OpenAI, same env as the tutor): `coach` = `varc` | `dilr` |
`quant` (sections VARC / DILR / QA). Each has a section-specific system prompt (VARC: RC strategy, para-jumble / odd
sentence / summary methods, vocabulary in context; DILR: set selection, grid building, approach per set type; Quant:
concepts, shortcuts, step checking). The model gets **only the caller's own data** for that section (`context` below,
shown in the app as "What your coach sees"): topic accuracy from `mbaQuestionStats` (insights rules), topics of recent
mistakes, the section's score estimate when `/me/score-estimate` is ready, and whether a timed test is running.
Guardrails: off-topic → one-line refusal; official facts (dates, pattern, cut-offs, fees, percentiles) are never stated —
the coach points to `/mba-entrance-exams/cat`, `/mba-colleges/iim-cutoffs`, `/mba-admission-deadlines`, `/mba/colleges`;
while a test is in progress the coach must not solve or hint at any specific question, and a message that shares 8+
consecutive words with a question (stem, options or passage) of a running attempt is refused with **409** before any
model call (no quota used). Every model call counts against the shared daily AI quota (`mbaAiUsage`,
`MBA_AI_DAILY_LIMIT`) → **429**; 503 when not configured or the model fails.
Chats are short-lived: `mbaCoachChats/{userId}_{coach}` keeps the last 20 turns, turns older than 7 days are dropped,
the last 12 turns are sent to the model.
```ts
type CoachId = "varc" | "dilr" | "quant";
interface CoachTurn { role: "user" | "assistant"; text: string /* plain text */; at: string }
interface CoachContext {
  topics: { topic: string; attempts: number; correct: number; accuracy: number | null; status: "weak" | "ok" | "strong" | "low_evidence" }[]; // ≤ 15
  recentMistakeTopics: string[];   // "Topic · Subtopic", latest first, ≤ 6
  estimate: { expected: number; low: number; high: number; maxScore: number; confidence: "low" | "medium" | "high" | null } | null;
  inRunningTest: boolean }
interface CoachChat { coach: CoachId; section: SectionId; title: string; turns: CoachTurn[]; context: CoachContext;
  dailyLimit: number; remainingToday: number; configured: boolean /* false = OPENAI_API_KEY missing */ }
```
- `GET /me/coach/{coach}` → `CoachChat` (422 unknown coach).
- `POST /me/coach/{coach}/messages` body `{ message: string /* 1-1500 chars */ }` → `CoachChat` with the new user turn and
  the reply appended. 409 quotes a live question; 422 blank/too long; 429 quota; 503.
- `DELETE /me/coach/{coach}` → `{ deleted: boolean }` (clears that chat).
- `GET /me/plan/explain?week=YYYY-MM-DD` → `{ explanation: PlanExplanation | null }` — the cached explanation if the week's
  plan (tasks + rules) is unchanged since it was written.
- `POST /me/plan/explain?week=` → `PlanExplanation`. AI explanation of the study planner's week, grounded only in
  `basis.rules`, the section figures and the tasks (never changes the plan). Returns the cache (`cached: true`, no quota)
  while the plan is unchanged; else one model call. 409 when the week has no tasks; 429/503 as above.
```ts
interface PlanExplanation { weekStart: string; text: string /* plain text, "- " bullet lines */; generatedAt: string;
  cached: boolean; remainingToday: number | null /* null when cached */ }
```

## Syllabus (LMS-lite) 🔒 (`mbaStudent`)
CAT syllabus section → topic → subtopic with concept notes (`api/mba/syllabus.py`). The hierarchy and notes come from
`data/mba/syllabus/cat.json` (ProCounsel-written concept notes, 3–6 bullet points per subtopic). Topics use the question
bank's topic labels (`bankTopics`); each subtopic's `match` keywords map the bank's free-text subtopics onto it (the
keyword found earliest in the label wins, ties → longer keyword). Question counts are live from the published CAT bank.
The existing Java courses (Learn tab) are unchanged; the syllabus is a second tab there.
```ts
interface SyllabusSubtopic { id: string /* "qa-percentages" */; title: string; notes: string[];
  questionCount: number; bankSubtopics: string[] /* bank labels mapped here */;
  practiceHref: string /* /mba/practice?section=QA&topic=Arithmetic */;
  drillHref: string | null /* /mba/mocks/build?section=…&topic=…&subtopic=…(repeated); null when no questions */;
  completed: boolean; completedAt: string | null; bookmarked: boolean; note: string | null /* private to the student */ }
interface SyllabusTopic { id: string; title: string; questionCount: number; practiceHref: string; completed: number; total: number; subtopics: SyllabusSubtopic[] }
interface SyllabusResponse { examId: "cat"; version: number;
  sections: { id: SectionId; title: string; completed: number; total: number; topics: SyllabusTopic[] }[];
  progress: { completed: number; total: number; bookmarked: number } }
```
- `GET /syllabus` → `SyllabusResponse` (with the caller's progress, bookmarks and notes).
- `PATCH /me/syllabus/{subtopicId}` body `{ completed?: boolean; bookmarked?: boolean; note?: string | null /* ≤ 2000, blank clears */ }`
  → `{ subtopicId; completed; completedAt; bookmarked; note; updatedAt }`. Only sent fields change; `completedAt` is set
  when first marked completed and cleared when unmarked. The doc is deleted once nothing is left (not completed, not
  bookmarked, no note). 404 unknown subtopic; 422 empty body, `null` for a boolean, unknown field, note too long.

## Notifications 🔒 (`mbaStudent`)
Computed on each request from real state (no cron): `resume_mock` (in-progress attempt), `plan_today` (pending tasks
today), `plan_overdue` (pending tasks from earlier this week), `mistakes_due`, `cat_countdown` (30/14/7/1 day
milestones and exam day; profile date, else official), `shortlist_deadline` (shortlist deadline within 7 days, not
declined/offer), `new_mock` (paper `publishedAt` within 14 days and not attempted), `counsellor_update` (the latest
admin-made change on each of the student's counsellor requests — assignment or status — within 30 days; id changes
with each update; href `/mba/shortlist#counsellor`), `doubt_reply` (newest visible reply by someone else on each thread the
student started, within 14 days; title says "Faculty answered…" for a faculty reply; href `/mba/community/doubts/{id}`),
`support_reply` (latest support message on each ticket within 30 days; href `/mba/help?ticket={id}`), `exam_update` (an exam
update published in the last 30 days for one of the student's target exams; id `exam-update-{id}`; href `/mba/dashboard#exam-updates`).
```ts
interface MbaNotification { id: string /* stable while the condition lasts; day-scoped ones change daily */;
  kind: "plan_today" | "plan_overdue" | "mistakes_due" | "resume_mock" | "cat_countdown" | "shortlist_deadline" | "new_mock"
    | "counsellor_update" | "doubt_reply" | "support_reply" | "exam_update";
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
interface QuestionRef { questionId: string; section: ExamSectionId; number: number /* 1-based within the section, as on the result page */;
  topic: string | null; difficulty: "easy" | "medium" | "hard" | null; outcome: Outcome; timeSpentMs: number }
interface Bucket { total: number; attempted: number; correct: number; incorrect: number; skipped: number; accuracy: number | null /* 0-1 */ }
interface PracticeLink { id: string /* "section:QA" | "topic:QA:Algebra" | "mistakes" */; label: string; href: string /* in-app */ }
interface DeterministicAnalysis { attemptId; title; submittedAt; score; maxScore; questionCount: number; attempted: number;
  lowEvidence: boolean /* attempted < 10 */; evidenceNote: string | null;
  sections: { id: ExamSectionId; questionCount; score; maxScore; attempted; correct; incorrect; unanswered; accuracy: number | null;
    timeSpentMs; medianTimeMs: number | null /* null with < 3 timed questions */ }[];
  byDifficulty: (Bucket & { difficulty: "easy" | "medium" | "hard" | "unrated" })[];
  byTopic: (Bucket & { section: ExamSectionId; topic: string; timeSpentMs: number })[];
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
- `GET /me/insights?examId=cat` (topics and trend of one exam; default CAT) →
```ts
{ topics: { section: ExamSectionId; topic: string; questions: number /* distinct answered */; attempts: number /* all answers, practice+daily+mocks */;
    correct: number; accuracy: number | null; avgTimeMs: number | null /* from submitted mocks only */; timedAnswers: number;
    confidence: "sufficient" | "low" /* attempts ≥ 8 */; status: "weak" | "ok" | "strong" | "low_evidence"; href: string }[];  // sorted section, topic
  weakTopics: Topic[] /* status "weak" (≥ 8 attempts and accuracy < 0.6), worst first, max 5 */; lowEvidenceCount: number;
  trend: { attemptId; title; kind: "full_mock" | "sectional" | string; submittedAt; score; maxScore;
    sections: { id: ExamSectionId; score; maxScore; accuracy: number | null }[] }[] /* last 5 submitted attempts of the exam, oldest first */;
  rules: { minAttempts: 8; weakBelow: 0.6; strongFrom: 0.8 } }
```
  Topics with < 8 answers are never flagged weak (`low_evidence`). `href` = `/mba/practice?section=QA&topic=…`
  (the practice page reads `exam`, `section` and `topic`; other exams add `exam=xat` etc., also in mock-analyst links).

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
  Same auth as the other admin endpoints; role capability `support` or `content` (see "Admin roles").

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

## Success metrics 🛡 (Admin "MBA metrics")
`GET /admin/metrics?from=YYYY-MM-DD&to=YYYY-MM-DD` — same auth as the other admin endpoints; role capability `analytics` (see "Admin roles").
Days are India time and inclusive. Defaults: `to` = today (a later `to` is clamped to today), `from` = `to` − 27 days. 422 for a
bad date, `from > to`, or a range over 92 days. Read-only; cached in-process per range for `MBA_METRICS_TTL_SECONDS` (default 300).
Never returns user ids, names or phone numbers — counts and rates only. Rates are 0–1 (4 dp) or `null` when the base is 0.
```ts
interface TimeToValue { students: number; medianDays: number | null; sameDayRate: number | null }
interface MockKind { started: number; submitted: number; completionRate: number | null }
interface MbaMetrics {
  from: string; to: string; generatedAt: string;
  onboarded: number;                     // mbaProfiles created in range
  activation: { eligible: number; activated: number; rate: number | null };
  timeToFirstPractice: TimeToValue;      // onboarded in range → first practice-answered question (calendar days, 0 = same day)
  timeToFirstMock: TimeToValue;          // onboarded in range → first test started (exact, in days)
  mocks: MockKind & { byKind: Record<string /* full_mock | sectional */, MockKind> };  // attempts started in range
  planner: { scheduled: number; done: number; skipped: number; adherence: number | null };  // mbaStudyTasks dated in range; done/scheduled
  weeklyActive: { distinctStudents: number; avgWeekly: number | null /* full weeks only */ };
  dailyChallenge: { days: number; avgParticipantsPerDay: number | null; distinctStudents: number };
  counsellorRequests: { total: number; avgPerWeek: number | null; byStatus: { open; assigned; done } /* pipeline folded: new→open, contacted|in_progress→assigned, converted|closed→done */; conversionRate: number | null /* done/total */ };
  weeks: { weekStart; weekEnd; fullWeek: boolean; onboarded; activeStudents; mocksStarted; mocksSubmitted; plannerScheduled;
           plannerDone; dailyChallengeStudents; counsellorRequests; counsellorRequestsDone }[];  // Monday weeks clipped to the range
  truncated: string[];                   // collections whose read cap was hit — numbers are then lower bounds
}
```
Definitions: **activation** = of students onboarded in range at least 7 days ago (`eligible`), those who answered ≥ 10 distinct
questions (practice, daily or mock) on their onboarding day or the 6 days after. **Active** = answered a question or started a
test that week. **Daily challenge** = answered at least one of that day's daily questions on that day (from `mbaQuestionStats`,
all students, not just leaderboard opt-ins; uses today's published bank to rebuild past days' sets). **Mock completion** uses the
stored status, so an expired attempt nobody has reopened still counts as not submitted.
Reads (single-field range queries, projected fields, capped): `mbaProfiles.createdAt` (5 000), `mbaQuestionStats.lastAnsweredAt ≥ from`
(40 000), `mbaAttempts.startedAt ≥ from` (20 000), `mbaStudyTasks.date` (50 000), `mbaCounsellorRequests.createdAt` (5 000).

## Previous-year papers, ProCounsel percentile, score estimator 🔒 (`mbaStudent`)

**PYQs.** Actual past CAT papers (2017–2025, slots 1–3) are imported from `data/mba/content/cat-<year>-slot<n>/`
like any paper (`scripts/mba/import_paper.py`), so the mock engine derives `{paperId}-full` and
`{paperId}-varc|dilr|qa` from them. A paper is a PYQ when `year` and `slot` are integers and
`source.kind == "official"` (`exams.is_pyq`). Durations and marking come from the paper's exam version
(2017–19: 60-minute sections; 2020: 76 questions; 2021+: 40-minute sections), nothing is hard-coded.
`/tests`, `/papers`, `/questions`, attempt results and `QuestionPublic` all carry `isPyq` (+ `year`/`slot`);
`/tests` and `/questions` filter with `source=pyq|original|all`.

- `GET /me/pyq` → every offered PYQ paper (newest year first, then slot) with the student's progress:
```ts
{ papers: { paperId; title; year: number; slot: number; examVersionYear: number | null; questionCount; durationMinutes;
    sections: { id: SectionId; questionCount: number; durationMinutes: number }[]; source: Source | null;
    tests: { testId; kind: "full_mock" | "sectional"; title; sections: SectionId[]; durationMinutes; questionCount;
      attempts: number /* submitted */; inProgressAttemptId: string | null; lastAttemptId: string | null;
      bestScore: number | null; firstScore: number | null; maxScore: number | null;
      takenBy: number /* ProCounsel students with a first attempt */;
      procounselPercentile: ProcounselPercentile | null /* of the student's first attempt */ }[] }[];
  minStudents: number; percentileNote: string }
```
  Start / resume a test with the usual `POST /attempts {testId}`.

**ProCounsel percentile** (`mbaTestScoreStats/{testId}`). When an attempt is submitted (the request that
actually submits it), it is added to the test's histogram if it is the student's first submitted attempt of
that test, and the attempt is marked `scoreStatsCounted`. A percentile is read from that one doc: mid-rank
`(below + ½·equal) / others × 100` over OTHER students' first attempts (the student's own counted score is
taken out); `null` until at least 20 others. Applies to every test (PYQ and ProCounsel mocks). Copy must say it
is relative to ProCounsel students, not the official CAT percentile; no official percentile mapping exists
and none is shown.

- `GET /me/score-estimate` → estimated CAT raw score on the current pattern (latest `mbaExams/cat` version
  whose section question counts are announced):
```ts
{ ready: boolean;
  pattern: { year: number; totalDurationMinutes: number; mixBasis: string /* where the MCQ/TITA split comes from */ } | null;
  expected: number | null; low: number | null; high: number | null /* 80% band */; maxScore: number | null;
  confidence: "low" | "medium" | "high" | null; confidenceReason: string;
  sections: { id: SectionId; questionCount; maxScore; expected; low; high; timedTests: number; answered: number;
    types: { type: "MCQ" | "TITA"; questionCount; attemptRate: number | null; accuracy: number | null; answered: number; expected: number }[] }[];
  inputs: { pyqAttempts; mockAttempts; fullLength; timedQuestions; timedAnswered; practiceQuestions; dailyQuestions; lastTimedAt: string | null };
  needs: { section: SectionId; timedTestsNeeded: number; questionsNeeded: number }[];  // empty when ready
  progress: number /* 0–1 towards the minimum data */;
  tips: { title; detail; href }[] /* max 4: what to do to tighten the estimate */;
  rules: Record<string, number>; disclaimer: string }
```
  Method: timed full/sectional attempts (PYQ weight 1.0, ProCounsel mocks 0.9) give the attempt rate and
  accuracy per section, MCQ and TITA separately (TITA has no negative marking); practice and daily-challenge
  answers (`mbaQuestionStats`) add accuracy only, weight 0.35, one observation per question (wrong if it was
  ever a mistake; questions seen in a timed test are not counted again). Every observation is weighted by
  recency (30-day half-life). Thin MCQ/TITA buckets are shrunk towards the section. Expected marks =
  questions × attempt rate × (accuracy × correct + (1 − accuracy) × incorrect); the 80% band combines the
  uncertainty of the measured rates with the paper-to-paper spread at that accuracy. The MCQ/TITA mix of the
  current pattern comes from the latest PYQ papers in the bank (`mixBasis`).
  `ready: false` until every section has ≥ 1 timed test and ≥ 20 answered questions (`needs` says what is
  missing). Confidence: high = ≥ 3 timed tests per section, ≥ 300 answers, last timed test within 30 days;
  medium = ≥ 2 per section and ≥ 120 answers; else low. Never maps to a percentile.

## Practice modes — test builder, timed drills, self-rated confidence 🔒 (`mbaStudent`)

A built test is an ordinary attempt in `mbaAttempts` (`kind: "drill"`, `testId: "drill-{attemptId}"`, a generated
`sectionPlan`, `drill: {mode, sections, topics, subtopics, difficulty, source, count, timeLimitMinutes, clientToken}`),
so it runs on the attempt engine above: server timer, autosave with `seq`, idempotent submit, CAT marking of the
latest `mbaExams/cat` version, result, `/me/attempts` history, insights trend and the mock analyst. No new collection.
`POST /attempts { testId: "drill-…" }` resumes it (or returns the submitted attempt → the player opens the result);
it is never created there (404 for an unknown drill id). Built tests do not complete planned mocks in the study
planner and are not added to the ProCounsel-percentile histogram (`mbaTestScoreStats`).

- `GET /drills/options` →
```ts
{ sections: { id: SectionId; questionCount: number; minutesPerQuestion: number /* auto pace */;
    topics: { topic: string; questionCount: number; subtopics: { subtopic: string; questionCount: number }[] }[] }[];
  sources: { all: number; pyq: number; original: number };
  weakTopics: { section: SectionId; topic: string; attempts: number; accuracy: number }[];  // insights rule, worst first
  mistakesDue: number; luckyGuesses: number;     // questions that a weak-topic set would pick first
  inProgress: AttemptSummary | null;              // the student's running built test
  limits: { maxCount: 50; maxMinutes: 180 } }
```
  Counts exclude questions in the student's running attempts.
- `POST /drills` body →  `Attempt`
```ts
{ clientToken: string /* 8–64 chars [A-Za-z0-9_-], new per "Start" click: a repeat returns the same test */;
  mode: "timed" | "weak" | "mixed";
  sections?: SectionId[] /* empty = all; "timed" needs exactly one */;
  topics?: string[]; subtopics?: string[] /* case-insensitive; ignored for "weak" */;
  difficulty?: ("easy" | "medium" | "hard")[] /* empty = all */;
  source?: "all" | "pyq" | "original" /* PYQ = the practice `source` filter rule */;
  count: number /* 1–50 */; timeLimitMinutes?: number | null /* 1–180; null = automatic */ }
```
  Errors: 409 while another built test is in progress ("finish or submit it first"); 422 for invalid input,
  `timed` without exactly one section, no matching questions, a weak-topic set with nothing to revise, or fewer
  minutes than sections; 503 when the CAT pattern is not seeded.
  Selection (never reads answer keys): pool = published questions matching the filters minus every question in
  the student's running attempts (a built test can never reveal a live mock's answers; and the mock engine's 409
  still stops a mock that shares questions with a running built test). DILR/RC sets stay together — whole sets
  while they fit, otherwise the first questions of one set in paper order. Questions are picked randomly within
  priority tiers and their order is shuffled per section; **option order is never shuffled** (official solutions
  refer to option letters). Tiers: `mixed`/`timed` — never answered, then last answer wrong, then the rest; the
  count is spread evenly over the chosen sections. `weak` — due mistakes, then lucky guesses (latest answer right
  but rated "guess"), then questions of weak topics (same rule as `/me/insights`: ≥ 8 answers and accuracy < 0.6):
  never answered, last wrong, rest. Sections run in CAT order (VARC, DILR, QA), each its own timed block, so a
  one-section drill is one timed block. Time = `timeLimitMinutes` split by question count (≥ 1 min each), or
  automatic: ceil(questions × section minutes ÷ section questions) of the latest CAT version that announced
  question counts (40/24 VARC, 40/22 DILR and QA ≈ 1.8 min), falling back to 1.8 min per question.

### Self-rated confidence
`type Confidence = "sure" | "unsure" | "guess"` — optional on practice answers and attempt responses (kept only
with an answer). Counted into the student's `mbaQuestionStats` doc when the answer is counted (practice answer,
attempt submit): `confidenceCounts: { sure|unsure|guess: { answers, correct } }`, `lastConfidence`.
```ts
interface ConfidenceBreakdown {   // AttemptResult.confidence: answered questions only
  sure: { answered: number; correct: number; incorrect: number }; unsure: …; guess: …; unrated: … }
```
- `GET /me/confidence` →
```ts
{ levels: { level: Confidence; answers: number; correct: number; accuracy: number | null }[];
  ratedAnswers: number; unratedAnswers: number;
  sureButWrong: number /* answers rated sure that were wrong */; luckyGuesses: number /* rated guess, right */;
  luckyGuessQuestions: number /* latest answer a lucky guess; offered again by weak-topic sets */;
  topics: { section: SectionId; topic: string; sureButWrong: number; luckyGuesses: number; href: string }[] /* max 5 */;
  totals: { answered: number; correct: number; incorrect: number } /* all answers, rated or not */ }
```

## MBA ops 🛡 (Admin "MBA ops")
`GET /admin/ops?days=14` (`analytics`; `days` 1–60) → read-only summary:
```ts
interface OpsSummary { generatedAt: string;
  ai: { days: { date: string /* IST yyyy-mm-dd, oldest first, zeros included */; calls: number; students: number; estCostUsd: number }[];
        totalCalls: number; totalStudents: number; estCostUsd: number;
        topUsers: { userId: string; calls: number; days: number; estCostUsd: number }[] /* top 10 in the window */;
        pricing: { model: string; inputPerMTokUsd: number; outputPerMTokUsd: number; estInputTokensPerCall: number; estOutputTokensPerCall: number; sourceUrl: string } };
  content: { papers: { draft; published; archived; upcoming; live; ended } /* last three: scheduled published papers */;
             questions: { draft; flagged; published; archived; unlisted /* archived out of a paper */ }; sets: { draft; published; archived } };
  support: { reports: { open; resolved; rejected; last7Days }; counsellorRequests: { open; assigned; done } } }
```
AI calls come from `mbaAiUsage` (tutor hints, mock analyst and GDPI feedback share it; it stores counts, not tokens), so
cost is an **estimate**: calls × tokens per call × price, all from `api/mba/ai_pricing.py` (env `MBA_AI_PRICE_INPUT_PER_MTOK_USD`,
`MBA_AI_PRICE_OUTPUT_PER_MTOK_USD`, `MBA_AI_EST_INPUT_TOKENS`, `MBA_AI_EST_OUTPUT_TOKENS`). Backups/retention: docs/mba-ops.md.

## Exam updates (`mbaExamUpdates`) 🔒 / 🛡
Admin-written announcements per exam; **every update needs the official https source page** (exam body / institute).
Nothing is seeded: admins enter updates from the official sites. Students see published updates for the exams they
target (profile `targetExams`; CAT when unset) on the dashboard and as `exam_update` notifications.
```ts
type ExamId = "cat" | "xat" | "snap" | "nmat" | "cmat" | "mat" | "gmat" | "mah-mba-cet";
type ExamUpdateKind = "registration" | "admit_card" | "exam_date" | "answer_key" | "result" | "other";
interface ExamUpdate { id: string; exam: ExamId; examLabel: string; kind: ExamUpdateKind; kindLabel: string; title: string;
  detail: string | null; eventDate: string | null /* YYYY-MM-DD the update is about */; sourceUrl: string; publishedAt: string | null }
interface AdminExamUpdate extends ExamUpdate { status: "draft" | "published"; createdAt: string; createdBy: string | null;
  updatedAt: string; updatedBy: string | null }
```
- 🔒 `GET /me/exam-updates` → `{ exams: ExamId[] /* what it is filtered by */; updates: ExamUpdate[] /* newest published first, ≤ 20 */ }`.
- 🛡 (capability `content` or `support`) `GET /admin/exam-updates?exam=` → `{ updates: AdminExamUpdate[] }` (drafts included, newest first).
- 🛡 `POST /admin/exam-updates` body `{ exam; kind; title: string /*3-140*/; detail?: string|null /*≤600*/; eventDate?: string|null;
  sourceUrl: string /* https only, required */; status?: "draft" | "published" /*default draft*/ }` → 201 `AdminExamUpdate`.
- 🛡 `PATCH /admin/exam-updates/{id}` (any subset of the create fields) → `AdminExamUpdate`. Publishing (draft → published)
  sets `publishedAt` = now (so it notifies again); back to draft clears it. 422 empty body or nulling a required field.
- 🛡 `DELETE /admin/exam-updates/{id}` → `{ deleted: true }`.

## Delete my MBA data 🔒 (`mbaStudent`)
- `POST /me/data/delete` body `{ confirm: "DELETE" }` → `{ deleted: Record<collection, number>; anonymised: { mbaQuestionReports: number; mbaDoubts: number }; completedAt }`.
  Deletes every document of the caller in `mbaAttempts`, `mbaAttemptAnalyses`, `mbaQuestionStats`, `mbaStudyTasks`,
  `mbaAiUsage`, `mbaGdpiSessions`, `mbaCounsellorRequests`, `mbaDailyResults`, `mbaLeaderboardPrefs`,
  `mbaNotificationState`, `mbaShortlists`, `mbaProfiles`, `mbaCoachChats`, `mbaSyllabusProgress`, `mbaApplicationDocs` (uploaded files first, then their records). Question reports are kept for content quality but anonymised
  (moved to a random id, `userId` and rate-limit fields removed). Also deletes `mbaGroupMembers`, `mbaCommunityUsage` and
  `mbaSupportTickets`; in `mbaDoubts` threads (which hold other students' answers) the student is anonymised: their posts
  stay as "Former student" without a `userId`, and their votes/reports are removed. Anonymous aggregates (`mbaTestScoreStats`) are kept.
  Never touches Java collections; the ProCounsellor account stays (the student is simply not onboarded to MBA any
  more). 422 without the exact confirm phrase. Idempotent (a second call deletes nothing).

## Community: doubts, study groups, events, help 🔒 (`mbaStudent`; admin parts 🛡)
Built in Python, not on the Java community (`communityQuestions`…): that model has no exam tag, no link to an MBA
question, no verified answers and is Java-owned (read-only here). The Java live sessions (`counsellorLiveSession`) have no
exam tag either, so MBA doubt hours/webinars are admin-managed in `mbaEvents`. The "weekly quiz" is the daily challenge +
weekly leaderboard (no separate quiz engine). Code: `api/mba/community.py`, `api/mba/support.py`.

### Doubts (one thread model for question doubts and group posts)
```ts
interface DoubtReply { id: string; by: "student" | "faculty"; authorName: string; isYours: boolean; text: string;
  verified: boolean /* faculty answers always; faculty can verify a student reply */; upvotes: number; youUpvoted: boolean;
  youReported: boolean; hidden: boolean /* only ever true on your own reply */; createdAt: string }
interface DoubtThread { id: string; scope: "question" | "group"; questionId: string | null; groupId: string | null;
  authorName: string; isYours: boolean; text: string; status: "open" | "resolved"; hidden: boolean /* own only */;
  upvotes: number; youUpvoted: boolean; youReported: boolean; replyCount: number; facultyAnswered: boolean;
  createdAt: string; lastActivityAt: string }
interface DoubtDetail extends DoubtThread { questionPreview: string | null /* ≤160 chars plain text, question doubts */;
  replies: DoubtReply[] /* verified first, then oldest first */ }
```
- `GET /questions/{id}/doubts` → `{ threads: DoubtThread[] /* open first, most upvoted, latest activity */;
  question: { id; section: SectionId | null; number: number | null; stemHtml: string } }`. `POST /questions/{id}/doubts`
  body `{ text: string /*5–2000*/ }` → 201 `DoubtDetail`. Same visibility rule as question reports: only after the student has
  seen the answer (answered it, or it was in a submitted attempt) and never while it is in their running mock → **403**; 404 unknown question.
- `GET /me/doubts` → `{ threads }` the caller started (question doubts + group posts), latest activity first.
- `GET /doubts/{id}` → `DoubtDetail` (403 without access to its question/group; 404 unknown or hidden by a moderator unless it is yours).
- `POST /doubts/{id}/replies` body `{ text }` → 201 `DoubtDetail` (409 when the thread has 100 replies).
- `PATCH /doubts/{id}` body `{ status: "open" | "resolved" }` → `DoubtDetail` (author only, else 403).
- `PUT /doubts/{id}/vote`, `PUT /doubts/{id}/replies/{replyId}/vote` body `{ up: boolean }` → `DoubtDetail` (idempotent).
- `POST /doubts/{id}/report`, `POST /doubts/{id}/replies/{replyId}/report` body `{ reason: "spam" | "abusive" | "off_platform" | "wrong" | "other" }`
  → `DoubtDetail`. One report per student per post; 422 on your own post. **3 distinct reports hide the post** until a moderator
  reviews it (a verified answer is never auto-hidden).
- Students never see userIds; names are the leaderboard display name, else first name + last initial.
- **Text filter (422 with a plain reason)**: abusive words; and for students also links, e-mail addresses, Indian mobile numbers
  (also spaced/dashed) and "message me on WhatsApp/Telegram/Instagram…" — keeps students on the platform. Faculty may post links.
- **Limits (429)** per student per IST day: 10 new threads/posts, 50 replies, 20 reports; 15 s between two posts.
  Counters: `mbaCommunityUsage/{userId}_{date}`.
- "Ask AI first": the app shows the existing AI tutor (`POST /ai/hint`, same daily quota) on the doubt page before the form.

### Study groups
Group id = `{exam}-{year}` (exam from the profile exam ids, year = this year … +2), label e.g. "CAT 2026". One group per student.
- `GET /groups` → `{ groups: GroupInfo[] /* every exam × year */; mine: GroupInfo | null; suggestedId: string | null /* profile exam + exam-date year */ }`,
  `GroupInfo = { id; label; exam; year; members }`.
- `PUT /me/group` body `{ groupId }` → `GroupInfo` (join or switch; 404 malformed id, 422 a past year). `DELETE /me/group` → 204.
- `GET /groups/{id}/posts` → `{ threads }`, `POST /groups/{id}/posts` body `{ text }` → 201 `DoubtDetail` — members only (403). Replies,
  votes, reports, status: the `/doubts/{id}…` endpoints above.
- `GET /groups/{id}/leaderboard` → `WeeklyBoard & { groupId; members }` — the weekly daily-challenge board (same rule, same
  opt-in via `PUT /me/leaderboard`) limited to the group's members; `participants` = opted-in members with results. Members only.

### Doubt hours and webinars (`mbaEvents`)
```ts
interface MbaEvent { id: string; title: string; description: string | null; kind: "doubt_hour" | "webinar";
  startsAt: string; endsAt: string /* ISO UTC */; link: string | null /* https only */; host: string | null;
  exams: string[] /* [] = everyone */; status: "scheduled" | "cancelled" }
```
- `GET /events` → `{ events: MbaEvent[] }` soonest first: not ended more than 2 h ago, starting within 90 days, and for one of the
  student's target exams (profile; default CAT) or for everyone. Cancelled events stay listed (shown as cancelled). Max 50.
- 🛡 `GET /admin/events?includePast=false` → `{ events: (MbaEvent & { createdBy; createdAt; updatedAt })[] }`;
  `POST /admin/events` body `{ title; description?; kind; startsAt; endsAt /* ISO with zone, ≤12 h after start */; link?; host?; exams?; status? }`
  → 201; `PUT /admin/events/{id}` (same body) → event; `DELETE /admin/events/{id}` → 204 (prefer `status: "cancelled"` so students see it).
  Capability `content` or `support`.

### Help-centre tickets
```ts
type TicketCategory = "account" | "mocks" | "questions" | "technical" | "data" | "feedback" | "other";
type TicketStatus = "open" /* waiting for support */ | "answered" | "closed";
interface Ticket { id: string; category: TicketCategory; subject: string; status: TicketStatus; attemptId: string | null;
  questionId: string | null; messages: { by: "student" | "support"; authorName: string; text: string; at: string }[];
  createdAt: string; updatedAt: string }
```
- `GET /me/tickets` → `{ tickets: Ticket[] }` (latest first). `GET /me/tickets/{id}` → `Ticket` (404 if not yours).
- `POST /me/tickets` body `{ category; subject /*3–120*/; message /*10–3000*/; attemptId?; questionId? }` → 201 `Ticket`
  (422 if the attempt isn't the caller's or the question is unknown). 5 tickets per IST day.
- `POST /me/tickets/{id}/messages` body `{ text /*≤3000*/ }` → `Ticket` (reopens it: `open`; 30 messages/day; 409 after 60 messages).
- `PATCH /me/tickets/{id}` body `{ status: "closed" }` → `Ticket`.
- Tickets are private between the student and support, so contact details are allowed (only abusive words are refused).
- 🛡 (capability `support`) `GET /admin/support/tickets?status=&category=&q=` → `{ tickets: AdminTicket[]; counts: { open; answered; closed } }`
  (`AdminTicket = Ticket & { userId; studentName; phoneNumber }`; open first; `counts` ignore `status`);
  `GET /admin/support/tickets/{id}`; `POST /admin/support/tickets/{id}/messages` body `{ text; status? }` → `AdminTicket`
  (status defaults to `answered`); `PATCH /admin/support/tickets/{id}` body `{ status }`.

### Faculty doubts queue 🛡 (capability `content` or `support`)
```ts
interface AdminDoubt { id; scope; questionId; groupId; paperId: string | null; section: SectionId | null; number: number | null;
  stemPreview: string; authorName: string; userId: string | null; text: string; status; hidden: boolean; hiddenReason: string | null;
  upvotes: number; reports: { reason: string; at: string }[]; replyCount: number; reportedReplies: number /* unreviewed */;
  facultyAnswered: boolean; escalated: boolean; createdAt; lastActivityAt }
interface AdminDoubtDetail extends AdminDoubt { replies: { id; by; authorName; userId: string | null; adminId: string | null; text;
  verified: boolean; hidden: boolean; hiddenReason: string | null; upvotes: number; reports: { reason; at }[]; createdAt }[] }
```
- `GET /admin/doubts?queue=escalated|unanswered|reported|hidden|all&scope=&limit=100` → `{ doubts: AdminDoubt[]; counts: { escalated; unanswered; reported; hidden; all } }`.
  **Escalated** = open, visible question doubt with no faculty answer for **24 h** (oldest first) — the escalation path.
  `unanswered` = the same without the 24 h wait; `reported` = student reports newer than the last moderator review.
- `GET /admin/doubts/{id}` → `AdminDoubtDetail` (hidden content included).
- `POST /admin/doubts/{id}/replies` body `{ text }` → 201 `AdminDoubtDetail` — a **verified** faculty answer (links allowed).
- `PATCH /admin/doubts/{id}` body `{ hidden?; status?; clearReports? }`, `PATCH /admin/doubts/{id}/replies/{replyId}` body
  `{ hidden?; verified?; clearReports? }` → `AdminDoubtDetail`. Every PATCH marks the post reviewed (clears it from `reported`
  until a new report). Faculty answers can't be un-verified (hide them instead).
