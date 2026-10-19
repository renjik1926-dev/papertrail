# 0003. Flat, all-required output schema

Status: Accepted

## Decision

Separate arrays per item kind; every field required; no nullable fields (empty string or 0 means "not applicable").

## Why

Structured outputs limit optional and union-type parameters per request. All-required avoids both limits. A contract test checks `additionalProperties: false` everywhere.
