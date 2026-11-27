"""Route inventory guard (Part 4, Stage 4).

Every registered route, including nested routers and FastAPI's documentation
routes, must appear in ``backend.app.api.permissions.ROUTE_PERMISSIONS``, and
its actual dependency tree must match its classification:

- PUBLIC: neither ``get_current_user`` nor ``require_administrator``.
- AUTHENTICATED: ``get_current_user``, but not ``require_administrator``.
- ADMINISTRATOR: ``require_administrator``.

Adding a route without classifying it, or classifying it inconsistently with
its dependencies, fails these tests. Behavioural probes then confirm the
classification over HTTP: anonymous callers get 401 on every protected route
and students get 403 on every administrator route.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.database import init_database
from backend.app.api import deps
from backend.app.api.permissions import ROUTE_PERMISSIONS, Access
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.audit.repository import init_audit_tables
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT
from backend.app.main import app
from backend.tests.auth_support import create_signed_in_account, make_auth_settings, use_auth_database

PROTECTED = (Access.AUTHENTICATED, Access.ADMINISTRATOR)


@dataclass(frozen=True)
class RegisteredRoute:
    method: str
    path: str
    calls: frozenset[Any]
    in_schema: bool


def _dependency_calls(dependant: Any) -> Iterator[Any]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _dependency_calls(dependency)


def registered_routes(routes: Iterable[Any], prefix: str = "", inherited: tuple[Any, ...] = ()) -> Iterator[RegisteredRoute]:
    """Yield every (method, full path) the application serves, with its dependency calls.

    FastAPI 0.165 keeps included routers as nested wrappers whose
    ``include_context`` carries the prefix and router-level dependencies, so the
    tree is walked recursively. Older versions flatten routes; both are handled.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            calls = frozenset(set(_dependency_calls(route.dependant)) | set(inherited))
            for method in sorted(route.methods - {"HEAD"}):
                yield RegisteredRoute(method, prefix + route.path, calls, bool(route.include_in_schema))
        elif isinstance(route, Route):
            for method in sorted((route.methods or {"GET"}) - {"HEAD"}):
                yield RegisteredRoute(method, prefix + route.path, frozenset(inherited), False)
        else:
            context = getattr(route, "include_context", None)
            nested = getattr(route, "original_router", None) or getattr(context, "included_router", None)
            if nested is None:
                raise AssertionError(f"Unrecognized route type {type(route).__name__}; extend the inventory walker.")
            router_dependencies = tuple(dependency.dependency for dependency in getattr(context, "dependencies", []) or [])
            yield from registered_routes(
                nested.routes,
                prefix + (getattr(context, "prefix", "") or ""),
                inherited + router_dependencies,
            )


def unclassified_routes(application: FastAPI) -> set[tuple[str, str]]:
    return {(route.method, route.path) for route in registered_routes(application.routes)} - set(ROUTE_PERMISSIONS)


ROUTES = list(registered_routes(app.routes))


# --------------------------------------------------------------------------- #
# Inventory completeness
# --------------------------------------------------------------------------- #


def test_every_registered_route_is_classified() -> None:
    assert unclassified_routes(app) == set(), "Classify new routes in backend/app/api/permissions.py"


def test_every_classification_names_a_registered_route() -> None:
    registered = {(route.method, route.path) for route in ROUTES}
    assert set(ROUTE_PERMISSIONS) - registered == set(), "Remove stale entries from ROUTE_PERMISSIONS"


def test_route_walk_reaches_every_documented_operation() -> None:
    """Guards against the walker silently missing nested routes."""
    schema = TestClient(app).get("/openapi.json").json()
    documented = {(method.upper(), path) for path, operations in schema["paths"].items() for method in operations}

    assert documented == {(route.method, route.path) for route in ROUTES if route.in_schema}
    assert len(documented) >= 11


def test_inventory_lists_the_expected_classifications() -> None:
    api = "/api/v1"
    assert {key for key, access in ROUTE_PERMISSIONS.items() if access is Access.ADMINISTRATOR} == {
        ("POST", f"{api}/regulations/ingest"),
        ("PATCH", f"{api}/regulations/{{regulation_id}}/verification"),
        ("GET", f"{api}/admin/users"),
        ("POST", f"{api}/admin/users"),
        ("GET", f"{api}/admin/users/{{user_id}}"),
        ("PATCH", f"{api}/admin/users/{{user_id}}"),
        ("PATCH", f"{api}/admin/users/{{user_id}}/role"),
        ("POST", f"{api}/admin/users/{{user_id}}/password"),
        ("POST", f"{api}/admin/users/{{user_id}}/deactivate"),
        ("POST", f"{api}/admin/users/{{user_id}}/reactivate"),
        ("POST", f"{api}/admin/users/{{user_id}}/unlock"),
        ("POST", f"{api}/admin/users/{{user_id}}/revoke-sessions"),
        ("GET", f"{api}/admin/audit-events"),
    }
    assert {key for key, access in ROUTE_PERMISSIONS.items() if access is Access.PUBLIC} == {
        ("GET", "/"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
        ("GET", f"{api}/health"),
        ("POST", f"{api}/auth/login"),
    }


def test_guard_detects_an_unclassified_route() -> None:
    probe = FastAPI()
    router = APIRouter()

    @router.get("/secret-report")
    def secret_report() -> dict[str, str]:
        return {}

    probe.include_router(router, prefix="/api/v1")

    assert ("GET", "/api/v1/secret-report") in unclassified_routes(probe)


def test_walker_includes_router_level_dependencies() -> None:
    probe = FastAPI()
    router = APIRouter()

    @router.get("/inner")
    def inner() -> dict[str, str]:
        return {}

    probe.include_router(router, prefix="/outer", dependencies=[Depends(deps.require_administrator)])

    [route] = [route for route in registered_routes(probe.routes) if route.path == "/outer/inner"]
    assert deps.require_administrator in route.calls


# --------------------------------------------------------------------------- #
# Dependencies match classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
def test_route_dependencies_match_classification(route: RegisteredRoute) -> None:
    access = ROUTE_PERMISSIONS[(route.method, route.path)]
    authenticates = deps.get_current_user in route.calls
    administrator_only = deps.require_administrator in route.calls

    if access is Access.PUBLIC:
        assert not authenticates and not administrator_only
    elif access is Access.AUTHENTICATED:
        assert authenticates and not administrator_only
    else:
        assert administrator_only and authenticates  # require_administrator depends on get_current_user


def test_openapi_security_matches_inventory() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    secured = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if operation.get("security") == [{"HTTPBearer": []}]
    }
    expected = {(route.method, route.path) for route in ROUTES if route.in_schema and ROUTE_PERMISSIONS[(route.method, route.path)] in PROTECTED}

    assert secured == expected
    for method, path in expected:
        responses = schema["paths"][path][method.lower()]["responses"]
        assert "401" in responses, (method, path)
        if ROUTE_PERMISSIONS[(method, path)] is Access.ADMINISTRATOR:
            assert "403" in responses, (method, path)


