# Database (shared Firestore)

This API uses the main ProCounsellor Firestore (`procounsellor-71824`), shared with
the Java ProcounsellorApp backend. Existing data must never change, so:

- **Existing collections are read-only.** Everything in `JAVA_OWNED_COLLECTIONS`
  (`users`, `counsellors`, …) can be read but any write raises `ReadOnlyCollectionError`.
- **New collections are writable once registered** in
  `api/db/collections.py → WRITABLE_COLLECTIONS`. Seed scripts use the same guard.
- Never write through `snapshot.reference`; get a writable ref from `db.collection(...)`.

## Usage

```python
from fastapi import Depends
from api.db import SafeFirestore, get_db

@router.get("/something")
def something(db: SafeFirestore = Depends(get_db)):
    user = db.collection("users").document(uid).get()          # read existing: OK
    db.collection("myNewCollection").document(uid).set({...})  # registered new collection: OK
```

## Auth

Users log in through the main backend, which returns a JWT (`jwtToken`, subject =
phone number). `api/auth` verifies that same token with `PROCOUNSEL_JWT_SECRET` and
looks up the caller and role (read-only), so endpoints know who is calling:

```python
from api.auth import CurrentUser, require_roles

@router.get("/dashboard")
def dashboard(user: CurrentUser = Depends(require_roles("mbaStudent"))): ...
```

`GET /api/v1/auth/me` returns who a token belongs to.

Admin-panel users log in with `POST /api/auth/adminSignin` on the main backend, which signs
a JWT with the same key whose subject is the admin's login email — the id of their doc in
`admins` (Java `JwtUtil.getAuthenticatedAdmin`). `require_admin` verifies the token and
reads `admins/{subject}` (403 if missing); `require_admin_roles(...)` also checks its `role`:

```python
from api.auth import CurrentAdmin, require_admin

@router.get("/admin/thing")
def thing(admin: CurrentAdmin = Depends(require_admin)): ...  # admin.admin_id, admin.role
```

## Configuration

| Variable | Purpose |
|---|---|
| `FIREBASE_CREDENTIALS_PATH` | Path to the service-account JSON (local) |
| `FIREBASE_CONFIG` | Service-account JSON as a string (Vercel) |
| `PROCOUNSEL_JWT_SECRET` | Base64 HS256 key shared with the main backend's login JWTs (users and admins) |
| `FIREBASE_REALTIME_CONFIG` | Realtime Database URL (optional) |

Check the connection: `GET /api/v1/db/health`.
