# ProCounsel MBA — developer handoff (2026-11-13)

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

Dashboard ("Road to IIM" levels, countdown, priorities, streak, score estimate, exam updates) ·
question bank + practice (204 ProCounsel originals + **1,854 actual CAT questions, 24 papers
2017–2025**, source/year filters, bookmarks, confidence tags) · mock engine (server timers,
autosave, resume, idempotent submit, per-exam timer blocks and marking) · **past papers**
(`/mba/pyq`, full + sectional, ProCounsel percentile per paper once 20+ students took it) ·
**score estimator** (`/me/score-estimate`, range + confidence from mocks/PYQs/practice/daily) ·
**practice modes** (timed drills, weak-topic and mixed sets, custom test builder) · **other exams**
(XAT, SNAP, NMAT, CMAT, MAT, GMAT, MAH-CET configs from official sources; original mocks for
XAT/SNAP/NMAT/CMAT) · mistake notebook · daily challenge + leaderboard · AI tutor, **AI section
coaches** (VARC/DILR/Quant), "Explain my plan", AI mock analyst · insights · study planner ·
**CAT syllabus** (47 subtopics, concept notes, progress, private notes) · notifications ·
GDPI prep (+ **voice answers**, **mock interview booking**) · **community** (question doubts,
faculty escalation queue, study groups, events) · **help centre + support tickets** · colleges
(all 65, eligibility, compare, ROI, deadlines, shortlist, checklist, **document upload**,
**admission outcomes**) · **counsellor workflow** (real assignment, pipeline, notes, follow-ups,
CSV, student consent) · **exam-update feed** · Admin: content review, **paper/question authoring
for every exam**, scheduling, versioning, **finer roles**, **ops panel** (AI cost), **metrics**,
doubts, support, events, requests · **GA4 funnel events** · **delete my MBA data** ·
public SEO/AEO pages (130 routes incl. `/cat-previous-year-papers`).

## Left from the PDF

1. **Paid plans** — skipped on purpose (free at launch). Entitlement checks would go server-side.
2. **Email/SMS/WhatsApp notifications** — in-app only; needs DLT-registered MSG91 templates /
   Meta WhatsApp approval.
3. **Notifying the counsellor directly** — needs a Java endpoint to push/email one counsellor;
   admins use the per-counsellor view meanwhile. Counsellor-side view inside the Java app.
4. **GDPI video practice** and college-specific interview pages (no official WAT/PI format data).
5. **Real-time peer rooms/chat** — not built by design (threads + groups instead).
6. **GMAT Data Insights multi-part questions** — not representable; GMAT practice is MCQ only and
   non-adaptive (labelled as such). No mocks yet for MAT, GMAT, MAH-CET.
7. **Error monitoring** (e.g. Sentry) — not added.

## Content review queue (faculty)
- PYQ papers were transcribed from the supplied PDFs and solved by us (2017–2020 cross-checked
  against the publisher key; disagreements documented in each solution). Judgement-call answers
  (mostly VARC para-jumbles/odd-one-out) should be skimmed in Admin before/after publishing.
  Known points: cat-2025-slot1 DILR-16 converted from type-in to MCQ (answer was names);
  cat-2022-slot2 DILR-06 reportedly dropped by IIM (solution says so); a few source typos fixed
  (e.g. cat-2025-slot3 QA-02 sign) — verify against an official copy if available.
- New original mocks pc-xat/snap/nmat/cmat-mock-01 are drafts; flagged items listed in the
  multi-exam section of docs/mba-api.md history / PR notes.

## Known gaps / small fixes
- Leaderboard records a day's results only when someone loads a board that day.
- AI quota is checked before and counted after the model call (can slightly exceed under
  parallel requests). Content cache TTL is 5 min (`MBA_BANK_TTL_SECONDS`).
- ProCounsel percentile only counts attempts submitted after this release (no backfill).
- Built tests across several sections use one timer per section, not one shared clock.
- Admin lists for doubts/tickets read whole collections — add paging as volume grows.
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
- New optional env: `BUCKET_NAME=procounsellor-71824.firebasestorage.app` (document upload), `MBA_TRANSCRIBE_MODEL`,
  `MBA_ADMIN_ROLES_*`, `MBA_AI_PRICE_*`, `MBA_METRICS_TTL_SECONDS`. Website: `VITE_GA4_MEASUREMENT_ID`.
- After the API deploy: `seed_exam --all` (other exams) and import the 4 non-CAT mocks as drafts.
- Rotate secrets that were shared in chat (Firebase key, Razorpay, Twilio, MSG91, mail, Zoom, YouTube, Facebook).
