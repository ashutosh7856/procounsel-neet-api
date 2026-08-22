# Procounsel NEET API

FastAPI backend for Procounsel NEET counselling intelligence.

This API serves imported counselling data for:

- State-wise college search
- NEET score to estimated AIR
- MCC cutoff lookup
- Official state cutoff lookup
- Rank-based college recommendations
- Target college reach checks
- Gender/category/state fee-benefit guidance

## Run Locally

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive docs:

```text
http://127.0.0.1:8000/docs
```

Health check:

```http
GET http://127.0.0.1:8000/health
```

## Deploy On Vercel

Import this repository in Vercel as a Python/FastAPI project.

Recommended settings:

- Framework Preset: `Other`
- Build Command: leave empty
- Output Directory: leave empty
- Install Command: `pip install -r requirements.txt`

Vercel uses `api/index.py` as the serverless entrypoint and `vercel.json` rewrites all routes to the FastAPI app. After deploy, verify:

```http
GET https://your-vercel-domain.vercel.app/
GET https://your-vercel-domain.vercel.app/health
GET https://your-vercel-domain.vercel.app/docs
GET https://your-vercel-domain.vercel.app/api/v1/states
```

## Main Endpoints

- `GET /health`
- `GET /api/v1/states`
- `GET /api/v1/colleges`
- `GET /api/v1/score-rank`
- `GET /api/v1/fee-benefits`
- `GET /api/v1/mcc/metadata`
- `GET /api/v1/mcc/cutoffs`
- `GET /api/v1/state-cutoffs/metadata`
- `GET /api/v1/state-cutoffs`
- `POST /api/v1/predict`
- `POST /api/v1/target-college-check`

Full API reference: `docs/api-reference.md`

## Data Folders

- `data/reference/`: college directory, score-rank anchors, fee-benefit guidance
- `data/official/normalized/`: normalized MCC and official state cutoff JSON

## Import Official PDFs

MCC:

```bash
python -m api.mcc_import --pdf "path/to/mcc.pdf" --year 2026 --round R1 --source-url "https://mcc.nic.in/..." --out data/official/normalized/mcc-cutoffs.json
```

Maharashtra state CAP:

```bash
python -m api.state_cutoff_import --state maharashtra --pdf "path/to/maharashtra-cap.pdf" --year 2025 --round R1 --source-url "https://dmer.maharashtra.gov.in/english/admission/medical-admission/" --out data/official/normalized/state-cutoffs.json
```

## Accuracy Rule

Use official MCC, state counselling authority, government, NIC, or university counselling files as cutoff truth. Merit lists, seat matrices, schedules, news pages, coaching portals, and unofficial mirrors should not be treated as college closing cutoffs.
