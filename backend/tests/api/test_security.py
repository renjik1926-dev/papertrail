"""Local-server protections (BUILD_PLAN §9): Host check, required header, Origin check, headers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from papertrail.jobs import Worker
from papertrail.security import CONTENT_SECURITY_POLICY
from tests.conftest import HEADERS

FORBIDDEN = {
    "error": {"code": "forbidden_origin", "message": "This request was blocked for your safety."}
}


def test_wrong_host_is_403(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    response = http.get("/api/health", headers={"Host": "attacker.example:8000"})
    assert response.status_code == 403 and response.json() == FORBIDDEN
    assert http.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200


def test_state_changing_request_needs_the_custom_header(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    response = http.put("/api/settings/privacy_notice_ack", json={"value": "true"})
    assert response.status_code == 403 and response.json() == FORBIDDEN
    assert http.post("/api/documents/x/reprocess").status_code == 403
    assert http.delete("/api/documents/x").status_code == 403
    # Reads don't need it.
    assert http.get("/api/settings").status_code == 200


def test_foreign_origin_is_403(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    evil = http.put(
        "/api/settings/privacy_notice_ack",
        json={"value": "true"},
        headers={**HEADERS, "Origin": "https://attacker.example"},
    )
    assert evil.status_code == 403
    own = http.put(
        "/api/settings/privacy_notice_ack",
        json={"value": "true"},
        headers={**HEADERS, "Origin": "http://127.0.0.1:8000"},
    )
    assert own.status_code == 200


def test_vite_origin_only_in_dev_mode(client_factory) -> None:
    vite = {**HEADERS, "Origin": "http://localhost:5173"}
    release, _ = client_factory()
    assert (
        release.put(
            "/api/settings/privacy_notice_ack", json={"value": "true"}, headers=vite
        ).status_code
        == 403
    )
    dev, _ = client_factory(dev=True)
    assert (
        dev.put(
            "/api/settings/privacy_notice_ack", json={"value": "true"}, headers=vite
        ).status_code
        == 200
    )


def test_security_headers_and_no_cors(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    response = http.get("/api/health", headers={"Origin": "https://attacker.example"})
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in response.headers
    preflight = http.options(
        "/api/documents",
        headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers
