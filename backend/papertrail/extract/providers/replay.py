"""Replay provider: returns saved responses keyed by request hash (BUILD_PLAN §8.5).

Used by CI, the Playwright tests and the demo export, so none of them need an API key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from papertrail.errors import Reason
from papertrail.extract.providers.base import (
    ExtractResult,
    ProviderError,
    request_hash,
    result_from_raw,
)
from papertrail.extract.render import load_prompt

RECORDING_FORMAT = 1


class MissingRecordingError(ProviderError):
    def __init__(self, digest: str, directory: Path) -> None:
        super().__init__(
            Reason.missing_recording,
            f"Missing recording {digest}.json in {directory} - run `papertrail record` "
            "(the parser, prompt, schema, model or effort changed since it was recorded).",
        )
        self.digest = digest


def recording_path(directory: Path, digest: str) -> Path:
    return directory / f"{digest}.json"


def load_recording(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def write_recording(
    directory: Path,
    *,
    digest: str,
    response: dict[str, Any],
    source: str,
    document_name: str,
    document_sha256: str,
    model: str,
    effort: str,
    prompt_version: str,
    recorded_at: str,
    note: str = "",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "format": RECORDING_FORMAT,
        "request_hash": digest,
        "source": source,
        "note": note,
        "document": document_name,
        "document_sha256": document_sha256,
        "settings": {"model": model, "effort": effort, "prompt_version": prompt_version},
        "recorded_at": recorded_at,
        "response": response,
    }
    path = recording_path(directory, digest)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


class ReplayProvider:
    name = "replay"

    def __init__(self, recordings_dir: Path, *, model: str) -> None:
        self.recordings_dir = recordings_dir
        self.model = model

    def digest(self, rendered_document: str, *, prompt_version: str, effort: str) -> str:
        return request_hash(
            model=self.model,
            effort=effort,
            prompt_text=load_prompt(prompt_version),
            rendered_document=rendered_document,
        )

    def extract(self, rendered_document: str, *, prompt_version: str, effort: str) -> ExtractResult:
        digest = self.digest(rendered_document, prompt_version=prompt_version, effort=effort)
        path = recording_path(self.recordings_dir, digest)
        if not path.is_file():
            raise MissingRecordingError(digest, self.recordings_dir)
        record = load_recording(path)
        response = record.get("response")
        if not isinstance(response, dict):
            raise ProviderError(Reason.invalid_output, f"Recording {path.name} has no response.")
        return result_from_raw(response, model=self.model)
