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
  `document_pages`) and the backend-only `users` table if they do not exist.
- The first-administrator script below does the same before creating an account.

Run commands from the project root so the relative `DATABASE_PATH` resolves
correctly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

The `users` table is used only by the API. The Streamlit app does not use it and
is unaffected.

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
- The regulation and query endpoints are not protected yet.

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
