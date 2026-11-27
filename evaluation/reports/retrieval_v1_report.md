# CohortIQ retrieval and end-to-end evaluation

Generated 2026-11-27 10:29 UTC. Dataset `cohortiq-retrieval-v1`.

## Setup

- **Cases:** 20 (17 answerable, 3 expecting abstention).
- **About the dataset:** Retrieval evaluation set for the two approved regulations in the project database: 'SMVEC' version 2023 (admission batches 2024 and 2025, programme 'B-tech - CSE') and 'regulation 2' version 2024 (admission batches 2022 and 2023, programme 'b tech aids'). Most questions are asked once for each cohort, so the expected regulation differs only by cohort. Expected pages were judged by hand from the extracted page text: a page is relevant if it states the information needed to answer. Reference answers are paraphrased from those pages and are not scored in this version. Data note: the document stored as 'regulation 2' version 2024 is headed 'Academic Regulations 2020 (R-2020)' in its own text; cases use the stored metadata.
- **Categories:** abstention (3), attendance (2), break_of_study (2), classification (2), discipline (2), duration (2), grading (2), honours (1), passing (2), revaluation (2).
- **Retrieval:** top 5 chunks, recursive chunking, size 1000, overlap 200 (the API defaults).
- **Router:** minimum best retrieval score 3; clause lookups use top 3.
- **Regulations in the database:**
  - SMVEC version 2023: batches 2024, 2025; programmes B-tech - CSE; approved.
  - regulation 2 version 2024: batches 2022, 2023; programmes b tech aids; approved.
- **Method:** every case runs on a temporary copy of the database with answer generation replaced by a stand-in, so no model or external service is called.

## Two paths are evaluated

1. **Retrieval-only workflow:** `app.workflow.answer_student_question`, which the Streamlit app uses. It has no router. This is the original baseline, kept unchanged.
2. **End-to-end with the Adaptive RAG router:** `query_service.answer_with_adaptive_routing`, which `POST /api/v1/query/ask` uses. Questions can be refused, clarified or abstained on before generation.

### Which metrics apply to which path

| Metric | Retrieval-only workflow | End-to-end with the router |
|---|---|---|
| Precision@K, Recall@K, MRR | The workflow's top-K retrieved chunks. | The evidence passed to the answer generator (top 3 for clause lookups). When the router abstains on an answerable case, the case scores 0. |
| Wrong-version rate and chunks | Chunks from another regulation or version in the top K. | Same, on the evidence passed to the generator (empty when the router abstains). |
| Abstention | Retrieval returned no evidence, so the model would not be called. | The answer generator was not called: any route other than `clause_lookup` or `general`. |
| Routing outcome | Not applicable (no router). | The validated route and reason returned with every answer. |

A retrieved chunk is **relevant** when it comes from the expected regulation (document name and version) and one of the expected pages. Retrieval metrics average over answerable cases only.

- **Precision@5:** relevant chunks among the top 5, divided by 5.
- **Recall@5:** share of the expected pages that appear in the top 5.
- **MRR:** mean of 1 / rank of the first relevant chunk (0 when none is in the top 5).
- **Wrong-version rate:** share of answerable cases with at least one top-5 chunk from a different regulation or version.
- **Wrong-version chunks:** share of returned top-5 chunks from a different regulation or version.
- **Abstention accuracy:** share of all cases where the path abstained exactly when it should.

## A. Retrieval-only workflow (baseline)

| Configuration | Precision@5 | Recall@5 | MRR | Wrong-version rate | Wrong-version chunks | Abstention accuracy |
|---|---|---|---|---|---|---|
| Retrieval-only workflow, cohort-filtered (no router) | 0.412 | 0.926 | 0.828 | 0.0% | 0.0% | 95.0% |
| Retrieval-only baseline: no cohort filter (all approved regulations) | 0.306 | 0.745 | 0.608 | 94.1% | 47.1% | 85.0% |

Abstention detail:

- Retrieval-only workflow, cohort-filtered (no router): 2 of 3 expected abstentions made; 0 answerable case(s) wrongly abstained.
- Retrieval-only baseline: no cohort filter (all approved regulations): 0 of 3 expected abstentions made; 0 answerable case(s) wrongly abstained.

## B. End-to-end with the Adaptive RAG router

