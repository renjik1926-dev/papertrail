"""CLI happy paths and main errors (BUILD_PLAN §8.12) with Typer's test runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from papertrail.cli import app, openapi_schema
from tests.conftest import EVAL_DOCS, FIXTURES, RECORDINGS, REPO

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv("PAPERTRAIL_DATA_DIR", str(data))
    monkeypatch.setenv("PAPERTRAIL_RECORDINGS_DIR", str(RECORDINGS))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env from the developer's folder
    return data


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and result.stdout.startswith("papertrail ")


def test_parse_prints_blocks() -> None:
    result = runner.invoke(app, ["parse", str(FIXTURES / "plain_letter.pdf")])
    assert result.exit_code == 0
    assert "[p1:b1]" in result.stdout and "Department of Example Services" in result.stdout


def test_parse_missing_file_exits_2() -> None:
    assert runner.invoke(app, ["parse", "nope.pdf"]).exit_code == 2


def test_parse_unsupported_explains() -> None:
    result = runner.invoke(app, ["parse", str(FIXTURES / "encrypted.pdf")])
    assert result.exit_code == 1 and "password-protected" in result.output


def test_run_with_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "replay")
    result = runner.invoke(app, ["run", str(EVAL_DOCS / "medical_bill_01.pdf")])
    assert result.exit_code == 0, result.output
    assert "[ok]" in result.stdout and "verified" in result.stdout
    as_json = runner.invoke(app, ["run", "--json", str(EVAL_DOCS / "medical_bill_01.pdf")])
    assert json.loads(as_json.stdout)["document_date"] == "2026-10-20"


def test_run_save_stores_the_document(monkeypatch: pytest.MonkeyPatch, isolated: Path) -> None:
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "replay")
    result = runner.invoke(app, ["run", "--save", str(EVAL_DOCS / "medical_bill_01.pdf")])
    assert result.exit_code == 0, result.output
    assert "saved as document" in result.output
    assert (isolated / "papertrail.db").is_file()


def test_missing_recording_says_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "replay")
    result = runner.invoke(app, ["run", str(FIXTURES / "plain_letter.pdf")])
    assert result.exit_code == 1 and "papertrail record" in result.output


def test_extract_without_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "claude")
    result = runner.invoke(app, ["extract", str(EVAL_DOCS / "medical_bill_01.pdf")])
    assert result.exit_code == 1 and "ANTHROPIC_API_KEY is not set" in result.output


def test_doctor_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "claude")
    failing = runner.invoke(app, ["doctor"])
    assert failing.exit_code == 1 and "API key" in failing.stdout and "not set" in failing.stdout
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "replay")
    passing = runner.invoke(app, ["doctor"])
    assert passing.exit_code == 0, passing.output
    assert "Model" in passing.stdout and "claude-haiku-5-5" in passing.stdout
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    shown = runner.invoke(app, ["doctor"])
    assert "sk-secret-value" not in shown.output and "set" in shown.stdout


def test_record_and_smoke_need_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)
    assert "ANTHROPIC_API_KEY" in runner.invoke(app, ["record", "--yes"]).output
    assert "ANTHROPIC_API_KEY" in runner.invoke(app, ["smoke", "--yes"]).output


def test_eval_with_replay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(REPO)
    result = runner.invoke(app, ["eval", "--split", "dev", "--out", str(tmp_path / "reports")])
    assert result.exit_code == 0, result.output
    assert "Wrong-but-verified" in result.stdout
    # The report must warn about placeholders exactly when any saved answer isn't from Claude.
    placeholders = any(
        json.loads(p.read_text(encoding="utf-8")).get("source") != "claude"
        for p in (REPO / "eval" / "recorded").glob("*.json")
    )
    assert ("hand-written placeholders" in result.stdout) == placeholders
    assert list((tmp_path / "reports").glob("*.json"))


def test_backup_and_restore_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: Path
) -> None:
    monkeypatch.setenv("PAPERTRAIL_PROVIDER", "replay")
    assert (
        runner.invoke(app, ["run", "--save", str(EVAL_DOCS / "medical_bill_01.pdf")]).exit_code == 0
    )
    archive = tmp_path / "backup.zip"
    assert runner.invoke(app, ["backup", str(archive)]).exit_code == 0
    # Restoring into the same (non-empty) folder is refused.
    refused = runner.invoke(app, ["restore", str(archive)])
    assert refused.exit_code == 1 and "isn't empty" in refused.output
    monkeypatch.setenv("PAPERTRAIL_DATA_DIR", str(tmp_path / "restored"))
    restored = runner.invoke(app, ["restore", str(archive)])
    assert restored.exit_code == 0, restored.output
    assert len(list((tmp_path / "restored" / "files").glob("*.pdf"))) == 1


def test_openapi_json_is_current() -> None:
    """The committed schema is the source of the frontend's TypeScript types (BUILD_PLAN §9)."""
    committed = REPO / "frontend" / "src" / "api" / "openapi.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == json.loads(
        json.dumps(openapi_schema(), sort_keys=True)
    ), "Run `papertrail openapi` and `npm run gen:api`, then commit the result."


def test_export_demo_writes_api_shaped_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(REPO)
    out = tmp_path / "demo"
    result = runner.invoke(app, ["export-demo", "--out", str(out)])
    assert result.exit_code == 0, result.output
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert [d["id"] for d in index] == ["tax_notice_01", "insurance_eob_01", "adversarial_01"]
    payload = json.loads((out / "tax_notice_01.json").read_text(encoding="utf-8"))
    assert payload["document"]["status"] == "ready"
    assert payload["items"]["items"] and (out / "tax_notice_01.pdf").is_file()
    # Stable IDs: re-exporting gives identical files.
    again = tmp_path / "again"
    runner.invoke(app, ["export-demo", "--out", str(again)])
    assert (again / "tax_notice_01.json").read_text() == (out / "tax_notice_01.json").read_text()
