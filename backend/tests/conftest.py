"""Shared test fixtures. No test needs the network or an API key."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from papertrail.api import create_app
from papertrail.clock import FixedClock
from papertrail.config import Settings
from papertrail.extract.providers.base import Provider
from papertrail.extract.providers.fake import FakeProvider
from papertrail.extract.providers.replay import ReplayProvider
from papertrail.jobs import InProcessParser, Worker

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures"
REPO = TESTS.parent.parent
EVAL_DOCS = REPO / "eval" / "docs"
RECORDINGS = REPO / "eval" / "recorded"
HEADERS = {"X-PaperTrail": "1"}
BASE_URL = "http://127.0.0.1:8000"
FIXED_NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        PAPERTRAIL_DATA_DIR=tmp_path / "data",
        PAPERTRAIL_PROVIDER="replay",
        PAPERTRAIL_RECORDINGS_DIR=RECORDINGS,
        ANTHROPIC_API_KEY="",
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(FIXED_NOW)


def make_client(
    settings: Settings, clock: FixedClock, provider: Provider | None = None
) -> tuple[TestClient, Worker]:
    chosen = provider or ReplayProvider(RECORDINGS, model=settings.model)
    app = create_app(
        settings,
        clock=clock,
        provider_factory=lambda: chosen,
        start_worker=False,
        parse_runner=InProcessParser(),
    )
    client = TestClient(app, base_url=BASE_URL)
    return client, app.state.worker


@pytest.fixture
def client_factory(
    settings: Settings, clock: FixedClock
) -> Iterator[Callable[..., tuple[TestClient, Worker]]]:
    clients: list[TestClient] = []

    def factory(provider: Provider | None = None, **overrides: Any) -> tuple[TestClient, Worker]:
        chosen_settings = settings.model_copy(update=overrides) if overrides else settings
        client, worker = make_client(chosen_settings, clock, provider)
        client.__enter__()
        clients.append(client)
        return client, worker

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(client_factory: Callable[..., tuple[TestClient, Worker]]) -> tuple[TestClient, Worker]:
    return client_factory()


@pytest.fixture
def fake_client(
    client_factory: Callable[..., tuple[TestClient, Worker]],
) -> tuple[TestClient, Worker]:
    return client_factory(FakeProvider(), PAPERTRAIL_PROVIDER="fake")


def upload(client: TestClient, path: Path, name: str | None = None) -> dict[str, Any]:
    with path.open("rb") as handle:
        response = client.post(
            "/api/documents",
            files={"file": (name or path.name, handle, "application/pdf")},
            headers=HEADERS,
        )
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


def process_all(worker: Worker) -> int:
    count = 0
    while worker.run_once():
        count += 1
    return count
