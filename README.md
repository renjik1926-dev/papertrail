# PaperTrail

Upload a confusing letter (PDF) and get a checklist of what it asks you to do — actions,
documents to send, deadlines, amounts and contacts — where **every item links to the exact
passage it came from**. Anything that can't be backed by a quote from the letter is flagged
instead of guessed.

> **Status: first draft (v0.1.0 in progress).** The pipeline, verifier, local web app, CLI and
> tests work. The saved AI answers used by the tests and the demo are **real Claude Haiku 5.5
> responses**, recorded once for six synthetic letters (see [Accuracy](#accuracy)). Built from
> [BUILD_PLAN.md](BUILD_PLAN.md).

## Why

Tax notices, insurance statements and university letters bury the two or three things you
actually have to do. Tools that summarize them with AI can sound sure while being wrong.
PaperTrail shows you the source of every item, so you can check it in seconds.

## How it works

```
PDF -> parse (pdfplumber: words, lines, blocks with positions)
    -> extract (ONE call to Claude Haiku 5.5, structured JSON with quotes and block IDs)
    -> verify (plain code: is the quote really in the letter? is the date/amount in that passage?)
    -> locate (quote -> highlight rectangles on the page)
    -> store (SQLite) -> web UI: checklist next to the PDF with highlights
```

**The AI suggests, code verifies.** Claude only proposes items and copies dates and amounts
exactly as written. Everything else is ordinary, tested code: matching each quote against
the letter, date math ("within 60 days of the date of this notice"), conflicting amounts,
"this is not a bill" wording, text in the letter addressed to an AI, and so on (checks
V1–V12 in the plan). Each item ends up **verified**, **needs review** (with the reasons
shown) or **rejected** (hidden from the checklist).

## AI use

- **At runtime**, PaperTrail makes **one call per document** to Anthropic's Claude API
  (model `claude-haiku-5-5` by default, `PAPERTRAIL_MODEL` to change it) through
  `client.messages.parse` with a strict, all-required output schema and an explicit `effort`.
- **What is sent:** the letter's text (split into numbered blocks) and a fixed system prompt.
  Not the PDF file, not your filename, nothing else. It is sent under your own API key; see
  Anthropic's [privacy policy](https://www.anthropic.com/legal/privacy) and
  [commercial terms](https://www.anthropic.com/legal/commercial-terms).
- **What the AI does not decide:** whether an item is shown, any date calculation, and any
  amount parsing. Those are code.
- **Cost:** about $0.001–0.003 per typical letter at Haiku 5.5 prices ($0.10 / $0.50 per
  million input / output tokens for prompts up to 100K tokens; check
  [Anthropic's pricing](https://platform.claude.com/docs/en/about-claude/pricing) before relying on it). A daily cap
  (`PAPERTRAIL_MAX_DOCS_PER_DAY`, default 50) is a backstop against bugs and retry loops.
- **Tests and CI never call the API.** They replay saved responses keyed by a hash of the
  model, effort, prompt, schema and document text.

## Accuracy

The six saved answers in `eval/recorded/` are real responses from `claude-haiku-5-5` (prompt
`extract_v1`, effort `medium`), recorded on 2026-10-19 for six **synthetic** letters. Recording
all six cost under one cent. Tests and the demo replay these answers, so they run without a key
or network.

**No accuracy claim yet.** Four letters are the *dev* split, used while building, so their
numbers aren't a fair test. The two held-out *test* letters will be scored once, after the
prompt is frozen, and published here (BUILD_PLAN §12). Six letters is also far too few to say
much: the plan's target is 30–40.

Contributors without a key can still run everything: `eval/write_placeholder_recordings.py`
writes hand-written stand-ins (marked `"source": "hand-written placeholder"`), and the eval report
says when any are in use.

## Try it (from source)

You need [uv](https://docs.astral.sh/uv/) and Node.js 22+. No API key is needed to try it
with saved responses.

```bash
git clone https://github.com/renjik1926-dev/papertrail
cd papertrail

# Backend
cd backend && uv sync && cd ..
PAPERTRAIL_PROVIDER=replay uv run --project backend papertrail doctor
PAPERTRAIL_PROVIDER=replay uv run --project backend papertrail run eval/docs/tax_notice_01.pdf

# Web app (two terminals)
PAPERTRAIL_PROVIDER=replay PAPERTRAIL_DEV=1 uv run --project backend papertrail serve
cd frontend && npm ci && npm run dev      # then open http://localhost:5173
```

With `PAPERTRAIL_PROVIDER=replay`, only the letters in `eval/docs/` have saved responses.
`PAPERTRAIL_PROVIDER=fake` works on any PDF with a crude rule-based stand-in (useful for
trying the UI). To use Claude, put your key in a `.env` file (see `.env.example`), in this
folder or in the data folder that `papertrail doctor` prints, and leave the provider at its
default `claude`. Run `papertrail smoke` once to check the key (a fraction of a cent).

A one-command install from a release wheel (`uv tool install ...`) comes with v0.1.0.

## Privacy

- Letters and results are stored only on your computer, in the data folder shown by
  `papertrail doctor`. The server listens on `127.0.0.1` only.
- The letter's text goes to Anthropic's API for the extraction call; nothing else leaves
  your computer. No analytics, no telemetry, no crash reporting.
- Deleting a letter removes the file, the saved AI response and everything derived from it.
  To delete everything: uninstall PaperTrail and delete the data folder.
- `papertrail backup` / `papertrail restore` move your data between machines.

## Commands

`parse`, `extract`, `run`, `eval`, `record`, `serve`, `doctor`, `smoke`, `backup`,
`restore`, `export-demo`, `openapi` — run `papertrail --help` or see BUILD_PLAN §8.12.

## Development

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npx eslint . && npx tsc --noEmit && npx vitest run && npm run build && npx playwright test
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for re-recording responses, regenerating fixtures and
the API types.

## Project layout

```
backend/    Python package `papertrail`: parse/, extract/, verify/, db/, api.py, cli.py; tests/
frontend/   React + TypeScript (Vite), pdf.js viewer; tests/unit (Vitest), tests/e2e (Playwright)
eval/       synthetic letters, answer keys, saved responses, labeling rules
docs/       decision records
```

## Limitations

English, digital (non-scanned) PDFs only, and more — see [LIMITATIONS.md](LIMITATIONS.md).

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License and disclaimer

MIT — see [LICENSE](LICENSE). PaperTrail lists what a letter says. It is not legal, medical
or financial advice; check each item against the highlighted passage in the original letter.
