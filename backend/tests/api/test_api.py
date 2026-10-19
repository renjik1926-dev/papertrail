"""API behavior (BUILD_PLAN §9): uploads, errors, items, reviews, re-processing, export, delete."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from papertrail.ingest import clean_filename
from papertrail.jobs import Worker
from tests.conftest import EVAL_DOCS, FIXTURES, HEADERS, process_all, upload


def test_health(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    body = http.get("/api/health").json()
    assert body["ok"] is True and body["version"] and body["worker"] == "stopped"


def test_not_a_pdf_is_415(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    response = http.post(
        "/api/documents",
        files={"file": ("x.pdf", io.BytesIO(b"hello" * 400), "application/pdf")},
        headers=HEADERS,
    )
    assert response.status_code == 415
    assert response.json() == {"error": {"code": "not_a_pdf", "message": "That file isn't a PDF."}}


def test_pdf_header_may_follow_some_leading_bytes(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    data = b"junk" * 10 + (FIXTURES / "plain_letter.pdf").read_bytes()
    response = http.post(
        "/api/documents",
        files={"file": ("x.pdf", io.BytesIO(data), "application/pdf")},
        headers=HEADERS,
    )
    assert response.status_code == 201


def test_too_large_is_413(client_factory) -> None:
    http, _ = client_factory(PAPERTRAIL_MAX_MB=1, max_mb=1)
    data = b"%PDF-1.7\n" + b"0" * (1024 * 1024 + 10)
    response = http.post(
        "/api/documents",
        files={"file": ("big.pdf", io.BytesIO(data), "application/pdf")},
        headers=HEADERS,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"


def test_upload_is_deduplicated_by_hash(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    first = upload(http, EVAL_DOCS / "medical_bill_01.pdf")
    with (EVAL_DOCS / "medical_bill_01.pdf").open("rb") as handle:
        again = http.post(
            "/api/documents",
            files={"file": ("copy.pdf", handle, "application/pdf")},
            headers=HEADERS,
        )
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    assert len(http.get("/api/documents").json()) == 1


def test_filename_is_display_only(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    doc = upload(http, FIXTURES / "plain_letter.pdf", name="../../etc/passwd.pdf")
    assert doc["filename"] == "passwd.pdf"


def test_clean_filename() -> None:
    assert clean_filename("..\\a\\b\x07.pdf") == "b.pdf"
    assert clean_filename("") == "letter.pdf"
    assert len(clean_filename("x" * 500)) == 200


def test_unknown_document_is_404(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    for path in ("/api/documents/nope", "/api/documents/nope/items", "/api/documents/nope/file"):
        response = http.get(path)
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    assert http.get("/api/no-such-endpoint").status_code == 404


def test_full_flow_with_replay(client: tuple[TestClient, Worker]) -> None:
    http, worker = client
    doc = upload(http, EVAL_DOCS / "tax_notice_01.pdf")
    assert doc["status"] == "queued"
    process_all(worker)

    detail = http.get(f"/api/documents/{doc['id']}").json()
    assert detail["status"] == "ready" and detail["document_date"] == "2026-11-02"
    assert [p["page_no"] for p in detail["pages"]] == [1, 2]
    assert detail["current_run"]["provider"] == "replay"
    assert detail["current_run"]["estimated_cost_usd"] is None  # only real Claude runs have a cost

    payload = http.get(f"/api/documents/{doc['id']}/items").json()
    items = payload["items"]
    kinds = {i["kind"] for i in items}
    assert {"action", "document", "deadline", "amount", "contact"} <= kinds
    owed = next(i for i in items if i["kind"] == "amount")
    assert owed["amount_cents"] == 124000 and owed["status"] == "verified" and owed["rects"]
    relative = next(i for i in items if i["kind"] == "deadline" and i["due_calc"])
    assert relative["due_date"] == "2027-01-01"
    attached = [i for i in items if i["kind"] == "deadline" and i["parent_item_id"]]
    assert attached, "a deadline should attach to its action"
    flagged = [i for i in items if i["status"] == "needs_review"]
    assert all(i["reasons"] for i in flagged)

    pdf = http.get(f"/api/documents/{doc['id']}/file")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert (
        pdf.headers["content-disposition"] == "inline"
        and pdf.headers["cache-control"] == "no-store"
    )

    ics = http.get(f"/api/documents/{doc['id']}/calendar.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert ics.text.count("BEGIN:VEVENT") == 3


def test_reviews_are_recorded_and_restorable(client: tuple[TestClient, Worker], settings) -> None:
    http, worker = client
    doc = upload(http, EVAL_DOCS / "medical_bill_01.pdf")
    process_all(worker)
    item = next(
        i
        for i in http.get(f"/api/documents/{doc['id']}/items").json()["items"]
        if i["kind"] == "deadline"
    )

    accepted = http.patch(
        f"/api/items/{item['id']}", json={"action": "accept"}, headers=HEADERS
    ).json()
    assert accepted["review_state"] == "accepted"
    edited = http.patch(
        f"/api/items/{item['id']}",
        json={"action": "edit", "changes": {"text": "Pay the hospital", "due_date": "2026-11-20"}},
        headers=HEADERS,
    ).json()
    assert (edited["review_state"], edited["text"], edited["due_date"]) == (
        "edited",
        "Pay the hospital",
        "2026-11-20",
    )
    assert edited["original"]["text"] == item["text"]
    dismissed = http.patch(
        f"/api/items/{item['id']}", json={"action": "dismiss"}, headers=HEADERS
    ).json()
    assert dismissed["review_state"] == "dismissed"
    restored = http.patch(
        f"/api/items/{item['id']}", json={"action": "restore"}, headers=HEADERS
    ).json()
    assert (restored["review_state"], restored["text"], restored["due_date"]) == (
        "none",
        item["text"],
        item["due_date"],
    )

    conn = sqlite3.connect(settings.db_path)
    actions = [
        r[0]
        for r in conn.execute(
            "SELECT action FROM reviews WHERE item_id = ? ORDER BY rowid", (item["id"],)
        )
    ]
    assert actions == ["accept", "edit", "dismiss", "restore"]


def test_quote_and_sources_cannot_be_edited(client: tuple[TestClient, Worker]) -> None:
    http, worker = client
    doc = upload(http, EVAL_DOCS / "medical_bill_01.pdf")
    process_all(worker)
    item = http.get(f"/api/documents/{doc['id']}/items").json()["items"][0]
    response = http.patch(
        f"/api/items/{item['id']}",
        json={"action": "edit", "changes": {"quote": "made up"}},
        headers=HEADERS,
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"
    bad_date = http.patch(
        f"/api/items/{item['id']}",
        json={"action": "edit", "changes": {"due_date": "soon"}},
        headers=HEADERS,
    )
    assert bad_date.status_code == 422 and "due_date" in bad_date.json()["error"]["message"]
    malformed = http.patch(
        f"/api/items/{item['id']}",
        content=b"{not json",
        headers={**HEADERS, "content-type": "application/json"},
    )
    assert malformed.status_code == 400 and malformed.json()["error"]["code"] == "bad_request"
    missing = http.patch("/api/items/nope", json={"action": "accept"}, headers=HEADERS)
    assert missing.status_code == 404


def test_reprocess_carries_reviews_over_and_409s_while_queued(
    client: tuple[TestClient, Worker],
) -> None:
    http, worker = client
    doc = upload(http, EVAL_DOCS / "medical_bill_01.pdf")
    process_all(worker)
    items = http.get(f"/api/documents/{doc['id']}/items").json()["items"]
    target = next(i for i in items if i["kind"] == "amount")
    http.patch(
        f"/api/items/{target['id']}",
        json={"action": "edit", "changes": {"amount_cents": 23700}},
        headers=HEADERS,
    )

    assert http.post(f"/api/documents/{doc['id']}/reprocess", headers=HEADERS).status_code == 202
    conflict = http.post(f"/api/documents/{doc['id']}/reprocess", headers=HEADERS)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "job_in_progress"
    process_all(worker)

    payload = http.get(f"/api/documents/{doc['id']}/items").json()
    carried = next(i for i in payload["items"] if i["item_key"] == target["item_key"])
    assert carried["id"] != target["id"]
    assert (carried["review_state"], carried["amount_cents"]) == ("edited", 23700)
    assert payload["no_longer_found"] == []


def test_settings_endpoints(client: tuple[TestClient, Worker]) -> None:
    http, _ = client
    assert http.get("/api/settings").json() == {"privacy_notice_ack": False}
    assert http.put(
        "/api/settings/privacy_notice_ack", json={"value": "true"}, headers=HEADERS
    ).json() == {"privacy_notice_ack": True}
    assert (
        http.put("/api/settings/unknown", json={"value": "true"}, headers=HEADERS).status_code
        == 404
    )
    assert (
        http.put(
            "/api/settings/privacy_notice_ack", json={"value": "maybe"}, headers=HEADERS
        ).status_code
        == 422
    )


def test_unsupported_document_shows_reason(client: tuple[TestClient, Worker]) -> None:
    http, worker = client
    doc = upload(http, FIXTURES / "scanned.pdf")
    process_all(worker)
    detail = http.get(f"/api/documents/{doc['id']}").json()
    assert (detail["status"], detail["status_detail"]) == ("unsupported", "scanned")
    assert "scanned" in detail["status_message"]


def test_missing_recording_fails_with_reason(client: tuple[TestClient, Worker]) -> None:
    http, worker = client
    doc = upload(http, FIXTURES / "plain_letter.pdf")
    process_all(worker)
    detail = http.get(f"/api/documents/{doc['id']}").json()
    assert (detail["status"], detail["status_detail"]) == ("failed", "missing_recording")
    assert detail["last_run"]["status"] == "failed"


def test_delete_removes_rows_and_files(client: tuple[TestClient, Worker], settings) -> None:
    http, worker = client
    doc = upload(http, EVAL_DOCS / "medical_bill_01.pdf")
    process_all(worker)
    assert list(settings.runs_dir.glob("*.json")) and list(settings.files_dir.glob("*.pdf"))
    assert http.delete(f"/api/documents/{doc['id']}", headers=HEADERS).status_code == 204
    assert http.get(f"/api/documents/{doc['id']}").status_code == 404
    assert not list(settings.runs_dir.glob("*.json")) and not list(settings.files_dir.glob("*.pdf"))
    assert http.delete(f"/api/documents/{doc['id']}", headers=HEADERS).status_code == 404


def test_orphan_files_are_swept_on_startup(client_factory, settings) -> None:
    settings.ensure_dirs()
    orphan_pdf = settings.files_dir / ("f" * 64 + ".pdf")
    orphan_run = settings.runs_dir / "00000000-0000-0000-0000-000000000000.json"
    orphan_pdf.write_bytes(b"%PDF-")
    orphan_run.write_text("{}")
    client_factory()
    assert not orphan_pdf.exists() and not orphan_run.exists()


def test_frontend_fallback_serves_index(
    client: tuple[TestClient, Worker], tmp_path: Path, monkeypatch
) -> None:
    http, _ = client
    # Without a built frontend, non-API paths explain how to get one.
    response = http.get("/documents/abc")
    assert response.status_code == 404
