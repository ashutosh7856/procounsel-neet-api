# ProCounsel MBA — operations (backups, retention, AI cost)

Documentation only. Nothing here runs automatically and no script in this repo touches
production for these tasks. Run the commands yourself, from a machine logged in to gcloud
with an account that has `roles/datastore.importExportAdmin` on the project and write access
to the bucket.

## What is stored
Firestore is the shared production database (the Java backend uses it too). The MBA feature
only ever writes the `mba*` collections listed in `api/db/collections.py::WRITABLE_COLLECTIONS`:

| Kind | Collections |
|---|---|
| Content (authored by faculty, re-creatable from `data/mba/content` + Admin edits) | `mbaExams`, `mbaPapers`, `mbaQuestionSets`, `mbaQuestions`, `mbaPrograms`, `mbaGdpiItems` |
| Student data (personal) | `mbaProfiles`, `mbaAttempts`, `mbaAttemptAnalyses`, `mbaQuestionStats`, `mbaStudyTasks`, `mbaAiUsage`, `mbaShortlists`, `mbaCounsellorRequests`, `mbaNotificationState`, `mbaGdpiSessions`, `mbaLeaderboardPrefs`, `mbaDailyResults`, `mbaApplicationDocs` (records of uploaded application documents; the files live in storage, not Firestore) |
| Shared / anonymous | `mbaQuestionReports` (reporter id removed when a student deletes their data), `mbaTestScoreStats` (score histograms, no ids) |

Admin edits are versioned inside the docs themselves (`version` + last 50 `history` entries on
questions, sets and papers), so a backup also captures who changed what.

## Backup (Firestore export of the mba* collections)
One-off export to a Cloud Storage bucket in the same region as the database
(replace `PROJECT_ID` and `BUCKET`; create the bucket once with a lifecycle rule, below):

```bash
gcloud firestore export "gs://BUCKET/mba/$(date -u +%Y-%m-%dT%H%M)" \
  --project=PROJECT_ID \
  --collection-ids=mbaExams,mbaPapers,mbaQuestionSets,mbaQuestions,mbaTests,mbaPrograms,mbaGdpiItems,mbaProfiles,mbaAttempts,mbaAttemptAnalyses,mbaQuestionStats,mbaStudyTasks,mbaAiUsage,mbaShortlists,mbaCounsellorRequests,mbaNotificationState,mbaGdpiSessions,mbaQuestionReports,mbaLeaderboardPrefs,mbaDailyResults,mbaTestScoreStats,mbaApplicationDocs
```

Keep the `--collection-ids` list in step with `WRITABLE_COLLECTIONS` when a collection is added.
An export with `--collection-ids` can be imported back with `gcloud firestore import gs://BUCKET/mba/<folder>
--collection-ids=...` — an import OVERWRITES documents with the same ids, so restore into a copy
first (another project or database) and copy back only what is needed. Never import into the shared
production database without the co-founder's go-ahead.

**Suggested schedule:** daily at 02:30 IST (low traffic), keep 30 daily exports, plus one export before
every bulk content change (a paper import, a mass re-review). Ways to schedule it:
- Cloud Scheduler → a small Cloud Function / Cloud Run job that calls the Firestore export API with the
  same collection ids (Google's "Schedule data exports" guide), or
- Firestore managed scheduled backups (`gcloud firestore backups schedules create --database='(default)'
  --recurrence=daily --retention=14w`). Note these back up the WHOLE database (Java collections too),
  so agree it with whoever owns the Java backend first.

Bucket lifecycle (delete exports older than 30 days):
```bash
echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30,"matchesPrefix":["mba/"]}}]}' > lifecycle.json
gcloud storage buckets update gs://BUCKET --lifecycle-file=lifecycle.json
```

## Data retention
- **Content** (papers, questions, sets, programmes, GDPI items): kept indefinitely; never deleted by the app
  ("delete" in the Admin panel archives).
- **Student data**: kept while the student uses ProCounsel MBA. A student can delete it any time from
  *Profile → Delete my MBA data* (`POST /api/v1/mba/me/data/delete`): every per-student `mba*` document is
  deleted and their question reports are anonymised. Their ProCounsellor account (Java `users`) is not touched.
  Backups taken before the deletion still contain the data until they age out (30 days with the lifecycle
  above) — say so if a student asks.
- **AI usage counters** (`mbaAiUsage`, one small doc per student per active day): only needed for the daily
  quota and the ops panel. Suggested: delete docs older than 180 days (a manual, reviewed job; none exists).
- **Daily leaderboard results** (`mbaDailyResults`): suggested 90 days.
- When adding a per-student collection, add it to `api/mba/privacy.py::USER_COLLECTIONS`, the export list
  above and this table.

## AI cost (ops panel)
The Admin *MBA ops* page shows AI calls per day, top users and an **estimated** cost. `mbaAiUsage`
stores call counts, not tokens, so cost = calls × assumed tokens per call × price. All four numbers live in
`api/mba/ai_pricing.py` and can be overridden by env:

| Env | Default | Meaning |
|---|---|---|
| `MBA_AI_PRICE_INPUT_PER_MTOK_USD` | 0.15 | USD per 1M input tokens (gpt-4o-mini standard tier, https://developers.openai.com/api/docs/pricing, retrieved 2026-11-13) |
| `MBA_AI_PRICE_OUTPUT_PER_MTOK_USD` | 0.60 | USD per 1M output tokens (same source) |
| `MBA_AI_EST_INPUT_TOKENS` | 1500 | assumed prompt tokens per call |
| `MBA_AI_EST_OUTPUT_TOKENS` | 500 | assumed reply tokens per call |

Update the two prices whenever `OPENAI_MODEL` changes. For exact spend use the OpenAI usage dashboard.
