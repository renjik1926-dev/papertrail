# 0010. Bind to 127.0.0.1; no accounts

Status: Accepted

## Decision

The server listens on 127.0.0.1 only, with Host, custom-header and Origin checks instead of authentication.

## Why

It's a single-user local app; binding locally is the security boundary, and the checks stop websites in the browser from using it.
