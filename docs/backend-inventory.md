# Backend inventory (2026-11-11)

Every backend host the Website and Admin call, and what it serves. Goal: keep the
Java backend as the main app backend and migrate every Python/Node side service
into this repo (`procounsel-neet-api`).

| # | Host | What it is | Serves | Called from | Plan |
|---|---|---|---|---|---|
| 1 | `procounsellor-backend-1000407154647.asia-south1.run.app` | **Java main backend** (ProcounsellorApp, Cloud Run, prod `procounsellor-71824`) | Auth/OTP + JWT, users, counsellors, ProBuddies, school students, courses, test series, blogs, colleges, deadlines, leads, payments, community | Website `VITE_API_BASE_URL`, Admin `VITE_BACKEND_URL` | Stays |
| 2 | `procounsellor-procounsel-neet-api.vercel.app` | **This repo** (FastAPI) | MHT-CET predictor (`/api/v1/mht-cet/*`), NEET v1 counselling (`/api/v1/*`: states, colleges, score-rank, predict, cutoffs), all MBA (`/api/v1/mba/*`), auth/db health | Website `VITE_NEET_COUNSELLING_API_URL` (`neetCounselling.ts`, `procounselApi.ts`, `mhtcet.ts`), Admin `VITE_MBA_API_URL` | Target for everything |
| 3 | `neet-rank-predictor-two.vercel.app` | Separate NEET API (hard-coded, not in env) | NEET v2: `/api/predict-rank`, `/api/predict-colleges`, `/api/admission-probability`, `/api/round-cutoffs`, `/api/colleges`, `/api/options`, `/api/institutes`, `/api/state-counselling`, `/api/neet` | Website `src/api/neetV2.ts` (NEET rank/college predictors, cutoff analyzer, counselling directory), Vite dev proxies `/neet-api`, `/mhtcet-api` | Migrate → this repo |
| 4 | `college-search-api.vercel.app` | Node/Express (local repo `college-search-api`, SQLite `colleges.db`) | `/search` (college name autocomplete), `/study-abroad/predict`, `/assess` (Mettle AI career test), `/track-referrer` + `/referrers` (referral analytics) | Website `App.tsx` (referrer tracking), `api/user.ts` + `ProBuddiesRegistration.tsx` (college search), `studyAbroadPredictor.ts`, `MettleAssessment.tsx`; Admin `UserDetailPage.tsx`, `ReferrersPage.tsx` | Migrate → this repo |
| 5 | `chatbot-backend-364445951625.asia-south1.run.app` | Cloud Run service (separate GCP project) | Chatbot (`VITE_CHATBOT_API_URL`), JEE: `/jee-main/predict-rank`, `/jee-main/predict-colleges`; Admin college fees page | Website `api/jee.ts`, chatbot; Admin `CollegeFeesPage.tsx` | Migrate JEE predictors → this repo; chatbot later |
| 6 | `mht-cet-predictor-beige.vercel.app` | Old MHT-CET predictor | Mentioned only in a comment (`api/mhtcet.ts`); MHT-CET now served by #2 | — | Retire (confirm no traffic) |
| 7 | `procounsel-neet-api.vercel.app` | Older domain of this repo's Vercel project(s) | Fallback/older references | `procounselApi.ts`/`mhtcet.ts` comments, Admin `env.ts` | Check which Vercel project owns it; keep one |
| 8 | `state-city-provider.vercel.app` | Small Vercel service | State/city lists | Admin `src/lib/location.ts` | Migrate → this repo (or static JSON) |
| 9 | `procounsellor-backend-143388308141.asia-south1.run.app` | Second Java Cloud Run (likely develop/test project) | Only in a commented-out line in Website `.env` | — | Not used by prod code |

Also: `imiedu.s3.ap-south-1.amazonaws.com` = static images (S3), not a backend.

## Notes
- Several services are separate Vercel projects from (possibly) the same repos — check
  each project's Settings → Git and Domains. Env vars are per project.
- Migration order suggestion: #3 NEET v2 (highest SEO value, hard-coded URL), #5 JEE
  predictors, #4 college search / study-abroad / Mettle / referrers, #8 state-city, then
  retire #6/#7. Each migration keeps response shapes identical so the Website only
  changes a base URL, and the old service stays up until traffic moves.
