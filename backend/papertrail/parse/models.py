"""Plain data produced by the parser. Pydantic models so they round-trip through a child process."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Word(Frozen):
    text: str
    char_start: int  # offset into the block text
    char_end: int
    x0: float  # PDF points, origin at the page's visible top-left
    top: float
    x1: float
    bottom: float


class Block(Frozen):
    id: str  # "p2:b14"
    page_no: int  # 1-based
    seq: int  # reading order across the document
    text: str  # words joined by spaces, lines joined by "\n"
    x0: float
    top: float
    x1: float
    bottom: float
    words: tuple[Word, ...]


class PageInfo(Frozen):
    page_no: int
    width: float
    height: float
    is_scanned: bool


class ParsedDocument(Frozen):
    parser_version: str
    pages: tuple[PageInfo, ...]
    blocks: tuple[Block, ...]


ParseStatus = Literal["ok", "unsupported", "failed"]


class ParseOutcome(Frozen):
    status: ParseStatus
    reason: str = ""  # an errors.Reason value when status != "ok"
    page_count: int = 0
    document: ParsedDocument | None = None
