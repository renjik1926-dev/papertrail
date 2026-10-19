"""Blocks -> the tagged document text sent to the model (BUILD_PLAN §8.5)."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.resources import files

from papertrail.parse.models import Block

PROMPT_VERSION = "extract_v1"


def load_prompt(version: str = PROMPT_VERSION) -> str:
    """The system prompt's exact contents (they are part of the replay request hash)."""
    resource = files("papertrail.extract") / "prompts" / f"{version}.md"
    return resource.read_text(encoding="utf-8")


def render_blocks(blocks: Sequence[Block], page_count: int) -> str:
    lines = [f'<document pages="{page_count}">']
    for block in sorted(blocks, key=lambda b: b.seq):
        lines.append(f"[{block.id}] {block.text}")
    lines.append("</document>")
    return "\n".join(lines)
