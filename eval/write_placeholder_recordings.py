"""Wrap the hand-written answers in eval/placeholder_outputs/ as Replay recordings.

There is no API key in the environment where this draft was built, so these stand in for
real Claude responses until `papertrail record` replaces them. Each recording is marked
`"source": "hand-written placeholder"`, and the eval report says so. Never present results
built on them as Claude's accuracy.

Re-run this after changing the parser, prompt, schema, model or effort (the request hash
changes):

    uv run --project backend python eval/write_placeholder_recordings.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from papertrail.config import load_settings
from papertrail.extract.providers.base import request_hash
from papertrail.extract.providers.replay import recording_path, write_recording
from papertrail.extract.render import PROMPT_VERSION, load_prompt
from papertrail.extract.schema import Extraction
from papertrail.parse import parse_pdf
from papertrail.pipeline import file_sha256, render_document

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "hand-written placeholder"
NOTE = (
    "Written by hand to stand in for a real Claude response (no API key was available). "
    "Replace with `papertrail record`."
)


def main() -> int:
    settings = load_settings()
    recordings = ROOT / "eval" / "recorded"
    prompt_text = load_prompt(PROMPT_VERSION)
    for stale in recordings.glob("*.json"):
        if json.loads(stale.read_text(encoding="utf-8")).get("source") == SOURCE:
            stale.unlink()
    for answer in sorted((ROOT / "eval" / "placeholder_outputs").glob("*.json")):
        pdf = ROOT / "eval" / "docs" / f"{answer.stem}.pdf"
        extraction = Extraction.model_validate_json(answer.read_text(encoding="utf-8"))
        parsed = parse_pdf(pdf, max_pages=settings.max_pages)
        if parsed.document is None:
            print(f"{pdf.name}: {parsed.status} {parsed.reason}", file=sys.stderr)
            return 1
        rendered = render_document(parsed.document)
        digest = request_hash(
            model=settings.model, effort=settings.effort, prompt_text=prompt_text, rendered_document=rendered
        )
        existing = recording_path(recordings, digest)
        if existing.is_file() and json.loads(existing.read_text(encoding="utf-8")).get("source") == "claude":
            print(f"{pdf.name}: keeping the real recording")
            continue
        response = {
            "id": f"placeholder-{answer.stem}",
            "type": "message",
            "role": "assistant",
            "model": settings.model,
            "content": [{"type": "text", "text": extraction.model_dump_json()}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "stop_details": None,
            # Unknown: no real call was made, so no token counts are invented.
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        write_recording(
            recordings,
            digest=digest,
            response=response,
            source=SOURCE,
            note=NOTE,
            document_name=pdf.name,
            document_sha256=file_sha256(pdf),
            model=settings.model,
            effort=settings.effort,
            prompt_version=PROMPT_VERSION,
            recorded_at="2026-10-19T00:00:00Z",
        )
        print(f"{pdf.name}: {digest[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
