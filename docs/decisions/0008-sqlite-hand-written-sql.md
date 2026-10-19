# 0008. SQLite with hand-written SQL and numbered migrations

Status: Accepted

## Decision

One database file; all SQL in `db/repo.py`; migrations tracked with `PRAGMA user_version`, backed up before migrating.

## Why

No server to run, and the schema stays visible.