| Configuration | Precision@5 | Recall@5 | MRR | Wrong-version rate | Wrong-version chunks | Abstention accuracy |
|---|---|---|---|---|---|---|
| End-to-end with the Adaptive RAG router (API path) | 0.412 | 0.926 | 0.828 | 0.0% | 0.0% | 100.0% |

Abstention detail:

- End-to-end with the Adaptive RAG router (API path): 3 of 3 expected abstentions made; 0 answerable case(s) wrongly abstained.

Routing outcomes (route / reason → cases):

- general/evidence_found: 17
- low_evidence/no_applicable_regulations: 2
- out_of_scope/no_regulation_terms: 1

## Limitations

- Answer faithfulness and answer relevancy are **not evaluated**: no answers are generated.
- Citation validity is **not evaluated**: it needs generated answers with citations, and this run calls no model.
- Reference answers are stored in the dataset for later answer-quality evaluation but are **not scored**.
- The dataset is small (about 20 cases) and was labelled by one person by reading the extracted page text, so results indicate behaviour but are not statistically strong.
- Relevance is judged per page, not per clause or chunk. A chunk from a relevant page counts as relevant even if it holds only part of the answer.
- The two regulations have near-identical wording for many rules, which makes wrong-version retrieval a realistic risk but also means a 'wrong-version' chunk may still state the same rule.
- Retrieval-only abstention happens only when retrieval returns no evidence. BM25 always returns its top results when the cohort has any regulation (there is no score threshold on that path), so out-of-scope questions cannot abstain there.
- End-to-end abstention is measured on this dataset's three abstention cases only; routing accuracy across all routes is measured separately on the routing dataset (see `evaluation/reports/routing_v1_report.md`).
- Only the current retrieval method is measured (BM25 with recursive chunking). There is no vector, hybrid or reranked retrieval to compare yet.
- The project database and PDFs are not in the repository, so these results can only be reproduced with the same database. Tests use a separate synthetic database.
- Every evaluated cohort has exactly one applicable regulation, so in the cohort-filtered and router paths a wrong-version chunk can only come from an applicability error, not from ranking. The no-cohort-filter baseline shows the ranking risk the filter removes.

## Per-case results

### Retrieval-only workflow, cohort-filtered (no router)

