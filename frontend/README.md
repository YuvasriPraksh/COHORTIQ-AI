# CohortIQ frontend

Student-facing web interface for the CohortIQ AI API: sign in, ask a question
about the regulations for your cohort, and see the answer with its evidence and
how the Adaptive RAG router handled it.

Built with Vite, React and TypeScript. It uses only existing API endpoints:

| Endpoint | Used for |
|---|---|
| `POST /api/v1/auth/login` | Sign in |
| `GET /api/v1/auth/me` | The signed-in account and its cohort |
| `POST /api/v1/query/ask` | Questions, answers, citations, sources searched and the route |

## Running locally

Start the API from the repository root (see the main README), then:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. In development, requests to `/api` are proxied to
`http://127.0.0.1:8000`; set `VITE_API_PROXY_TARGET` to use another address.
For a separately hosted API, build with `VITE_API_BASE_URL` set to its origin
(the API's `BACKEND_CORS_ORIGINS` must allow the frontend's origin).

## Checks

```powershell
npm run typecheck   # TypeScript
npm test            # Vitest + Testing Library
npm run build       # type-check and production build into dist/
```

## Notes

- The access token is kept in `sessionStorage` for the current tab and cleared
  on sign-out, on expiry, and whenever the API answers 401.
- Students always ask with the cohort stored on their account. Administrators
  can preview any cohort, as the API allows; there are no admin screens here.
- There is no conversation history or document search: the API does not
  provide them.
