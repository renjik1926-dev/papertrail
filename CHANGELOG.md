# Changelog

All notable changes are listed here. Versions follow [SemVer](https://semver.org/).

## [Unreleased]

First draft built from BUILD_PLAN.md v1.4.

### Added
- PDF parsing into blocks with word positions; rotated and cropped pages line up with the viewer.
- One Claude call per document via `messages.parse` (Haiku 5.5 by default, explicit effort,
  refusal handling, optional workspace header); Replay and Fake providers.
- Plain-code verifier (V1–V12), highlight location, deadline-to-action attachment.
- SQLite storage with migrations, background worker with a parse timeout and a daily cap.
- Local web app: checklist next to the PDF with highlights, reviews, calendar export, print page.
- CLI: parse, extract, run, eval, record, serve, doctor, smoke, backup, restore, export-demo, openapi.
- Evaluation harness with six synthetic letters and answer keys.
- CI, Pages and release workflows.

### Changed
- The six saved model responses in `eval/recorded/` are now real `claude-haiku-5-5` answers
  (prompt `extract_v1`, effort `medium`, recorded 2026-10-19), replacing the hand-written
  placeholders. The placeholder writer remains for contributors without a key.

### Fixed
- The startup sweep no longer deletes files less than an hour old. Before, starting the server
  while another PaperTrail process was mid-upload or mid-backup could delete that process's PDF or
  backup snapshot.

### Known gaps
- No accuracy results yet: the held-out test split hasn't been scored, and six letters is far
  below the planned 30–40.
