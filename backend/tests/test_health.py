"""Tests for the FastAPI backend health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_health_endpoint_returns_running_status() -> None:
    """GET /api/v1/health should return a JSON response indicating the API is running."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "CohortIQ AI API",
        "message": "API is running",
    }


def test_root_endpoint_returns_welcome_and_docs_path() -> None:
    """GET / should return a welcome response with the API documentation path."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Welcome to CohortIQ AI API",
        "docs": "/docs",
    }
