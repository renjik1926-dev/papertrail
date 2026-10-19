# 0009. Provider interface: Claude, Replay, Fake

Status: Accepted

## Decision

The pipeline talks to a `Provider`. Replay returns saved responses keyed by request hash; Fake is a deterministic test double.

## Why

CI, the demo and most tests run without an API key or network.
