# Contributing

## Setup

```bash
cd backend && uv sync          # Python 3.12+, dependencies from uv.lock
cd frontend && npm ci          # Node 22+
```

Run the backend with `PAPERTRAIL_PROVIDER=replay PAPERTRAIL_DEV=1 uv run papertrail serve`
and the frontend with `npm run dev` (Vite proxies `/api` to the backend).

## Checks (the same as CI)

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest

cd frontend
npx eslint . && npx prettier --check . && npx tsc --noEmit && npx vitest run && npm run build
npx playwright install chromium && npx playwright test   # end-to-end, uses the Replay provider
```

## Saved responses (recordings)

Tests, CI and the demo replay responses from `eval/recorded/`, keyed by a hash of the model,
effort, prompt file, schema and the exact document text. Changing any of them changes the
hash, and replay fails with "missing recording".

- With an API key: `uv run --project backend papertrail record --split dev` (prints the
  estimated cost and asks first). Commit the new files and re-run `papertrail eval`.
- Without a key: `uv run --project backend python eval/write_placeholder_recordings.py`
  rewrites the hand-written placeholders for the new hash. Never present results built on
  placeholders as model accuracy.

## Fixtures and golden files

Fixture PDFs are generated once and committed:
`uv run --project backend --group fixtures python eval/make_fixtures.py` (needs Playwright's
Chromium). After regenerating, update the parser golden files with
`UPDATE_GOLDEN=1 uv run pytest tests/unit/test_parse.py` and re-record.

Only synthetic or public documents go in the repository — never a real letter.

## API types

After changing an endpoint or model: `uv run --project backend papertrail openapi` then
`npm run gen:api` in `frontend/`. CI fails if either is out of date.

## Pull requests

Short branches, conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`), and the
checklist in the PR template.
