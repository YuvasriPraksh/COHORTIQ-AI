"""Offline evaluation of CohortIQ (modules M7 and M6).

Separate from the application: it runs the retrieval-only workflow and the
end-to-end Adaptive RAG router path on a temporary copy of a database, scores
the results against labelled datasets and writes reports. No model or external
service is called.

Run from the project root::

    python -m evaluation --output evaluation/reports/retrieval_v1_report.md
    python -m evaluation.routing --output evaluation/reports/routing_v1_report.md
"""
