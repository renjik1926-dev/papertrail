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

### Known gaps
- Saved model responses are hand-written placeholders; no accuracy results yet.
