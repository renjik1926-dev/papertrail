# 0001. One AI call per document

Status: Accepted

## Decision

Each letter is read with exactly one Claude call (Haiku 5.5 by default).

## Why

Cheap (fractions of a cent per letter), fast, and easy to test with saved responses. A multi-step agent would cost more and be harder to test.
