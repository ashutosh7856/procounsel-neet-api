# ProCounsel MBA — developer handoff (2026-11-12)

What is built, what is left from the product PDF
(`ProCounsel_MBA_Product_Feature_and_Implementation_Proposal.pdf`), and where things live.

## Where things live

| Area | Location |
|---|---|
| MBA API (FastAPI) | `procounsel-neet-api/api/mba/*` — one module per feature, routers included from `api/mba/routes.py` |
| DB safety | `api/db/` — `SafeFirestore` write guard; only collections in `api/db/collections.py::WRITABLE_COLLECTIONS` are writable; Java collections are read-only |
| Auth | `api/auth/` — verifies the Java backend's HS256 login JWT (`PROCOUNSEL_JWT_SECRET`); `require_roles("mbaStudent")`, `require_admin_roles(...)` |
| API contract | `docs/mba-api.md` (source of truth), `docs/mba-content-format.md`, `docs/backend-inventory.md` |
| Data + sources | `data/mba/` (official data, `SOURCES.md` lists every source), `data/mba/content/` (mock papers), `data/mba/gdpi/` |
| Import scripts | `scripts/mba/` — `seed_exam`, `import_paper` (`--publish`, `--force`), `import_programs`, `import_gdpi`; all idempotent, `--dry-run` supported |
| Student app | `Website/src/pages/mba/*`, `src/layouts/MbaStudentLayout.tsx`, `src/api/mba*.ts`, `src/components/mba/*` |
| Public SEO pages | `Website/src/pages/mba-public/*`, `src/components/mba-public/*`, snapshot `scripts/generate-mba-snapshot.mjs` → `src/data/mbaSnapshot.ts`; plan in `Website/docs/MBA-SEO-BLUEPRINT.md` |
| Admin | `Admin/src/pages/MbaContentPage.tsx`, `MbaPaperReviewPage.tsx`, `MbaRequestsPage.tsx`, `src/components/mba/MbaReportsPanel.tsx` |

Note: the backend verification suites (fake Firestore, ~2,700 checks) were run from a
throwaway scratchpad and are **not in the repo**. Adding a real `tests/` folder is a
good first task for the next developer.

## Built (PDF modules)

Dashboard ("Road to IIM" levels, countdown, priorities, streak) · question bank + practice
(204 original CAT-pattern questions, filters, bookmarks, answer reveal) · mock engine
(server timers, autosave, resume, idempotent submit, scoring, review; 3 full + 9 sectionals) ·
mistake notebook with spaced review · daily challenge + opt-in leaderboard · AI tutor (hints) ·
AI mock analyst + deterministic analysis · topic insights / weakness detector · study planner
(rule-based weekly plan, auto-complete, .ics) · in-app notifications · GDPI prep (231 WAT/GD/PI
items, AI mock PI and timed WAT with feedback) · Learn tab (lists existing courses) ·
college data (21 IIMs + 44 others, official sources), eligibility check, compare, ROI,
deadlines, shortlist + application checklist · counsellor requests (Admin assigns) ·
question issue reports (Admin triage) · Admin content review/edit/publish · 129 public MBA
SEO/AEO pages + CAT score calculator, CAT college predictor, free-mocks page.

## Left from the PDF

### Blocked by data (not code)
- **PYQs** — IIMs don't publish past papers publicly. Bank uses ProCounsel originals.
- **Score → percentile estimator** — no official benchmark data. Don't fake it.

### Product features not built
1. **Other exams (XAT, SNAP, NMAT, CMAT, MAT, GMAT)** — mock engine is CAT-only
   (`SectionId` = VARC/DILR/QA in `api/mba/models.py`). Needs per-exam versioned configs
   (sections, timing, marking — data already in `data/mba/exams/*.json`), engine
   generalisation, then content. ~1–2 days engine + content time.
2. **Native LMS** — Learn tab only lists existing Java courses (matched by "MBA/CAT" in the
   title; Java course model has no exam tag). Missing: proper MBA/exam tag on courses,
   lesson completion/progress, lesson notes/bookmarks, syllabus hierarchy
   (section → topic → lesson), faculty lesson CMS/versioning.
3. **Practice modes** — timed drills, mixed/weak-topic sets, custom test builder,
   question randomisation, scheduled tests.
4. **Test authoring UI** — papers are authored as JSON and imported; Admin can only
   review/edit/publish. Missing: create questions/papers in Admin, test scheduling/versions.
5. **Question extras** — alternative approaches, diagrams/images, solution videos,
   student self-rated confidence.
6. **Section coaches (AI)** — VARC/DILR/Quant-specific coaches; AI explanation for the planner.
7. **Community** — study groups/cohorts, peer rooms, community Q&A, faculty doubt hours,
   weekly quizzes/webinars (could reuse existing live sessions), moderation + anti-cheating.
8. **Applications** — document upload (checklist is tick-only), student-controlled sharing
   with counsellor, admission outcome tracking.
9. **Counsellor workflow** — assignment is a recorded name only: no notification to the
   counsellor, no counsellor-side view of assigned MBA students, no follow-up history.
10. **GDPI extras** — recorded (audio/video) practice, faculty/counsellor mock interview
    booking, college-specific interview spaces.
11. **Notifications** — in-app only. Email/SMS/WhatsApp need DLT-registered templates
    (MSG91) / Meta approval; exam-update feed (admit card, answer key, results) is manual.
12. **Support** — help centre, tickets, doubt escalation.
13. **Admin roles** — only `MBA_CONTENT_ADMIN_ROLES` (default `superAdmin,COURSE`); no
    separate faculty / test manager / student-support roles.
14. **Paid plans** — skipped (free at launch). Entitlement checks would go server-side.
15. **Ops** — AI cost/usage dashboard, consent + data retention/deletion workflows,
    scheduled Firestore backups (`gcloud firestore export`), error monitoring.
16. **Analytics** — PDF success metrics (activation, time-to-value, mock completion,
    plan adherence) as GA4 events + a weekly report.

## Known gaps / small fixes
- In-app colleges list (`/mba/colleges`) shows IIMs only, but the shortlist API now accepts
  all 44 bundled colleges — add non-IIM colleges to that list/search.
- Leaderboard records a day's results only when someone loads a board that day.
- AI quota is checked before and counted after the model call (can slightly exceed under
  parallel requests). Content cache TTL is 5 min (`MBA_BANK_TTL_SECONDS`).
- `docs/database.md` was deleted in a commit — restore with `git checkout <rev> -- docs/database.md`.
- 60-percentile SEO page is gated (only 4 official cutoffs ≤60); author bylines are generic
  until real counsellor names/credentials are added.
- Other side backends still to migrate into this repo: see `docs/backend-inventory.md`.

## Deploy checklist
- Vercel project that owns `procounsellor-procounsel-neet-api.vercel.app`: `FIREBASE_CONFIG`,
  `PROCOUNSEL_JWT_SECRET`, `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-4o-mini` (+ optional
  `MBA_AI_DAILY_LIMIT`, `MBA_CONTENT_ADMIN_ROLES`, `MBA_BANK_TTL_SECONDS`). Verify
  `/api/v1/db/health` → `"ok": true`.
- `.vercelignore` excludes import-only data; `data/mba/programs`, `colleges`, `exams/*.json`
  must stay (read at runtime by applications/planner).
- Website/Admin: `VITE_NEET_COUNSELLING_API_URL` = the API URL (GitHub secret).
- After Website deploy: resubmit sitemap in Google Search Console + Bing Webmaster Tools.
- Rotate secrets that were shared in chat (Firebase key, Razorpay, Twilio, MSG91, mail, Zoom, YouTube, Facebook).