| Case | Cohort | Expected | First relevant rank | P@5 | R@5 | Wrong version | Abstained | Retrieved (rank order) |
|---|---|---|---|---|---|---|---|---|
| attendance-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 21, 22 | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.21; SMVEC 2023 p.14; SMVEC 2023 p.23; SMVEC 2023 p.22; SMVEC 2023 p.14 |
| attendance-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 13 | 2 | 0.400 | 1.000 | no | no | regulation 2 2024 p.19; regulation 2 2024 p.13; regulation 2 2024 p.13; regulation 2 2024 p.14; regulation 2 2024 p.12 |
| passing-theory-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 23 | 4 | 0.200 | 1.000 | no | no | SMVEC 2023 p.21; SMVEC 2023 p.21; SMVEC 2023 p.24; SMVEC 2023 p.23; SMVEC 2023 p.11 |
| passing-theory-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 19 | - | 0.000 | 0.000 | no | no | regulation 2 2024 p.18; regulation 2 2024 p.8; regulation 2 2024 p.8; regulation 2 2024 p.16; regulation 2 2024 p.20 |
| distinction-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 25 | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.25; SMVEC 2023 p.25; SMVEC 2023 p.26; SMVEC 2023 p.22; SMVEC 2023 p.34 |
| distinction-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 21 | 1 | 0.600 | 1.000 | no | no | regulation 2 2024 p.21; regulation 2 2024 p.21; regulation 2 2024 p.21; regulation 2 2024 p.14; regulation 2 2024 p.30 |
| max-duration-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 8, 25, 26, 27 | 1 | 0.800 | 0.750 | no | no | SMVEC 2023 p.8; SMVEC 2023 p.8; SMVEC 2023 p.27; SMVEC 2023 p.13; SMVEC 2023 p.25 |
| max-duration-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 9, 21, 22 | 1 | 0.800 | 1.000 | no | no | regulation 2 2024 p.9; regulation 2 2024 p.22; regulation 2 2024 p.21; regulation 2 2024 p.9; regulation 2 2024 p.11 |
| revaluation-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 24 | 1 | 0.200 | 1.000 | no | no | SMVEC 2023 p.24; SMVEC 2023 p.22; SMVEC 2023 p.22; SMVEC 2023 p.25; SMVEC 2023 p.25 |
| revaluation-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 19 | 1 | 0.600 | 1.000 | no | no | regulation 2 2024 p.19; regulation 2 2024 p.19; regulation 2 2024 p.14; regulation 2 2024 p.19; regulation 2 2024 p.21 |
| grades-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 24 | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.24; SMVEC 2023 p.21; SMVEC 2023 p.21; SMVEC 2023 p.24; SMVEC 2023 p.6 |
| grades-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 20 | 1 | 0.200 | 1.000 | no | no | regulation 2 2024 p.20; regulation 2 2024 p.19; regulation 2 2024 p.3; regulation 2 2024 p.6; regulation 2 2024 p.3 |
| break-of-study-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 26 | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.26; SMVEC 2023 p.26; SMVEC 2023 p.22; SMVEC 2023 p.22; SMVEC 2023 p.14 |
| break-of-study-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 22 | 3 | 0.200 | 1.000 | no | no | regulation 2 2024 p.3; regulation 2 2024 p.13; regulation 2 2024 p.22; regulation 2 2024 p.6; regulation 2 2024 p.14 |
| malpractice-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 28 | 1 | 0.200 | 1.000 | no | no | SMVEC 2023 p.28; SMVEC 2023 p.27; SMVEC 2023 p.14; SMVEC 2023 p.23; SMVEC 2023 p.27 |
| malpractice-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 23 | 1 | 0.400 | 1.000 | no | no | regulation 2 2024 p.23; regulation 2 2024 p.23; regulation 2 2024 p.12; regulation 2 2024 p.14; regulation 2 2024 p.6 |
| honours-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 13, 26 | 1 | 0.800 | 1.000 | no | no | SMVEC 2023 p.13; SMVEC 2023 p.13; SMVEC 2023 p.26; SMVEC 2023 p.13; SMVEC 2023 p.25 |
| abstain-no-regulation-batch | 2019 / B-tech - CSE | abstain | - | n/a | n/a | n/a | yes | none |
| abstain-programme-mismatch | 2024 / b tech aids | abstain | - | n/a | n/a | n/a | yes | none |
| abstain-out-of-scope | 2024 / B-tech - CSE | abstain | - | n/a | n/a | n/a | no (wrong) | SMVEC 2023 p.31; SMVEC 2023 p.22; SMVEC 2023 p.25; SMVEC 2023 p.26; SMVEC 2023 p.14 |

### Retrieval-only baseline: no cohort filter (all approved regulations)

