"""`papertrail export-demo`: static JSON for the GitHub Pages demo (BUILD_PLAN §8.11).

Runs the real pipeline with the Replay provider on the demo letters, in a temporary data
folder, and writes the same shapes the API returns. IDs and timestamps are made stable so
re-exporting only changes the files when the results change. No API calls.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from papertrail.api import document_detail, items_payload
from papertrail.clock import FixedClock
from papertrail.config import Settings
from papertrail.db import repo
from papertrail.db.connection import connect, migrate
from papertrail.extract.providers.replay import ReplayProvider
from papertrail.ingest import ingest_stream
from papertrail.jobs import InProcessParser, Worker

EXPORT_CLOCK = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _stable_ids(payload: Any, mapping: dict[str, str], prefix: str) -> Any:
    """Replace random UUIDs with readable, stable ones, consistently across the payload."""
    text = json.dumps(payload, ensure_ascii=False)

    def replace(match: re.Match[str]) -> str:
        found = match.group(0)
        if found not in mapping:
            mapping[found] = f"{prefix}-{len(mapping) + 1}"
        return mapping[found]

    return json.loads(_UUID.sub(replace, text))


def export_demo(
    *, documents: list[Path], recordings_dir: Path, out_dir: Path, base_settings: Settings
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        settings = base_settings.model_copy(
            update={"data_dir": Path(tmp), "provider": "replay", "recordings_dir": recordings_dir}
        )
        settings.ensure_dirs()
        conn = connect(settings.db_path)
        migrate(conn, settings.db_path)
        clock = FixedClock(EXPORT_CLOCK)
        provider = ReplayProvider(recordings_dir, model=settings.model)
        worker = Worker(settings, clock, lambda: provider, InProcessParser())
        stamp = EXPORT_CLOCK.isoformat().replace("+00:00", "Z")
        for pdf in documents:
            with pdf.open("rb") as handle:
                result = ingest_stream(conn, settings, handle, pdf.name, now=stamp)
            while worker.run_once():
                pass
            row = repo.get_document(conn, result.document["id"])
            assert row is not None
            if row["status"] != "ready":
                raise RuntimeError(
                    f"{pdf.name}: {row['status']} ({row['status_detail']}). "
                    "Is its recording in the recordings folder?"
                )
            slug = pdf.stem
            mapping = {row["id"]: slug}
            detail = _stable_ids(document_detail(conn, row).model_dump(mode="json"), mapping, slug)
            for run in ("current_run", "last_run"):
                if detail.get(run):
                    detail[run]["duration_ms"] = None  # replayed runs have no real latency
            items = _stable_ids(items_payload(conn, row).model_dump(mode="json"), mapping, slug)
            (out_dir / f"{slug}.json").write_text(
                json.dumps({"document": detail, "items": items}, indent=1, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            shutil.copyfile(pdf, out_dir / f"{slug}.pdf")
            index.append(
                {
                    k: detail[k]
                    for k in detail
                    if k not in ("pages", "current_run", "last_run", "job_active")
                }
            )
        worker.stop()
        conn.close()
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return index
