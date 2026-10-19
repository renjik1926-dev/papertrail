"""parse -> extract (one AI call) -> verify -> locate, shared by the CLI and the worker."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from papertrail.errors import Reason
from papertrail.extract.providers.base import Provider
from papertrail.extract.render import PROMPT_VERSION, render_blocks
from papertrail.extract.runner import ExtractionOutcome, run_extraction
from papertrail.parse import parse_pdf
from papertrail.parse.models import ParsedDocument, ParseOutcome
from papertrail.verify import verify_extraction
from papertrail.verify.models import VerifiedDocument


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_document(document: ParsedDocument) -> str:
    return render_blocks(document.blocks, len(document.pages))


@dataclass(frozen=True)
class ExtractAndVerify:
    extraction: ExtractionOutcome
    verified: VerifiedDocument | None

    @property
    def reason(self) -> Reason | None:
        return self.extraction.reason


def extract_and_verify(
    document: ParsedDocument,
    *,
    document_sha256: str,
    provider: Provider,
    effort: str,
    prompt_version: str = PROMPT_VERSION,
) -> ExtractAndVerify:
    outcome = run_extraction(
        provider, render_document(document), prompt_version=prompt_version, effort=effort
    )
    if not outcome.ok or outcome.result is None or outcome.result.extraction is None:
        return ExtractAndVerify(outcome, None)
    verified = verify_extraction(
        outcome.result.extraction, document.blocks, document_sha256=document_sha256
    )
    return ExtractAndVerify(outcome, verified)


@dataclass(frozen=True)
class PipelineResult:
    sha256: str
    parse: ParseOutcome
    run: ExtractAndVerify | None

    @property
    def reason(self) -> str | None:
        if self.parse.status != "ok":
            return self.parse.reason
        if self.run is None:
            return None
        return self.run.reason


def run_in_memory(path: Path, *, provider: Provider, effort: str, max_pages: int) -> PipelineResult:
    """The whole pipeline without the database (`papertrail run`)."""
    sha = file_sha256(path)
    parsed = parse_pdf(path, max_pages=max_pages)
    if parsed.status != "ok" or parsed.document is None:
        return PipelineResult(sha, parsed, None)
    return PipelineResult(
        sha,
        parsed,
        extract_and_verify(parsed.document, document_sha256=sha, provider=provider, effort=effort),
    )
