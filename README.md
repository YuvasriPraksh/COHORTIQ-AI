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