| Case | Cohort | Expected | First relevant rank | P@5 | R@5 | Wrong version | Abstained | Retrieved (rank order) |
|---|---|---|---|---|---|---|---|---|
| attendance-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 21, 22 | 1 | 0.200 | 0.500 | yes | no | SMVEC 2023 p.21; regulation 2 2024 p.19; regulation 2 2024 p.13; SMVEC 2023 p.14; SMVEC 2023 p.23 |
| attendance-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 13 | 3 | 0.200 | 1.000 | yes | no | SMVEC 2023 p.21; regulation 2 2024 p.19; regulation 2 2024 p.13; SMVEC 2023 p.14; SMVEC 2023 p.23 |
| passing-theory-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 23 | - | 0.000 | 0.000 | yes | no | SMVEC 2023 p.21; SMVEC 2023 p.21; regulation 2 2024 p.18; regulation 2 2024 p.8; regulation 2 2024 p.8 |
| passing-theory-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 19 | - | 0.000 | 0.000 | yes | no | SMVEC 2023 p.21; SMVEC 2023 p.21; regulation 2 2024 p.18; regulation 2 2024 p.8; regulation 2 2024 p.8 |
| distinction-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 25 | 2 | 0.400 | 1.000 | yes | no | regulation 2 2024 p.21; SMVEC 2023 p.25; regulation 2 2024 p.21; SMVEC 2023 p.25; regulation 2 2024 p.21 |
| distinction-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 21 | 1 | 0.600 | 1.000 | yes | no | regulation 2 2024 p.21; SMVEC 2023 p.25; regulation 2 2024 p.21; SMVEC 2023 p.25; regulation 2 2024 p.21 |
| max-duration-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 8, 25, 26, 27 | 2 | 0.600 | 0.500 | yes | no | regulation 2 2024 p.9; SMVEC 2023 p.8; SMVEC 2023 p.8; SMVEC 2023 p.27; regulation 2 2024 p.22 |
| max-duration-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 9, 21, 22 | 1 | 0.400 | 0.667 | yes | no | regulation 2 2024 p.9; SMVEC 2023 p.8; SMVEC 2023 p.8; SMVEC 2023 p.27; regulation 2 2024 p.22 |
| revaluation-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 24 | 1 | 0.200 | 1.000 | yes | no | SMVEC 2023 p.24; regulation 2 2024 p.19; SMVEC 2023 p.22; regulation 2 2024 p.19; SMVEC 2023 p.22 |
| revaluation-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 19 | 2 | 0.400 | 1.000 | yes | no | SMVEC 2023 p.24; regulation 2 2024 p.19; SMVEC 2023 p.22; regulation 2 2024 p.19; SMVEC 2023 p.22 |
| grades-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 24 | 1 | 0.200 | 1.000 | yes | no | SMVEC 2023 p.24; regulation 2 2024 p.20; regulation 2 2024 p.19; SMVEC 2023 p.21; SMVEC 2023 p.21 |
| grades-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 20 | 2 | 0.200 | 1.000 | yes | no | SMVEC 2023 p.24; regulation 2 2024 p.20; regulation 2 2024 p.19; SMVEC 2023 p.21; SMVEC 2023 p.21 |
| break-of-study-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 26 | 2 | 0.400 | 1.000 | yes | no | regulation 2 2024 p.3; SMVEC 2023 p.26; SMVEC 2023 p.26; regulation 2 2024 p.13; SMVEC 2023 p.14 |
| break-of-study-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 22 | - | 0.000 | 0.000 | yes | no | regulation 2 2024 p.3; SMVEC 2023 p.26; SMVEC 2023 p.26; regulation 2 2024 p.13; SMVEC 2023 p.14 |
| malpractice-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 28 | 2 | 0.200 | 1.000 | yes | no | regulation 2 2024 p.23; SMVEC 2023 p.28; SMVEC 2023 p.27; regulation 2 2024 p.23; regulation 2 2024 p.12 |
| malpractice-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 23 | 1 | 0.400 | 1.000 | yes | no | regulation 2 2024 p.23; SMVEC 2023 p.28; SMVEC 2023 p.27; regulation 2 2024 p.23; regulation 2 2024 p.12 |
| honours-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 13, 26 | 1 | 0.800 | 1.000 | no | no | SMVEC 2023 p.13; SMVEC 2023 p.13; SMVEC 2023 p.26; SMVEC 2023 p.13; SMVEC 2023 p.25 |
| abstain-no-regulation-batch | 2019 / B-tech - CSE | abstain | - | n/a | n/a | n/a | no (wrong) | SMVEC 2023 p.21; regulation 2 2024 p.19; regulation 2 2024 p.13; SMVEC 2023 p.14; SMVEC 2023 p.23 |
| abstain-programme-mismatch | 2024 / b tech aids | abstain | - | n/a | n/a | n/a | no (wrong) | SMVEC 2023 p.21; SMVEC 2023 p.21; regulation 2 2024 p.18; regulation 2 2024 p.8; regulation 2 2024 p.8 |
| abstain-out-of-scope | 2024 / B-tech - CSE | abstain | - | n/a | n/a | n/a | no (wrong) | SMVEC 2023 p.31; regulation 2 2024 p.27; regulation 2 2024 p.21; regulation 2 2024 p.21; SMVEC 2023 p.22 |

### End-to-end with the Adaptive RAG router (API path)

