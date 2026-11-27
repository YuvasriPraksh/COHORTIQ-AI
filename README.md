# CohortIQ AI
### Intelligent Academic Regulation & Cohort Impact Navigator

**Every Rule. Every Cohort. The Right Answer.**

> **Rules decide. AI explains.**

CohortIQ AI is an intelligent academic regulation platform designed to help students and academic administrators understand, verify, and manage academic regulations across different admission batches and programmes.

Academic regulations often change between cohorts. A rule that applies to one admission batch may not apply to another. Finding the correct rule in lengthy documents can be difficult, time-consuming, and error-prone.

CohortIQ AI aims to make academic regulation information **cohort-aware, traceable, and easier to verify** by combining deterministic rule applicability, regulation document processing, evidence-grounded AI, and secure administrative workflows.

---

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [Our Solution](#our-solution)
- [Key Features](#key-features)
- [How It Works](#how-it-works)
- [Core Design Principle](#core-design-principle)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Current Implementation Status](#current-implementation-status)
- [Getting Started](#getting-started)
- [API Overview](#api-overview)
- [Security](#security)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [Project Information](#project-information)

---

## Overview

CohortIQ AI is designed to answer academic regulation questions using the regulation context applicable to a student's admission batch and programme.

Instead of treating regulations as ordinary documents, the platform is being developed to support a structured lifecycle:

1. Ingest academic regulation documents.
2. Extract and organize regulation content.
3. Verify regulation information through an administrative workflow.
4. Determine which regulation applies to a cohort using explicit rules.
5. Retrieve relevant supporting evidence.
6. Generate answers grounded in that evidence.
7. Support regulation comparison and cohort impact analysis.

The platform is intended to serve both students seeking clear answers and administrators responsible for maintaining reliable academic regulation information.

## The Problem

Academic regulation information is often distributed across lengthy PDFs, circulars, and documents published for different admission batches or programmes.

This creates several challenges:

- Students may struggle to identify the regulation applicable to their cohort.
- Similar questions may have different answers under different regulation versions.
- Manually searching long documents takes time.
- Generic AI chatbots may retrieve relevant-looking content without determining whether it applies to the student.
- Administrators may find it difficult to identify which cohorts are affected when a regulation changes.
- Answers without traceable evidence can lead to confusion or misplaced confidence.

## Our Solution

CohortIQ AI combines structured regulation handling with cohort-aware retrieval and AI-assisted explanation.

The system is designed to:

- Associate regulation information with admission batches and programmes.
- Use deterministic logic to determine applicable regulation context.
- Retrieve evidence from the relevant regulation material.
- Generate answers supported by source references.
- Restrict student access to permitted information.
- Provide administrative controls for regulation ingestion and verification.
- Extend toward version comparison and cohort impact analysis.

**The system does not rely on an LLM alone to decide which regulation applies.** Applicability is determined through explicit application logic. AI is used to assist with document understanding and explain retrieved evidence.

---

## Key Features

### 1. Cohort-Aware Regulation Access

Regulation information can be associated with an admission batch and programme.

The backend checks a student's cohort against the cohort information stored on their account before processing cohort-specific requests.

This helps ensure that cohort-specific queries use the intended regulation context.

### 2. Regulation Document Ingestion

The existing application supports PDF-based regulation processing.

The backend provides regulation ingestion functionality, while the regulation workflow handles document processing and storage.

### 3. Regulation Verification

Regulations have verification status.

Administrative verification controls whether regulation content is available to students. Unapproved regulation content is not intended to be used as student-facing evidence.

### 4. Evidence-Grounded Question Answering

The existing application retrieves regulation content and uses it to support AI-generated answers.

The system is designed to provide source references so users can check the regulation evidence behind an answer.

### 5. Secure API Access

The FastAPI backend includes authentication and role-based access controls.

- Students access permitted student-facing endpoints.
- Administrators can access administrative regulation and user-management operations.
- Student cohort access is checked against the cohort stored on the account.
- Account and privilege changes can invalidate existing tokens.

### 6. Regulation Change Radar

Administrators can compare two stored versions of the same regulation. The Change Radar aligns extracted passages, shows potential additions, removals and modifications with source-page references, and stores the result for later review. Machine-detected differences are always labelled **“Potential changes — review required.”** and are not academic conclusions.

The review status can be set to **Needs review** or **Approved**. Approval is audited and does not approve or publish the underlying PDF. Students and staff see an update only when the review is approved, the new regulation itself is approved, and its confirmed batch/programme applicability matches their authenticated account. These review records do not alter Q&A retrieval.

Applicability is explicitly confirmed by an administrator against the new regulation's recorded applicability; automatic impact inference and structured clause management are not implemented.

### 8. Administrator User Management and Audit Logging

Administrators can manage student and staff accounts through the API: provision accounts, update profiles and cohorts, reset passwords, deactivate and reactivate accounts, unlock accounts and revoke sessions. Administrator accounts themselves are created only through the secured command-line bootstrap script.

Security-relevant actions are recorded in an append-only audit log, which administrators can browse through a read-only endpoint. See [Administrator User Management](#administrator-user-management), [Audit Log](#audit-log) and [Administrator Account Recovery](#administrator-account-recovery).

---

## How It Works

```text
Academic Regulation Documents
            |
            v
   Document Ingestion
            |
            v
 Regulation Content Storage
            |
            v
 Verification and Approval
            |
            v
 Deterministic Cohort Applicability
            |
            v
 Evidence Retrieval
            |
            v
 AI-Assisted Answer Generation
            |
            v
 Answer with Supporting References
```

For a student question, the intended flow is:

1. Authenticate the user.
2. Identify the cohort stored on the user's account.
3. Determine the permitted regulation context.
4. Retrieve relevant approved evidence.
5. Generate an answer grounded in the retrieved evidence.
6. Return the answer with source references.

If sufficient evidence is not available, the system should avoid presenting an unsupported answer.

---

## Core Design Principle

### Rules decide. AI explains.

CohortIQ AI separates **rule applicability** from **AI-generated explanation**.

| Responsibility | Approach |
|---|---|
| Determine the applicable cohort | Deterministic application logic |
| Enforce user permissions | Backend authorization |
| Control student access to regulation evidence | Verification status and cohort checks |
| Retrieve supporting regulation content | Retrieval pipeline |
| Explain retrieved evidence | AI-assisted generation |
| Handle ambiguous or unverified rules | Administrative review |

AI may assist with extraction, summarization, and explanation. It must not independently decide which regulation applies to a student.

---

## System Architecture

```text
                  Student / Administrator
                            |
                            v
                     FastAPI Backend
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
       Authentication   Authorization   API Services
             |              |              |
             +--------------+--------------+
                            |
                            v
                Existing Regulation Workflow
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
       Regulation Data   Retrieval       AI Answering
             |              |              |
             +--------------+--------------+
                            |
                            v
                  Evidence-backed Response
```

The current FastAPI backend reuses the existing regulation workflow and database logic rather than duplicating business logic in the API layer.

### Planned Architecture Extensions

The following capabilities are planned and should not be considered implemented:

- Structured clause management
- Regulation version comparison
- Cohort impact analysis
- Approval and publication workflow enhancements
- Hybrid keyword and vector retrieval
- Reranking and advanced RAG strategies
- Next.js frontend
- PostgreSQL and pgvector integration

---

## Technology Stack

### Currently Used

| Area | Technology |
|---|---|
| Programming language | Python |
| Existing user interface | Streamlit |
| Backend API | FastAPI |
| Data validation | Pydantic |
| Current database | SQLite |
| Authentication | JWT |
| Password hashing | Argon2id |
| AI service | Gemini API |
| PDF processing | PyMuPDF |
| Retrieval | BM25-based retrieval |
| Testing | Pytest |

### Planned or Under Evaluation

| Area | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript |
| UI components | Tailwind CSS, shadcn/ui |
| Database | PostgreSQL |
| Vector search | pgvector |
| Hybrid retrieval | BM25, vector retrieval, Reciprocal Rank Fusion |
| Reranking | Cross-Encoder |
| Advanced RAG | Adaptive RAG |
| RAG evaluation | Ragas or DeepEval |
| Frontend deployment | Vercel |
| Backend deployment | Render |

The planned technologies are not yet part of the current implementation unless explicitly stated otherwise in the implementation status.

---

## Project Structure

```text
CohortIQ-AI/
├── app/
│   ├── main.py
│   ├── ui/
│   ├── workflow.py
│   ├── database.py
│   ├── pdf_processor.py
│   ├── chunking.py
│   ├── retrieval.py
│   ├── gemini_service.py
│   ├── citation_validator.py
│   └── models.py
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   └── permissions.py
│   │   ├── auth/
│   │   ├── audit/
│   │   ├── schemas/
│   │   └── services/
│   │
│   ├── scripts/
│   │   └── create_admin.py
│   │
│   └── tests/
│
├── tests/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

The repository structure may evolve as additional backend capabilities and the planned frontend are introduced.

---

## Current Implementation Status

| Component | Status |
|---|---|
| Existing Streamlit regulation Q&A application | Implemented |
| FastAPI backend foundation | Implemented |
| Regulation read and ingestion endpoints | Implemented |
| Regulation verification endpoint | Implemented |
| Query endpoint | Implemented |
| JWT authentication | Implemented |
| Argon2id password hashing | Implemented |
| Role-based API access control | Implemented |
| Student cohort authorization | Implemented |
| Route-permission inventory guard | Implemented |
| Append-only audit-event repository | Implemented |
| Audit logging across application flows | Implemented (see [audit limitations](#consistency-and-limitations)) |
| Administrator user-management APIs | Implemented |
| Audit-event listing API | Implemented |
| Regulation Change Radar comparison and review workflow | Implemented |
| Cohort-filtered approved change updates | Implemented |
| Administrator account recovery procedure | Planned |
| Automatic cohort impact inference | Planned |
| Structured clause management | Planned |
| Next.js frontend | Planned |
| PostgreSQL and pgvector migration | Planned |
| Hybrid retrieval and advanced RAG | Planned |
| Production deployment | Planned |

---

## Getting Started

### Prerequisites

- Python installed
- Git installed
- A Gemini API key for AI functionality
- PowerShell on Windows, or a compatible terminal

### 1. Clone the Repository

```bash
git clone https://github.com/YuvasriPraksh/COHORTIQ-AI.git
cd COHORTIQ-AI
```

### 2. Create a Virtual Environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a local `.env` file using `.env.example` as a reference.

Add the required configuration values, including the Gemini API key and authentication settings required by your local setup.

The FastAPI backend signs access tokens with `JWT_SECRET_KEY`. Generate a strong value and paste it as `JWT_SECRET_KEY=` in `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

- A configured secret must be at least 32 bytes, must not be repetitive (at least 8 distinct characters), and must not contain a placeholder value such as `changeme` or `your-secret`. Otherwise the API refuses to start, in every environment.
- With `APP_ENV=production`, the API also refuses to start if `JWT_SECRET_KEY` is missing or blank.
- In `development` or `test` the API starts without a secret, but sign-in returns `503`.

**Never commit `.env` files, API keys, passwords, or other secrets to GitHub.**

### 5. Run the Existing Streamlit Application

```powershell
streamlit run app/main.py
```

### 6. Run the FastAPI Backend

From the repository root:

```powershell
uvicorn backend.app.main:app --reload
```

The health endpoint is:

```text
/api/v1/health
```

During development, interactive API documentation is available at:

```text
/docs
```

API documentation may be disabled or restricted in production.

Starting the API creates any missing tables in the shared SQLite database (`DATABASE_PATH`, default `data/cohortiq.db`): the regulation tables, the backend-only `users` table, the append-only `audit_events` table, and Change Radar review records. Existing regulation data is preserved, and the Streamlit app does not use the backend-only tables.

Run commands from the repository root so the relative `DATABASE_PATH` resolves correctly. From another directory, it points to a different, empty database file.

### 7. Create the First Administrator

Administrators cannot be created through the API. Create the first one from an interactive terminal:

```powershell
python -m backend.scripts.create_admin --email admin@admin.smvec.ac.in --full-name "Registrar Office"
```

- The password is entered twice at a hidden prompt. It cannot be passed as a command-line argument, and the command refuses to run when input is piped.
- The address must use the configured `ADMINISTRATOR_EMAIL_DOMAIN` (default `admin.smvec.ac.in`).
- The password must meet the password policy, and is stored only as an Argon2id hash.
- If an account with the same email already exists (in any letter case or role), nothing is created or changed.
- The script creates any missing tables, including `audit_events`. The account and a `user.created` audit event (actor type `cli`) are written in one transaction: if either cannot be stored, no account is created. The audit event contains no email address, name or password.
- Use `--db-path PATH` to target a different SQLite file.

---

## API Overview

The backend currently exposes the following API operations.

| Method | Endpoint | Purpose | Access |
|---|---|---|---|
| `GET` | `/api/v1/health` | Health check | Public |
| `GET` | `/api/v1/regulations` | List regulations | Signed in |
| `GET` | `/api/v1/regulations/{regulation_id}` | Retrieve a regulation | Signed in |
| `GET` | `/api/v1/regulations/{regulation_id}/pages` | Retrieve regulation pages | Signed in |
| `GET` | `/api/v1/cohorts/{admission_batch}/{programme}/regulations` | Retrieve regulations for a cohort | Signed in (students: own cohort) |
| `POST` | `/api/v1/regulations/ingest` | Ingest a regulation | Administrator |
| `PATCH` | `/api/v1/regulations/{regulation_id}/verification` | Update verification status | Administrator |
| `GET` | `/api/v1/change-radar/reviews` | List saved comparisons | Administrator |
| `POST` | `/api/v1/change-radar/reviews` | Compare stored versions and save a review | Administrator |
| `GET` | `/api/v1/change-radar/reviews/{review_id}` | Retrieve a saved comparison | Administrator |
| `PATCH` | `/api/v1/change-radar/reviews/{review_id}` | Set review to Needs review or Approved | Administrator |
| `GET` | `/api/v1/updates` | List approved updates applicable to the authenticated cohort | Signed in (student/staff cohort only) |
| `POST` | `/api/v1/query/ask` | Ask a regulation question | Signed in (students: own cohort) |
| `POST` | `/api/v1/auth/login` | Authenticate | Public |
| `POST` | `/api/v1/auth/register` | Register a student account with a college email | Public |
| `GET` | `/api/v1/auth/me` | Retrieve the authenticated user's profile | Signed in |
| `GET` | `/api/v1/admin/users` | List accounts | Administrator |
| `POST` | `/api/v1/admin/users` | Create a student account | Administrator |
| `POST` | `/api/v1/admin/users/staff` | Provision a staff account | Administrator |
| `GET` | `/api/v1/admin/users/{user_id}` | Retrieve an account | Administrator |
| `PATCH` | `/api/v1/admin/users/{user_id}` | Update an account's name or cohort | Administrator |
| `PATCH` | `/api/v1/admin/users/{user_id}/role` | Demote an administrator to student | Administrator |
| `POST` | `/api/v1/admin/users/{user_id}/password` | Reset a student's password | Administrator |
| `POST` | `/api/v1/admin/users/{user_id}/deactivate` | Deactivate an account | Administrator |
| `POST` | `/api/v1/admin/users/{user_id}/reactivate` | Reactivate an account | Administrator |
| `POST` | `/api/v1/admin/users/{user_id}/unlock` | Clear a sign-in lockout | Administrator |
| `POST` | `/api/v1/admin/users/{user_id}/revoke-sessions` | Revoke an account's tokens | Administrator |
| `GET` | `/api/v1/admin/audit-events` | List audit events (read-only) | Administrator |

Consult the generated OpenAPI documentation for request and response schemas.

### Access Control

- Every route is classified in `backend/app/api/permissions.py`. A test fails if a route is added without a classification, or with dependencies that do not match it.
- Roles and cohorts are always read from the `users` table, never from the token or the request.
- Missing, invalid, expired or revoked tokens and inactive accounts get `401`. Students calling an administrator route get `403`.
- Students and staff see only approved regulations applicable to the admission batch and programme stored on their account, including when reading a regulation directly by ID. On the cohort route and `POST /api/v1/query/ask`, both may use only their stored cohort (`403` otherwise). Administrators may use any cohort.
- `POST /api/v1/auth/register` lets students create their own account using `STUDENT_EMAIL_DOMAIN` (default `student.smvec.ac.in`). It applies the password policy, requires `admission_batch` and `programme`, always creates a **student** (there is no role field), returns `201` with the profile (no token; sign in afterwards) and `409` for an existing email. A `user.created` audit event (actor type `anonymous`) is written in the same transaction.
- Staff accounts use `STAFF_EMAIL_DOMAIN` (default `staff.smvec.ac.in`) and can only be created by an authenticated administrator through `POST /api/v1/admin/users/staff`; they are assigned a cohort and never get public sign-up. Administrator accounts use `ADMINISTRATOR_EMAIL_DOMAIN` (default `admin.smvec.ac.in`) and can only be bootstrapped through the interactive CLI. The login API verifies the selected role and permitted email domain against the stored account.
- **There is no email verification**, so an allowed domain alone does not prove that the person owns the address; configure institutional mailbox verification before production.
- `POST /api/v1/auth/login` returns the same `401` for unknown emails, wrong passwords, inactive accounts and locked accounts. After `LOGIN_MAX_FAILED_ATTEMPTS` (default 5) consecutive failures, the account is locked for `LOGIN_LOCKOUT_MINUTES` (default 15). Sign-in returns `503` when `JWT_SECRET_KEY` is not set, or when its audit event cannot be written.

### Administrator User Management

All `/api/v1/admin/users` routes require an administrator, return `Cache-Control: no-store`, and never return password hashes, token versions, failed sign-in counters or lock expiry.

- **Responses:** account responses contain `id`, `email`, `role`, `full_name`, `admission_batch`, `programme`, `is_active`, `is_locked`, `last_login_at`, `created_at` and `updated_at`.
- **Validation:** unknown request fields and query parameters are rejected with `422`.
- **Listing:** `GET /api/v1/admin/users` orders accounts by id.
  - Exact-match filters: `role`, `is_active`, `admission_batch`, `programme`.
  - `limit` is 1–100 (default 50); `offset` is 0–1,000,000.
  - The response contains `users`, `total`, `limit` and `offset`.
- **Creating students:** the body takes `email`, `password`, `admission_batch`, `programme` and an optional `full_name`, and returns `201`.
  - There is no role field.
  - The address must end in the configured student domain.
  - The password must meet the password policy.
  - A duplicate email gets `409`.
- **Provisioning staff:** `POST /api/v1/admin/users/staff` accepts the same profile fields, requires the configured staff domain, and assigns the staff role server-side.
- **Profile changes:** `PATCH /api/v1/admin/users/{user_id}` changes `full_name`, `admission_batch` and/or `programme`.
  - At least one field is required, and `null` clears a value.
  - Students and staff must keep a cohort.
- **Role changes:** `PATCH .../role` with `{"role": "student"}` demotes an administrator. Granting `administrator` is always refused (`403`); the API cannot create or promote administrators.
- **Password reset:** `POST .../password` with `{"new_password": "..."}` sets a student's or staff member's password. It is refused (`403`) for your own account and for any administrator account.
- **Self and last-administrator protection:** administrators cannot change their own role or active status (`403`). The last active administrator cannot be demoted or deactivated (`409`).
- **Token revocation:** demotion, deactivation, password reset and `revoke-sessions` revoke the account's existing tokens. Reactivation does not restore them; the user must sign in again. `unlock` clears the failed sign-in counter and any temporary lock.
- **Transactions:** each change runs in one transaction that re-checks the acting administrator and writes the audit event.
  - Requests that would change nothing write nothing.
  - A concurrent change to the same account can return `409` ("please retry").
  - Unknown accounts get `404`.
- **Not implemented:** self-service password change and forced password change at first sign-in.

### Audit-Event Listing

`GET /api/v1/admin/audit-events` is administrator-only and read-only.

- **Filters:** `action`, `outcome`, `actor_user_id`, `target_type` (`user` or `regulation`), `target_id` (requires `target_type`), `occurred_after` and `occurred_before`.
  - The time bounds are inclusive and must include a timezone offset, for example `2026-01-01T00:00:00Z`.
  - Unknown actions or parameters get `422`.
- **Order and pages:** newest first; events with the same timestamp are ordered by id, highest first. `limit` is 1–100 (default 50); `offset` is 0–1,000,000.
- **Response:** `events`, `total`, `limit` and `offset`. Each event has `id`, `occurred_at`, `action`, `outcome`, `actor_type`, `actor_user_id`, `actor_role`, `target_type`, `target_id` and `details`.
- **Withheld details:** `details` contains only allowlisted keys. The failed sign-in counter (`failed_login_count`) and lock expiry (`locked_until`) recorded for sign-in events are never returned.
- **Reads are not audited.** A student's refused request is still recorded as `authorization.denied`.

---

## Security

Security is implemented in the FastAPI backend and includes:

- JWT-based authentication (HS256); the API refuses to start with a weak `JWT_SECRET_KEY`, or without one in production (see [Configure Environment Variables](#4-configure-environment-variables))
- Argon2id password hashing
- Role-based endpoint authorization
- Student cohort checks against account-stored values
- Token invalidation after relevant account or privilege changes
- Restricted administrator operations; administrators are created only with the command-line script
- Append-only audit logging of security-relevant actions
- Input validation and request limits
- Tests for unauthorized access and privilege-escalation attempts

Additional production hardening is still required before deployment.

The existing Streamlit application is intended for local/internal use and is not covered by the FastAPI authentication layer.

### Audit Log

The `audit_events` table records security-relevant actions.

- **Append-only:** SQLite triggers abort any update, delete or replacing insert. Anyone with direct write access to the database file can still alter it.
- **Retention:** events are kept indefinitely; there is no automatic retention or deletion.
- **Content limits:** events never contain passwords, password hashes, tokens, email addresses, client IP addresses, question text or document content. Full names are never recorded.
- **Allowlist:** every action and detail key comes from a fixed allowlist in `backend/app/audit/repository.py`.

**What is recorded:**

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

**Not recorded:**

- anonymous or `401` requests, and sign-ins with unknown emails;
- requests that fail validation before any change is attempted (`422`), and unknown targets (`404`);
- uploads rejected before processing (file type, metadata format, size or page count);
- verification requests for missing regulations or invalid statuses;
- failed CLI attempts;
- a sign-in refused because the password changed during that sign-in;
- reading the audit log.

#### Consistency and Limitations

- **Same transaction:** sign-in events, user-management changes and refusals, and the CLI bootstrap. If the audit event cannot be written, the change is rolled back: sign-in returns `503`, user management returns `500`, and the CLI creates no account.
- **Not atomic: ingestion and verification.** The shared workflow code in `app/` manages its own database connections, so the event is written after the change. If that write fails, the API undoes the change and returns `500`:
  - ingestion deletes the new pending regulation;
  - verification restores the previous status, unless the status changed again in the meantime or could not be read.

  A crash between the change and the audit write, or a failed undo (logged at CRITICAL), can still leave an unaudited change.
- **Best effort: authorization refusals.** The `403` is always returned; if its audit event cannot be written, the failure is logged at ERROR.

### Administrator Account Recovery

There is **no dedicated recovery command**. These are the verified options:

- **Locked out:** the lock expires after `LOGIN_LOCKOUT_MINUTES`, or another administrator can call `unlock`.
- **Deactivated:** another administrator can call `reactivate`.
- **Lost or exposed token:** another administrator can call `revoke-sessions`.
- **Forgotten password:** the API cannot reset any administrator's password.
  - Someone with shell access to the server and database can run the first-administrator script with a **different** email to create a new administrator. This works even if no usable administrator remains.
  - The new administrator can then deactivate or demote the old account.
  - The old email cannot be reused: the script refuses existing emails and accounts are never deleted. A demoted account cannot be promoted again through the API.

A secure recovery procedure for administrator accounts (for example, resetting an administrator's password from the command line) is not implemented. It should be documented or addressed before production.

---

## Testing

Run the test suite from the repository root:

```powershell
python -m pytest backend/tests tests
```

Tests use temporary databases. Run them from the repository root so that any relative database path resolves to the intended location.

The project is actively developed. Test counts and coverage may change as new functionality is added.

---

## Roadmap

- [x] FastAPI backend foundation
- [x] Regulation API endpoints
- [x] Authentication and secure password handling
- [x] Role-based API access control
- [x] Cohort authorization
- [x] Append-only audit-event repository
- [x] Administrator user-management APIs
- [x] Audit logging integration across application flows
- [x] Audit-event listing API
- [ ] Secure administrator account recovery procedure
- [ ] Regulation version comparison
- [ ] Cohort impact analysis
- [ ] Structured clause management and approval workflow
- [ ] Next.js frontend
- [ ] PostgreSQL and pgvector integration
- [ ] Hybrid retrieval and reranking
- [ ] Advanced RAG evaluation
- [ ] Deployment and production hardening

---

## Limitations

- The current database is SQLite; PostgreSQL and pgvector are planned.
- The existing application does not yet provide every planned regulation-management capability.
- The Streamlit application is not protected by the FastAPI authentication layer.
- Audit events for regulation ingestion and verification are not written atomically with the change (see [Consistency and Limitations](#consistency-and-limitations)).
- There is no dedicated administrator account recovery command, and no self-service password change.
- Advanced hybrid retrieval, reranking, and Adaptive RAG are planned or under evaluation.
- The platform is under active development and is not yet presented as a production-ready academic authority.

---

## Contributing

Contributions, suggestions, and issue reports are welcome.

Before making substantial changes:

1. Check the current implementation and roadmap.
2. Keep implemented and planned features clearly distinguished.
3. Add or update tests for behavior changes.
4. Avoid committing secrets or local environment files.
5. Run the relevant tests before submitting changes.

---

## Project Information

**Project:** CohortIQ AI  
**Full Name:** Intelligent Academic Regulation & Cohort Impact Navigator  
**Tagline:** Every Rule. Every Cohort. The Right Answer.  
**Core Principle:** Rules decide. AI explains.

**Repository:** [COHORTIQ-AI](https://github.com/YuvasriPraksh/COHORTIQ-AI)

---

*CohortIQ AI is being developed to make academic regulation information more accessible, cohort-aware, and verifiable through explicit rules and evidence-grounded AI assistance.*
