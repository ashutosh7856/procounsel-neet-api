# Procounsel NEET API Reference

Base URL for local development:

```text
http://127.0.0.1:8000
```

Run locally:

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive docs:

```text
http://127.0.0.1:8000/docs
```

## Health

```http
GET /health
```

Returns API status and loaded data counts.

## States

```http
GET /api/v1/states
```

Returns all states that have imported college records.

## Colleges

```http
GET /api/v1/colleges?state=Maharashtra&college_type=Private&q=dhule&limit=20&offset=0
```

Query params:

- `state`: state name or `All India`
- `college_type`: `All types`, `Government`, `Private`, `Deemed`
- `q`: optional college/city search
- `limit`: 1 to 500
- `offset`: pagination offset

College response rows include cutoff year metadata:

```json
{
  "rounds": {
    "R1": 273017,
    "R2": 300369
  },
  "round_years": {
    "R1": 2025,
    "R2": 2025
  },
  "round_sources": {
    "R1": "official_state_cutoff",
    "R2": "directory_reference"
  },
  "cutoff_year": 2025,
  "official_cutoffs": []
}
```

For directory rows without an explicit source year, the API marks imported cutoff ranks as `2025` because the current directory cutoff dataset is 2025-based. Official MCC/state cutoff rows use the exact normalized source year. When official state rows match a directory college, `round_sources` shows which rounds came from `official_state_cutoff` versus `directory_reference`, and `official_cutoffs` contains the parsed source rows.

## Score To Estimated AIR

```http
GET /api/v1/score-rank?score=610
```

Returns approximate AIR from imported score-rank anchors. This is an estimate, not an official NTA rank.

## Fee Benefits

```http
GET /api/v1/fee-benefits?state=Maharashtra&gender=Female&category=General&counselling=State%20quota
```

Returns state/gender fee benefit guidance and source notes where imported.

## MCC Cutoff PDF Import

The 1272-page MCC PDF should not be parsed on every frontend request. Import it once into normalized JSON, then serve it through the API.

Windows PowerShell:

```powershell
python -m api.mcc_import `
  --pdf "D:\path\to\mcc-final-result.pdf" `
  --year 2026 `
  --round R1 `
  --source-url "https://mcc.nic.in/..." `
  --out data/official/normalized/mcc-cutoffs.json
```

Mac/Linux shell:

```bash
python -m api.mcc_import \
  --pdf "/path/to/mcc-final-result.pdf" \
  --year 2026 \
  --round R1 \
  --source-url "https://mcc.nic.in/..." \
  --out data/official/normalized/mcc-cutoffs.json
```

Each normalized cutoff row keeps `authority`, `year`, `round`, `quota`, `category`, `course`, `collegeName`, `openingRank`, `closingRank`, `sourceUrl`, `sourceFile`, `sourcePages`, `contentHash`, and `verificationStatus`.

## MCC Metadata

```http
GET /api/v1/mcc/metadata
```

Returns whether MCC cutoffs are loaded, generated timestamp, row counts, years, rounds, quotas, categories, courses, and source file path.

## State Cutoff PDF Import

Official state allotment PDFs should be imported once into normalized JSON. Maharashtra CAP allotment PDFs are currently supported:

```powershell
python -m api.state_cutoff_import `
  --state maharashtra `
  --pdf "data\official\raw\maharashtra\2025\r1-admissions-to-health-science-courses-neet-ug-2025-2026-provisional-selection-list-only-for-mbbs-bds-courses-cap-round-1.pdf" `
  --year 2025 `
  --round R1 `
  --source-url "https://dmer.maharashtra.gov.in/english/admission/medical-admission/" `
  --out data\official\normalized\state-cutoffs.json
```

The normalized records keep authority, state, year, round, quota, college code, college name, course, category, opening rank, closing rank, source file, source pages, content hash, and verification status.

## State Cutoff Metadata

```http
GET /api/v1/state-cutoffs/metadata
```

Returns whether official state cutoffs are loaded, generated timestamp, row counts, states, years, rounds, categories, courses, and source path.

## State Cutoffs

```http
GET /api/v1/state-cutoffs?state=Maharashtra&year=2025&round=R1&category=OPEN&course=MBBS&max_closing_rank=130000&limit=20
```

Query params:

- `state`: optional state name
- `year`: optional counselling year
- `round`: optional round label such as `R1`
- `category`: optional category; `General`, `GEN`, and `UR` map to `OPEN`
- `course`: optional course, such as `MBBS` or `BDS`
- `college_name`: optional partial college name search
- `max_closing_rank`: optional rank ceiling
- `limit`: 1 to 500
- `offset`: pagination offset

## MCC Cutoffs

```http
GET /api/v1/mcc/cutoffs?year=2026&round=R1&course=MBBS&category=OPEN&quota=AIQ&college_name=AIIMS&max_closing_rank=5000&limit=20&offset=0
```

Query params:

- `year`: optional counselling year
- `round`: optional round label such as `R1`, `R2`, `R3`, `Stray`
- `quota`: optional quota, such as `AIQ`, `DEEMED`, `ESIC`
- `category`: optional category, such as `OPEN`, `OBC`, `SC`, `ST`, `EWS`
- `course`: optional course, such as `MBBS`, `BDS`
- `college_name`: optional partial college name search
- `max_closing_rank`: optional rank ceiling
- `limit`: 1 to 500
- `offset`: pagination offset

Response shape:

```json
{
  "total": 1,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "authority": "MCC",
      "year": 2026,
      "round": "R1",
      "quota": "AIQ",
      "category": "OPEN",
      "course": "MBBS",
      "collegeName": "Example Medical College",
      "openingRank": 1200,
      "closingRank": 3500,
      "allottedRows": 12,
      "sourceUrl": "https://mcc.nic.in/...",
      "sourceFile": "mcc-final-result.pdf",
      "sourcePages": [12, 13],
      "contentHash": "sha256...",
      "verificationStatus": "parsed_from_official_pdf"
    }
  ],
  "source": "data/official/normalized/mcc-cutoffs.json"
}
```

## Predictor

```http
POST /api/v1/predict
Content-Type: application/json
```

Example with AIR:

```json
{
  "neet_air": 111000,
  "domicile": "Maharashtra",
  "category": "General",
  "gender": "Female",
  "budget": "60L",
  "counselling": "State quota",
  "target_type": "Private",
  "limit": 10
}
```

Example with score only:

```json
{
  "neet_score": 484,
  "domicile": "Maharashtra",
  "category": "General",
  "gender": "Female",
  "budget": "60L",
  "counselling": "State quota",
  "target_type": "All types",
  "limit": 10
}
```

Response includes:

- `rank_used`
- `rank_label`
- `budget_rupees`
- `official_state_cutoff_pool`
- `ranked_pool`
- `unranked_pool`
- `excluded_by_budget`
- `category_warning`
- `items`

## Target College Check

```http
POST /api/v1/target-college-check
Content-Type: application/json
```

Example:

```json
{
  "college_name": "ACPM Medical College",
  "target_state": "Maharashtra",
  "neet_air": 111000,
  "domicile": "Maharashtra",
  "category": "General",
  "gender": "Female",
  "budget": "60L",
  "counselling": "State quota",
  "target_type": "Private"
}
```

Returns whether the college matched and a verdict such as `High chance`, `Good chance`, `Borderline`, `Low chance`, `Verify`, or `Need score/rank`.

## Important Data Warning

The API uses imported reference data from `data/reference/*.json`. College names, cutoffs, fee tracks, source notes, and benefits must be verified with MCC, state counselling authorities, official fee orders, and college notices before final choice filling.