| Case | Cohort | Expected | Route (reason) | First relevant rank | P@5 | R@5 | Wrong version | Abstained | Retrieved (rank order) |
|---|---|---|---|---|---|---|---|---|---|
| attendance-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 21, 22 | general (evidence_found) | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.21; SMVEC 2023 p.14; SMVEC 2023 p.23; SMVEC 2023 p.22; SMVEC 2023 p.14 |
| attendance-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 13 | general (evidence_found) | 2 | 0.400 | 1.000 | no | no | regulation 2 2024 p.19; regulation 2 2024 p.13; regulation 2 2024 p.13; regulation 2 2024 p.14; regulation 2 2024 p.12 |
| passing-theory-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 23 | general (evidence_found) | 4 | 0.200 | 1.000 | no | no | SMVEC 2023 p.21; SMVEC 2023 p.21; SMVEC 2023 p.24; SMVEC 2023 p.23; SMVEC 2023 p.11 |
| passing-theory-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 19 | general (evidence_found) | - | 0.000 | 0.000 | no | no | regulation 2 2024 p.18; regulation 2 2024 p.8; regulation 2 2024 p.8; regulation 2 2024 p.16; regulation 2 2024 p.20 |
| distinction-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 25 | general (evidence_found) | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.25; SMVEC 2023 p.25; SMVEC 2023 p.26; SMVEC 2023 p.22; SMVEC 2023 p.34 |
| distinction-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 21 | general (evidence_found) | 1 | 0.600 | 1.000 | no | no | regulation 2 2024 p.21; regulation 2 2024 p.21; regulation 2 2024 p.21; regulation 2 2024 p.14; regulation 2 2024 p.30 |
| max-duration-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 8, 25, 26, 27 | general (evidence_found) | 1 | 0.800 | 0.750 | no | no | SMVEC 2023 p.8; SMVEC 2023 p.8; SMVEC 2023 p.27; SMVEC 2023 p.13; SMVEC 2023 p.25 |
| max-duration-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 9, 21, 22 | general (evidence_found) | 1 | 0.800 | 1.000 | no | no | regulation 2 2024 p.9; regulation 2 2024 p.22; regulation 2 2024 p.21; regulation 2 2024 p.9; regulation 2 2024 p.11 |
| revaluation-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 24 | general (evidence_found) | 1 | 0.200 | 1.000 | no | no | SMVEC 2023 p.24; SMVEC 2023 p.22; SMVEC 2023 p.22; SMVEC 2023 p.25; SMVEC 2023 p.25 |
| revaluation-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 19 | general (evidence_found) | 1 | 0.600 | 1.000 | no | no | regulation 2 2024 p.19; regulation 2 2024 p.19; regulation 2 2024 p.14; regulation 2 2024 p.19; regulation 2 2024 p.21 |
| grades-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 24 | general (evidence_found) | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.24; SMVEC 2023 p.21; SMVEC 2023 p.21; SMVEC 2023 p.24; SMVEC 2023 p.6 |
| grades-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 20 | general (evidence_found) | 1 | 0.200 | 1.000 | no | no | regulation 2 2024 p.20; regulation 2 2024 p.19; regulation 2 2024 p.3; regulation 2 2024 p.6; regulation 2 2024 p.3 |
| break-of-study-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 26 | general (evidence_found) | 1 | 0.400 | 1.000 | no | no | SMVEC 2023 p.26; SMVEC 2023 p.26; SMVEC 2023 p.22; SMVEC 2023 p.22; SMVEC 2023 p.14 |
| break-of-study-reg2-2024 | 2022 / b tech aids | regulation 2 2024 p. 22 | general (evidence_found) | 3 | 0.200 | 1.000 | no | no | regulation 2 2024 p.3; regulation 2 2024 p.13; regulation 2 2024 p.22; regulation 2 2024 p.6; regulation 2 2024 p.14 |
| malpractice-smvec-2023 | 2025 / B-tech - CSE | SMVEC 2023 p. 28 | general (evidence_found) | 1 | 0.200 | 1.000 | no | no | SMVEC 2023 p.28; SMVEC 2023 p.27; SMVEC 2023 p.14; SMVEC 2023 p.23; SMVEC 2023 p.27 |
| malpractice-reg2-2024 | 2023 / b tech aids | regulation 2 2024 p. 23 | general (evidence_found) | 1 | 0.400 | 1.000 | no | no | regulation 2 2024 p.23; regulation 2 2024 p.23; regulation 2 2024 p.12; regulation 2 2024 p.14; regulation 2 2024 p.6 |
| honours-smvec-2023 | 2024 / B-tech - CSE | SMVEC 2023 p. 13, 26 | general (evidence_found) | 1 | 0.800 | 1.000 | no | no | SMVEC 2023 p.13; SMVEC 2023 p.13; SMVEC 2023 p.26; SMVEC 2023 p.13; SMVEC 2023 p.25 |
| abstain-no-regulation-batch | 2019 / B-tech - CSE | abstain | low_evidence (no_applicable_regulations) | - | n/a | n/a | n/a | yes | none |
| abstain-programme-mismatch | 2024 / b tech aids | abstain | low_evidence (no_applicable_regulations) | - | n/a | n/a | n/a | yes | none |
| abstain-out-of-scope | 2024 / B-tech - CSE | abstain | out_of_scope (no_regulation_terms) | - | n/a | n/a | n/a | yes | none |