# --------------------------------------------------------------------------- #
# Behavioural probes over HTTP
# --------------------------------------------------------------------------- #


def _concrete(path: str) -> str:
    return (
        path.replace("{regulation_id}", "1")
        .replace("{user_id}", "1")
        .replace("{admission_batch}", "2024")
        .replace("{programme}", "BSc CS")
    )


def _request(client: TestClient, method: str, path: str, headers: dict[str, str] | None = None) -> Any:
    kwargs: dict[str, Any] = {"headers": headers or {}}
    if method in ("POST", "PATCH", "PUT"):
        kwargs["json"] = {}
    return client.request(method, _concrete(path), **kwargs)


@pytest.fixture
def probe_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any, Any]]:
    db_path = tmp_path / "probe.db"
    init_database(db_path)
    init_audit_tables(db_path)
    settings = make_auth_settings()
    use_auth_database(app, monkeypatch, db_path, settings)
    monkeypatch.setitem(app.dependency_overrides, regulation_routes.get_db_path, lambda: str(db_path))
    monkeypatch.setitem(app.dependency_overrides, query_routes.get_db_path, lambda: str(db_path))
    student = create_signed_in_account(db_path, settings, ROLE_STUDENT, admission_batch="2024", programme="BSc CS")
    admin = create_signed_in_account(db_path, settings, ROLE_ADMINISTRATOR)
    yield TestClient(app), student, admin


@pytest.mark.parametrize("key", sorted(ROUTE_PERMISSIONS), ids=lambda key: f"{key[0]} {key[1]}")
def test_anonymous_access_matches_classification(probe_client: tuple[TestClient, Any, Any], key: tuple[str, str]) -> None:
    client = probe_client[0]
    response = _request(client, *key)

    if ROUTE_PERMISSIONS[key] is Access.PUBLIC:
        assert response.status_code != 401
        assert response.status_code < 500
    else:
        assert response.status_code == 401
        assert response.json() == {"detail": deps.NOT_AUTHENTICATED_DETAIL}
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "key", sorted(k for k, access in ROUTE_PERMISSIONS.items() if access is Access.ADMINISTRATOR), ids=lambda key: f"{key[0]} {key[1]}"
)
def test_students_are_refused_administrator_routes(probe_client: tuple[TestClient, Any, Any], key: tuple[str, str]) -> None:
    client, student, admin = probe_client

    student_response = _request(client, *key, headers=student.headers)
    admin_response = _request(client, *key, headers=admin.headers)

    assert student_response.status_code == 403
    assert student_response.json() == {"detail": deps.FORBIDDEN_DETAIL}
    assert admin_response.status_code not in (401, 403)  # authorized: reaches validation or succeeds
    assert admin_response.status_code < 500


@pytest.mark.parametrize(
    "key", sorted(k for k, access in ROUTE_PERMISSIONS.items() if access is Access.AUTHENTICATED), ids=lambda key: f"{key[0]} {key[1]}"
)
def test_authenticated_routes_admit_both_roles(probe_client: tuple[TestClient, Any, Any], key: tuple[str, str]) -> None:
    client, student, admin = probe_client

    # A student may still be refused on cohort or visibility grounds, but never
    # because of authentication or the administrator-only gate.
    assert _request(client, *key, headers=student.headers).json() != {"detail": deps.FORBIDDEN_DETAIL}
    assert _request(client, *key, headers=student.headers).status_code != 401
    assert _request(client, *key, headers=admin.headers).status_code not in (401, 403)


@pytest.mark.parametrize(
    "method, path",
    [("GET", "/api/v1/does-not-exist"), ("GET", "/api/v1/admin"), ("POST", "/api/v1/users"), ("GET", "/api/v1/auth/register")],
)
def test_unknown_routes_return_404(probe_client: tuple[TestClient, Any, Any], method: str, path: str) -> None:
    client, student, admin = probe_client

    for headers in ({}, student.headers, admin.headers):
        assert client.request(method, path, headers=headers).status_code == 404


def test_unregistered_methods_on_known_paths_are_refused(probe_client: tuple[TestClient, Any, Any]) -> None:
    client, _student, admin = probe_client

    assert client.delete("/api/v1/regulations/1", headers=admin.headers).status_code == 405
    assert client.put("/api/v1/regulations/1/verification", headers=admin.headers).status_code == 405
    assert client.get("/api/v1/regulations/ingest", headers=admin.headers).status_code in (404, 422)
