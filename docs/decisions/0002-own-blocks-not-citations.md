# 0002. Send our own blocks with IDs; don't use built-in citations

Status: Accepted

## Decision

The prompt contains the letter as numbered blocks (`[p2:b14] ...`); the model cites block IDs and copies quotes.

## Why

Claude's built-in PDF citations point to pages only (no position) and can't be combined with structured outputs in one request.
