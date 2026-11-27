# CohortIQ AI

CohortIQ AI is an Intelligent Academic Regulation & Cohort Impact Navigator. This repository is being set up as a modular Python + Streamlit MVP foundation for working with academic regulation documents, extracting content, retrieving relevant context, and generating grounded responses with citations.

## Project status

This workspace currently contains the initial project structure and module skeletons only.

- The full application is **not implemented yet**.
- Modules include placeholders and `NotImplementedError` markers where future logic will be added.
- No fake functionality is included.

## Project structure

```text
CohortIQ1/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── pdf_processor.py
│   ├── chunking.py
│   ├── retrieval.py
│   ├── gemini_service.py
│   ├── citation_validator.py
│   └── models.py
├── data/
│   ├── uploads/
│   └── extracted/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Prerequisites

- Python 3.11+ (recommended)
- An existing virtual environment in `.venv/` (already created in this workspace)
- A Gemini API key for future AI features

## Setup

1. Activate the existing virtual environment.

   **PowerShell (Windows):**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

3. Create a local `.env` file from the example.

   ```powershell
   Copy-Item .env.example .env
   ```

4. Add your environment values in `.env`.

   Example:
   ```env
   GEMINI_API_KEY=your_api_key_here
   GEMINI_MODEL=gemini-1.5-flash
   DATABASE_PATH=data/cohortiq.db
   UPLOAD_DIR=data/uploads
   EXTRACTED_DIR=data/extracted
   ```

## Environment variable security

- Never hardcode API keys or secrets in source code.
- Keep secrets in `.env`, which is ignored by Git.
- Use `.env.example` as a safe template for required variables.

## FastAPI backend: database and first administrator

### Database initialization

The backend uses the same SQLite database as the Streamlit app (`DATABASE_PATH`,
default `data/cohortiq.db`). Tables are created automatically, and existing data
is never modified:

- Starting the API creates the regulation tables (`regulations`,
  `document_pages`), the backend-only `users` table and the append-only
  `audit_events` table if they do not exist.
- The first-administrator script below does the same before creating an account.

Run commands (including `pytest`) from the project root so the relative
`DATABASE_PATH` resolves correctly. From another directory, the relative path
points to a different, empty database file:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

The `users` and `audit_events` tables are used only by the API. The Streamlit
app does not use them and is unaffected.

### Authentication settings

Copy the authentication section of `.env.example` into your `.env`. For any
deployment, set a strong signing secret in `.env` (never commit it):

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the output as `JWT_SECRET_KEY=` in `.env`. With `APP_ENV=production` the
API refuses to start if `JWT_SECRET_KEY` is missing or weak (shorter than 32
bytes, repetitive, or a placeholder value).

### Creating the first administrator

Administrators cannot be created through the API. Create the first one from an
interactive terminal:

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.create_admin --email admin@university.edu --full-name "Registrar Office"
```

- The password is entered twice at a hidden prompt. It cannot be passed as a
  command-line argument, and the command refuses to run when input is piped.
- Passwords must be at least 12 characters and use at least three of lowercase,
  uppercase, digits and symbols (or be a passphrase of 20+ characters). Common
  words such as "password", repetitive passwords and passwords containing the
  email name are rejected.
- If an account with the same email already exists (in any letter case or role),
  nothing is created or changed.
- Passwords are stored only as Argon2id hashes and are never printed or logged.
- Use `--db-path PATH` to target a different SQLite file.
- The account and a `user.created` audit event (actor type `cli`) are written
  in one transaction. If either cannot be stored, no account is created. The
  audit event contains no email address, name or password.

### Signing in

- `POST /api/v1/auth/login` takes `{"email": "...", "password": "..."}` and
  returns `{"access_token": "...", "token_type": "bearer", "expires_in": 1800}`.
  Unknown emails, wrong passwords, inactive accounts and locked accounts all get
  the same `401` response.
- `GET /api/v1/auth/me` returns the signed-in user's profile. Send the token as
  `Authorization: Bearer <access_token>`.
- After `LOGIN_MAX_FAILED_ATTEMPTS` (default 5) consecutive failed sign-ins, the
  account is locked for `LOGIN_LOCKOUT_MINUTES` (default 15). Locks always
  expire, and a successful sign-in resets the counter.
