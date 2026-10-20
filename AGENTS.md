# AGENTS.md

Notes for AI coding tools working in this repository. People should start with the
[README](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## AI tools are not contributors

This file gives AI tools the context to work here. It doesn't make them contributors. The project
is written and maintained by renjik1926-dev, and no AI tool is credited for the work.

- Don't add `Co-Authored-By:` trailers for an AI, "Generated with …" lines, or any other AI credit
  to commits, pull requests, code comments, the changelog or release notes.
- Commit with the git identity that's already configured. Don't change `user.name` or
  `user.email`.
- This rule is about credit for the work, not about the product. The README's "AI use" section
  describes PaperTrail's runtime call to Claude, and it stays.

## What this is

PaperTrail turns a PDF letter into a checklist of actions, documents, deadlines and amounts. Each
item links to the passage it came from. The AI suggests and plain code verifies: one Claude call
per document proposes items, and the verifier (checks V1–V12) decides what is shown.

- [BUILD_PLAN.md](BUILD_PLAN.md) is the spec. Build on it rather than redesigning.
- [docs/decisions/](docs/decisions/) records why things are the way they are. Read the relevant
  record before changing a decision, and add a new record when you change one.

## Layout

```
backend/    Python 3.12 package `papertrail` (uv, FastAPI): parse/, extract/, verify/, db/, api.py, cli.py; tests/
frontend/   React + TypeScript (Vite), pdf.js viewer; tests/unit (Vitest), tests/e2e (Playwright)
eval/       synthetic letters, answer keys, saved AI responses, labeling rules
docs/       decision records
```

## Commands

```bash
# Setup
cd backend && uv sync
cd frontend && npm ci

# Checks (the same as CI)
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npx eslint . && npx prettier --check . && npx tsc --noEmit && npx vitest run && npm run build
cd frontend && npx playwright test

# Run locally without an API key
PAPERTRAIL_PROVIDER=replay PAPERTRAIL_DEV=1 uv run --project backend papertrail serve
cd frontend && npm run dev
```

On Windows, Prettier line-ending warnings come from `core.autocrlf=true`, not from the code.

## Rules

- **Code decides, not the model.** Date math, amount parsing and whether an item is shown belong in
  the verifier, not in the prompt (decisions 0004 and 0005).
- **No paid API calls without asking.** Tests and CI replay saved responses and never call the
  API. `papertrail record` and `papertrail smoke` spend real money, so ask the owner before
  running either one.
- **Keep the model.** The default is `claude-haiku-5-5`, chosen for cost. Don't switch to a larger
  model.
- **Recordings follow the inputs.** Replay is keyed by a hash of the model, effort, prompt, schema
  and document text. If you change any of them, refresh the recordings (see CONTRIBUTING.md).
  Never present results built on hand-written placeholders as model accuracy.
- **API types stay in sync.** After changing an endpoint or model, run
  `uv run --project backend papertrail openapi` and then `npm run gen:api` in `frontend/`.
- **No secrets or real letters.** `.env` is git-ignored and must stay that way. PDFs go only in
  `eval/docs/` or `backend/tests/fixtures/`, and only synthetic or public documents.
- **Branches and pull requests.** `main` is protected. Work on a short branch, open a pull request,
  and let `backend (ubuntu-24.04)` and `frontend` pass. Use conventional commit messages
  (`feat:`, `fix:`, `test:`, `docs:`) and fill in the PR template's checklist.
- **Plain, editorial UI.** No gradients, glows, hover-lift cards or fade-in animations.
