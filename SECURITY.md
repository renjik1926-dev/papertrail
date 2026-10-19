# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub's private vulnerability reporting
(Security tab -> "Report a vulnerability"), not in a public issue. Include steps to reproduce
with a synthetic document — never a real letter.

## Supported versions

Only the latest release gets security fixes.

## Design notes

PaperTrail is a local, single-user app. The server binds to `127.0.0.1`, checks the `Host`
header, requires an `X-PaperTrail` header and a same-origin `Origin` on state-changing
requests, never enables CORS, and sends a strict Content-Security-Policy. See BUILD_PLAN §9
and §14 for the threat model.
