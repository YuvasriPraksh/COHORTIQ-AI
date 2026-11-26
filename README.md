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
- Administrators can access administrative regulation operations.
- Student cohort access is checked against the cohort stored on the account.
- Account and privilege changes can invalidate existing tokens.

### 6. Regulation Version Comparison — Planned

A planned capability will compare regulation versions and identify changes in clauses, requirements, or academic rules.

### 7. Cohort Impact Analysis — Planned

A planned capability will help administrators identify which admission batches or programmes may be affected by a regulation change.

### 8. Administrator User Management and Audit Logging — In Progress

The append-only audit-event repository has been implemented and tested. Integration with application workflows and administrator management APIs is part of the ongoing development work.

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
│   │   └── services/
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
| Append-only audit-event repository | Implemented; integration in progress |
| Administrator user-management APIs | Planned / in progress |
| Regulation version comparison | Planned |
| Cohort impact analysis | Planned |
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

---

## API Overview

The backend currently exposes the following API operations.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/regulations` | List regulations |
| `GET` | `/api/v1/regulations/{regulation_id}` | Retrieve a regulation |
| `GET` | `/api/v1/regulations/{regulation_id}/pages` | Retrieve regulation pages |
| `GET` | `/api/v1/cohorts/{admission_batch}/{programme}/regulations` | Retrieve regulations for a cohort |
| `POST` | `/api/v1/regulations/ingest` | Ingest a regulation |
| `PATCH` | `/api/v1/regulations/{regulation_id}/verification` | Update verification status |
| `POST` | `/api/v1/query/ask` | Ask a regulation question |
| `POST` | `/api/v1/auth/login` | Authenticate |
| `GET` | `/api/v1/auth/me` | Retrieve the authenticated user's profile |

Authentication and authorization requirements depend on the endpoint. Consult the generated OpenAPI documentation for request and response schemas.

---

## Security

Security is implemented in the FastAPI backend and includes:

- JWT-based authentication
- Argon2id password hashing
- Role-based endpoint authorization
- Student cohort checks against account-stored values
- Token invalidation after relevant account or privilege changes
- Restricted administrator operations
- Input validation and request limits
- Tests for unauthorized access and privilege-escalation attempts

Additional production hardening is still required before deployment.

The existing Streamlit application is intended for local/internal use and is not covered by the FastAPI authentication layer.

---

## Testing

Run the test suite from the repository root:

```powershell
python -m pytest backend/tests tests
```

The project is actively developed. Test counts and coverage may change as new functionality is added.

---

## Roadmap

- [x] FastAPI backend foundation
- [x] Regulation API endpoints
- [x] Authentication and secure password handling
- [x] Role-based API access control
- [x] Cohort authorization
- [x] Append-only audit-event repository
- [ ] Administrator user-management APIs
- [ ] Audit logging integration across application flows
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
