# 0011. `effort` together with `messages.parse`

Status: Accepted (week-2 spike)

## Decision

Call `client.messages.parse(output_format=Extraction, output_config={"effort": ...})`. The SDK (anthropic 1.15) merges both into one `output_config` and applies its schema transformation. Because `parse()` raises when the text isn't valid JSON (a refusal or a truncated answer), the provider also keeps the raw response body from an HTTP response hook, so it can still read `stop_reason` and save the response.

## Why

Confirms the plan's preferred path (open question Q3). The SDK contract tests (`tests/unit/test_claude_contract.py`) assert the request shape on every run, so an SDK upgrade that changes it fails CI.