- Sign-in requires `JWT_SECRET_KEY` to be set; without it the endpoints return `503`.
- Sign-in attempts are audited (see [Audit log](#audit-log)). If the audit event
  cannot be written, the attempt is rolled back and `503` is returned.

## API access control

Every route is classified in `backend/app/api/permissions.py`, and a test fails
if a route is added without a classification or with dependencies that do not
match it. Roles and cohorts are always read from the `users` table, never from
the token or the request. All paths below start with `/api/v1`.

| Access | Routes |
|---|---|
| Public | `GET /health`, `POST /auth/login` (plus `GET /`, `/docs`, `/redoc`, `/openapi.json`) |
| Any signed-in user | `GET /auth/me`, `GET /regulations`, `GET /regulations/{regulation_id}`, `GET /regulations/{regulation_id}/pages`, `GET /cohorts/{admission_batch}/{programme}/regulations`, `POST /query/ask` |
| Administrators only | `POST /regulations/ingest`, `PATCH /regulations/{regulation_id}/verification`, every `/admin/users...` route, `GET /admin/audit-events` |

- Missing, invalid, expired or revoked tokens and inactive accounts get `401`.
  Students calling an administrator route get `403`.
- Students see approved regulations only. On the cohort route and
  `POST /query/ask`, students may only use the admission batch and programme
  stored on their account (`403` otherwise). Administrators may use any cohort.

## Administrator user management

All routes require an administrator, return `Cache-Control: no-store`, and
never return password hashes, token versions, failed sign-in counters or lock
expiry. Account responses contain `id`, `email`, `role`, `full_name`,
`admission_batch`, `programme`, `is_active`, `is_locked`, `last_login_at`,
`created_at` and `updated_at`. Unknown request fields and query parameters are
rejected with `422`.

| Route | Behaviour |
|---|---|
| `GET /admin/users` | List accounts, ordered by id. Exact-match filters: `role`, `is_active`, `admission_batch`, `programme`. `limit` 1–100 (default 50), `offset` 0–1,000,000. Returns `users`, `total`, `limit`, `offset`. |
| `POST /admin/users` | Create a **student** (`201`). Body: `email`, `password`, `admission_batch`, `programme`, optional `full_name`. There is no role field. The password must meet the password policy. A duplicate email gets `409`. |
| `GET /admin/users/{user_id}` | One account. |
| `PATCH /admin/users/{user_id}` | Change `full_name`, `admission_batch` and/or `programme` (at least one; `null` clears a value). Students must keep a cohort. |
| `PATCH /admin/users/{user_id}/role` | Body `{"role": "student"}`: demote an administrator. Granting `administrator` is always refused (`403`). |
| `POST /admin/users/{user_id}/password` | Body `{"new_password": "..."}`: set a **student's** password. Refused (`403`) for your own account and for any administrator. |
| `POST /admin/users/{user_id}/deactivate` | Deactivate the account. |
| `POST /admin/users/{user_id}/reactivate` | Reactivate an inactive account. |
| `POST /admin/users/{user_id}/unlock` | Clear the failed sign-in counter and any temporary lock. |
| `POST /admin/users/{user_id}/revoke-sessions` | Invalidate every access token issued to the account. |

Policy:

- **Administrators can only be created with the CLI** (see above). The API
  cannot create or promote administrators.
- Administrators cannot change their own role or active status, or reset their
  own password (`403`). The last active administrator cannot be demoted or
  deactivated (`409`).
- Demotion, deactivation, password reset and `revoke-sessions` revoke the
  account's existing tokens. Reactivation does not restore them; the user must
  sign in again.
- Each change runs in one transaction that re-checks the acting administrator
  and writes the audit event. Requests that would change nothing write nothing.
  A concurrent change to the same account can return `409` ("please retry").
- Unknown accounts get `404`. Self-service password change and forced password
  change at first sign-in are not implemented.

## Audit log

The `audit_events` table records security-relevant actions. It is append-only:
SQLite triggers abort any update, delete or replacing insert. (Anyone with
direct write access to the database file can still alter it.) Events are kept
indefinitely; there is no automatic retention or deletion.

Events never contain passwords, password hashes, tokens, email addresses, client
IP addresses, question text or document content. Full names are never recorded.
Every action and detail key comes from a fixed allowlist in
`backend/app/audit/repository.py`.

### What is recorded

| Action | When |
|---|---|
| `auth.login_succeeded` | Successful sign-in. |
| `auth.login_failed` | Failed sign-in to an **existing** account (`reason`: `invalid_password`, `account_locked` or `account_inactive`). Unknown emails are not recorded. |
| `auth.account_locked` | A failed sign-in locked the account. |
| `user.created` | First administrator created by the CLI, or a student created through the API. |
| `user.updated` | Profile change: the changed field names and old/new cohort values. |
| `user.role_changed`, `user.deactivated`, `user.password_reset` | Successful changes, and refusals (outcome `denied`, with a `reason`). |
| `user.reactivated`, `user.unlocked`, `user.sessions_revoked` | Successful changes. |
| `regulation.ingested` | Successful ingestion, or a failure during processing (`reason`: `invalid_metadata`, `invalid_pdf` or `internal_error`). |
| `regulation.verification_changed` | Verification status changed (old and new status). |
| `authorization.denied` | A signed-in user was refused with `403` (`reason`: `insufficient_role` or `cohort_mismatch`), with the HTTP method and route template (never the concrete URL). |

Not recorded:
- anonymous or `401` requests and sign-ins with unknown emails;
- requests that fail validation before any change is attempted (`422`), and
  unknown targets (`404`);
- uploads rejected before processing (file type, metadata format, size or page
  count);
- verification requests for missing regulations or invalid statuses;
- failed CLI attempts;
- a sign-in refused because the password changed during that sign-in;
- reading the audit log.

### Consistency and limitations

- **Same transaction:** sign-in events, user-management changes and refusals,
  and the CLI bootstrap. If the audit event cannot be written, the change is
  rolled back: sign-in returns `503`, user management returns `500`, and the
  CLI creates no account.
- **Not atomic: ingestion and verification.** The shared workflow code in
  `app/` manages its own database connections, so the event is written after
  the change. If that write fails, the API undoes the change and returns `500`:
  - ingestion deletes the new pending regulation;
  - verification restores the previous status, unless the status changed again
    in the meantime or could not be read.

  A crash between the change and the audit write, or a failed undo (logged at
  CRITICAL), can still leave an unaudited change.
- **Best effort: authorization refusals.** The `403` is always returned; if
  its audit event cannot be written, the failure is logged at ERROR.

### Listing audit events

`GET /api/v1/admin/audit-events` (administrators only, read-only).

- **Filters:** `action`, `outcome`, `actor_user_id`, `target_type` (`user` or
  `regulation`), `target_id` (requires `target_type`), `occurred_after` and
  `occurred_before`.
  - The time bounds are inclusive and must include a timezone offset, for
    example `2026-01-01T00:00:00Z`.
  - Unknown actions or parameters get `422`.
- **Order and pages:** newest first; events with the same timestamp are
  ordered by id, highest first. `limit` 1–100 (default 50), `offset`
  0–1,000,000.
- **Response:** `events`, `total`, `limit`, `offset`. Each event has `id`,
  `occurred_at`, `action`, `outcome`, `actor_type`, `actor_user_id`,
  `actor_role`, `target_type`, `target_id` and `details`.
- **Withheld details:** `details` contains only allowlisted keys. The failed
  sign-in counter (`failed_login_count`) and lock expiry (`locked_until`)
  recorded for sign-in events are never returned.
- **Reads are not audited.** A student's refused request is still recorded as
  `authorization.denied`.

## Administrator account recovery

There is **no dedicated recovery command**. These are the verified options:

- **Locked out:** the lock expires after `LOGIN_LOCKOUT_MINUTES`, or another
  administrator can call `unlock`.
- **Deactivated:** another administrator can call `reactivate`.
- **Lost or exposed token:** another administrator can call `revoke-sessions`.
- **Forgotten password:** the API cannot reset any administrator's password.
  - Someone with shell access to the server and database can run the
    first-administrator script with a **different** email to create a new
    administrator. This works even if no usable administrator remains.
  - The new administrator can then deactivate or demote the old account.
  - The old email cannot be reused: the script refuses existing emails and
    accounts are never deleted. A demoted account cannot be promoted again
    through the API.

A secure recovery procedure for administrator accounts (for example, resetting
an administrator's password from the command line) is not implemented. It
should be documented or addressed before production.

## Planned module responsibilities

- `app/main.py`: Streamlit entry point and UI orchestration.
- `app/config.py`: Environment-backed application configuration.
- `app/database.py`: Database connection and persistence helpers.
- `app/pdf_processor.py`: PDF text and metadata extraction.
- `app/chunking.py`: Splitting extracted text into retrieval-friendly chunks.
- `app/retrieval.py`: Finding relevant chunks for user queries.
- `app/gemini_service.py`: Gemini API interaction using configured secrets.
- `app/citation_validator.py`: Verifying that responses are grounded in sources.
- `app/models.py`: Shared data structures used across modules.

## Notes

- `data/uploads/` is intended for uploaded source files.
- `data/extracted/` is intended for extracted or intermediate text artifacts.
- `tests/` is reserved for future automated tests.

## Next steps

Future development can incrementally implement:

1. PDF ingestion and extraction
2. Chunking and retrieval
3. Gemini-backed question answering
4. Citation validation
5. Streamlit user interface
6. Automated tests in `tests/`
