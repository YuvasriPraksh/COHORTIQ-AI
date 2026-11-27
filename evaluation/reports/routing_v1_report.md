# CohortIQ routing evaluation

Generated 2026-11-27 10:11 UTC. Dataset `cohortiq-routing-v1`.

## Setup

- **Questions:** 40 (24 held out, 16 used in calibration).
- **About the dataset:** Labelled routing questions for the adaptive router, on the two approved regulations in the project database ('SMVEC' 2023 for batches 2024-2025 'B-tech - CSE'; 'regulation 2' 2024 for batches 2022-2023 'b tech aids'). Labels follow the route definitions, not the router's output: general = answered by the cohort's regulations (even if retrieval ranks poorly); clause_lookup = cites a clause that exists for that cohort; low_evidence = about regulations but not answered by the cohort's approved regulations (including no applicable regulation and non-existent clauses); out_of_scope = not about academic regulations; clarify = cohort missing. Cases marked calibration were scored while choosing the threshold and vocabulary, so they are not held out.
- **Router settings:** minimum best retrieval score 3 (applied when the cohort corpus has at least 20 chunks); clause lookups use top 3.
- **Method:** each question runs through `route_question` on a temporary copy of the database. No answer is generated and no model is called. A prediction is correct when the route matches (and the reason, where the case specifies one).

## Results

| Measure | Value |
|---|---|
| Routing accuracy (all questions) | 90.0% (36/40) |
| Routing accuracy (held-out questions) | 83.3% (20/24) |

| Route | Expected | Predicted | Precision | Recall |
|---|---|---|---|---|
| general | 14 | 18 | 77.8% | 100.0% |
| clause_lookup | 6 | 6 | 100.0% | 100.0% |
| low_evidence | 7 | 4 | 100.0% | 57.1% |
| out_of_scope | 10 | 9 | 100.0% | 90.0% |
| clarify | 3 | 3 | 100.0% | 100.0% |

Confusion (expected → predicted), misroutes only:

- low_evidence → general: 3
- out_of_scope → general: 1

## Limitations

- The dataset is small (40 questions) and was written and labelled by the person who designed the router; calibration cases informed the threshold and vocabulary, so only the held-out accuracy approximates unseen questions.
- Out-of-scope detection is a fixed vocabulary check: an unrelated question that uses a regulation word (for example 'result') is not refused, and a regulation question phrased without any listed word is refused.
- The score threshold is a conservative floor on raw BM25 scores. It does not detect in-domain questions the regulations do not answer (for example an exam timetable or a tuition amount), because such questions share words with the regulations and score as high as answerable ones.
- BM25 scores depend on corpus size and question length. The threshold is skipped for corpora smaller than the minimum chunk count, and must be recalibrated when the regulations change substantially.
- Routing accuracy says nothing about answer quality: a correctly routed general question can still retrieve the wrong pages (see the retrieval report).
- The score-threshold abstention fired for 0 of 40 questions in this dataset; its behaviour is covered by unit tests on a synthetic corpus, not measured here.

## Per-question results

| Case | Expected | Predicted (reason) | Best score | Correct | Calibration | Note |
|---|---|---|---|---|---|---|
| general-attendance | general | general (evidence_found) | 15.01 | yes | yes |  |
| general-passing-theory-miss | general | general (evidence_found) | 9.88 | yes | yes | Genuine retrieval miss in the retrieval report: answered on page 19, which BM25 ranks outside the top 5. The route is still general; routing cannot fix ranking. |
| general-distinction | general | general (evidence_found) | 18.66 | yes | yes |  |
| general-grades | general | general (evidence_found) | 30.15 | yes | yes |  |
| general-honours | general | general (evidence_found) | 15.92 | yes | yes |  |
| general-attendance-scenario | general | general (evidence_found) | 11.08 | yes | yes |  |
| general-fail-course | general | general (evidence_found) | 3.75 | yes | yes | Lowest best score among answerable labelled questions (3.75). |
| general-revaluation-short | general | general (evidence_found) | 4.65 | yes | yes |  |
| general-practical-pass | general | general (evidence_found) | 15.19 | yes | no |  |
| general-lateral-distinction | general | general (evidence_found) | 16.42 | yes | no |  |
| general-sgpa | general | general (evidence_found) | 6.33 | yes | no |  |
| general-ragging | general | general (evidence_found) | 14.64 | yes | no |  |
| general-absent-grade | general | general (evidence_found) | 16.22 | yes | no |  |
| general-revaluation-arrears | general | general (evidence_found) | 19.92 | yes | no |  |
| clause-10-1 | clause_lookup | clause_lookup (clause_reference) | 4.48 | yes | yes |  |
| clause-14-3 | clause_lookup | clause_lookup (clause_reference) | 6.61 | yes | yes |  |
| clause-12-2-2 | clause_lookup | clause_lookup (clause_reference) | 6.37 | yes | yes |  |
| clause-11-2 | clause_lookup | clause_lookup (clause_reference) | 3.84 | yes | no |  |
| clause-section-12-1 | clause_lookup | clause_lookup (clause_reference) | 3.52 | yes | no |  |
| clause-8-2 | clause_lookup | clause_lookup (clause_reference) | 4.05 | yes | no |  |
| low-clause-99-4 | low_evidence (clause_not_found) | low_evidence (clause_not_found) | - | yes | yes |  |
| low-clause-42-7 | low_evidence (clause_not_found) | low_evidence (clause_not_found) | - | yes | no |  |
| low-no-regulation-batch | low_evidence (no_applicable_regulations) | low_evidence (no_applicable_regulations) | - | yes | no |  |
| low-programme-mismatch | low_evidence (no_applicable_regulations) | low_evidence (no_applicable_regulations) | - | yes | no |  |
| low-exam-timetable | low_evidence | general (evidence_found) | 9.14 | no | no | About examinations, but the regulations contain no timetable. |
| low-tuition-fee | low_evidence | general (evidence_found) | 8.72 | no | no | The regulations mention fees but state no tuition amount. |
| low-honours-not-in-r2 | low_evidence | general (evidence_found) | 9.40 | no | no | 'regulation 2' has no honours degree rule. |
| oos-cricket | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | yes |  |
| oos-weather | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | yes |  |
| oos-capital | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | yes |  |
| oos-joke | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | yes |  |
| oos-poem | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | no |  |
| oos-smartphone | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | no |  |
| oos-prime-minister | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | no |  |
| oos-translate | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | no |  |
| oos-cricket-result | out_of_scope | general (evidence_found) | 10.82 | no | no | Contains 'result', which is also a regulation term. |
| oos-cricket-no-cohort | out_of_scope | out_of_scope (no_regulation_terms) | - | yes | no | Out-of-scope is checked before the cohort. |
| clarify-no-batch | clarify | clarify (missing_cohort) | - | yes | no |  |
| clarify-no-programme | clarify | clarify (missing_cohort) | - | yes | no |  |
| clarify-no-cohort | clarify | clarify (missing_cohort) | - | yes | no |  |
