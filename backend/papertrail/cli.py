"""The `papertrail` command (BUILD_PLAN §8.12)."""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import socket
import sqlite3
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from papertrail import __version__
from papertrail.clock import RealClock, local_day_start_utc, utc_iso
from papertrail.config import EFFORT_ORDER, MissingApiKeyError, Settings, load_settings
from papertrail.db import repo
from papertrail.db.connection import (
    MIN_SQLITE,
    SchemaTooNewError,
    connect,
    latest_version,
    migrate,
    schema_version,
    transaction,
)
from papertrail.errors import WORKSPACE_HINT, Reason, describe
from papertrail.extract.providers import make_provider
from papertrail.extract.providers.base import Provider, ProviderError, request_hash
from papertrail.extract.providers.claude import ClaudeProvider
from papertrail.extract.providers.replay import recording_path, write_recording
from papertrail.extract.render import PROMPT_VERSION, load_prompt
from papertrail.extract.runner import run_extraction
from papertrail.logging_setup import configure_logging
from papertrail.parse import parse_pdf
from papertrail.pipeline import PipelineResult, file_sha256, render_document, run_in_memory
from papertrail.pricing import estimate_cost_usd
from papertrail.verify.models import ItemKind, VerifiedItem
from papertrail.verify.status import reasons

app = typer.Typer(
    name="papertrail",
    help="Turn a letter (PDF) into a checklist where every item cites the passage it came from.",
    no_args_is_help=True,
    add_completion=False,
)

EffortOption = Annotated[
    str | None, typer.Option("--effort", help="low, medium or high (default: PAPERTRAIL_EFFORT)")
]
FileArgument = Annotated[
    Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="A PDF file")
]


def _settings(**overrides: Any) -> Settings:
    return load_settings(**overrides)


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


def _effort(settings: Settings, effort: str | None) -> str:
    value = effort or settings.effort
    if value not in EFFORT_ORDER:
        raise _fail(f"Unknown effort {value!r}; use low, medium or high.", 2)
    return value


def _provider(settings: Settings) -> Provider:
    try:
        return make_provider(settings)
    except MissingApiKeyError as error:
        raise _fail(str(error)) from None


def _check_daily_cap(settings: Settings) -> None:
    """The spend guard also applies to `run` and `extract` with the Claude provider."""
    if settings.provider != "claude" or not settings.db_path.exists():
        return
    conn = connect(settings.db_path)
    try:
        started = repo.count_runs_since(
            conn, provider="claude", since=local_day_start_utc(RealClock())
        )
    except sqlite3.Error:
        return
    finally:
        conn.close()
    if started >= settings.max_docs_per_day:
        raise _fail(describe(Reason.daily_limit).message)


def find_repo_root() -> Path:
    for folder in (Path.cwd(), *Path.cwd().parents):
        if (
            (folder / "eval").is_dir()
            and (folder / "backend").is_dir()
            and (folder / "frontend").is_dir()
        ):
            return folder
    raise _fail("Run this command inside the PaperTrail repository (it needs eval/ and frontend/).")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"papertrail {__version__}")
        raise typer.Exit


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    """PaperTrail command line."""


# parse / extract / run ------------------------------------------------------------------


@app.command()
def parse(file: FileArgument, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Print blocks with IDs and positions (debugging the parser)."""
    settings = _settings()
    outcome = parse_pdf(file, max_pages=settings.max_pages)
    if as_json:
        typer.echo(
            outcome.model_dump_json(
                indent=2, exclude={"document": {"blocks": {"__all__": {"words"}}}}
            )
        )
        return
    if outcome.status != "ok" or outcome.document is None:
        info = describe(outcome.reason)
        raise _fail(f"{outcome.status}: {outcome.reason} - {info.message}")
    for page in outcome.document.pages:
        typer.echo(
            f"page {page.page_no}: {page.width:.0f} x {page.height:.0f} pt{' (scanned)' if page.is_scanned else ''}"
        )
    for block in outcome.document.blocks:
        box = f"({block.x0:.1f}, {block.top:.1f}, {block.x1:.1f}, {block.bottom:.1f})"
        typer.echo(f"[{block.id}] {box} {block.text.replace(chr(10), ' / ')}")


@app.command()
def extract(file: FileArgument, effort: EffortOption = None) -> None:
    """Parse and call the provider; print the raw Extraction JSON."""
    settings = _settings()
    chosen = _effort(settings, effort)
    _check_daily_cap(settings)
    parsed = parse_pdf(file, max_pages=settings.max_pages)
    if parsed.status != "ok" or parsed.document is None:
        raise _fail(f"{parsed.status}: {describe(parsed.reason).message}")
    outcome = run_extraction(
        _provider(settings),
        render_document(parsed.document),
        prompt_version=PROMPT_VERSION,
        effort=chosen,
    )
    if not outcome.ok or outcome.result is None or outcome.result.extraction is None:
        reason = outcome.reason.value if outcome.reason else "unknown"
        raise _fail(f"failed: {reason} - {outcome.message or describe(reason).message}")
    typer.echo(outcome.result.extraction.model_dump_json(indent=2))


def _format_item(item: VerifiedItem) -> str:
    mark = {"verified": "[ok]", "needs_review": "[review]", "rejected": "[rejected]"}[
        item.status.value
    ]
    extra = ""
    if item.due_date:
        extra += f" - due {item.due_date}"
    if item.due_calc:
        extra += f" ({item.due_calc})"
    if item.amount_cents is not None:
        extra += f" - ${item.amount_cents / 100:,.2f} ({item.amount_role})"
    page = f" p{item.rects[0].page_no}" if item.rects else ""
    lines = [f"  {mark} {item.text}{extra}{page}"]
    lines += [f"      - {reason}" for reason in reasons(item.checks)]
    return "\n".join(lines)


@app.command()
def run(
    file: FileArgument,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print JSON instead of a checklist")
    ] = False,
    save: Annotated[
        bool, typer.Option("--save", help="Also store the result in the database")
    ] = False,
    effort: EffortOption = None,
) -> None:
    """Full pipeline; print the checklist with statuses and reasons."""
    settings = _settings()
    chosen = _effort(settings, effort)
    _check_daily_cap(settings)
    provider = _provider(settings)
    result = run_in_memory(file, provider=provider, effort=chosen, max_pages=settings.max_pages)
    if result.run is None or result.run.verified is None:
        reason = result.reason or "unknown"
        message = result.run.extraction.message if result.run else ""
        raise _fail(f"{reason}: {message or describe(reason).message}")
    verified = result.run.verified
    if save:
        document_id = _save_result(settings, file, result, provider)
        typer.echo(f"saved as document {document_id}", err=True)
    if as_json:
        typer.echo(verified.model_dump_json(indent=2))
        return
    typer.echo(
        f"{file.name} - {verified.document_type}, dated {verified.document_date or 'unknown'}"
    )
    for kind in ItemKind:
        group = [i for i in verified.items if i.kind == kind]
        if group:
            typer.echo(f"\n{kind.value}s:")
            for item in group:
                typer.echo(_format_item(item))
    counts = {
        s: sum(1 for i in verified.items if i.status.value == s)
        for s in ("verified", "needs_review", "rejected")
    }
    typer.echo(
        f"\n{counts['verified']} verified, {counts['needs_review']} need review, {counts['rejected']} rejected"
    )


def _save_result(settings: Settings, file: Path, result: PipelineResult, provider: Provider) -> str:
    """Store an in-memory result as a document with one run (no second API call)."""
    from papertrail.ingest import ingest_stream  # noqa: PLC0415
    from papertrail.store import new_id, save_raw_response, store_success  # noqa: PLC0415

    assert result.run is not None and result.run.verified is not None
    assert result.parse.document is not None
    extraction = result.run.extraction
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    try:
        migrate(conn, settings.db_path)
        stamp = utc_iso(RealClock().now())
        with file.open("rb") as handle:
            document = ingest_stream(conn, settings, handle, file.name, now=stamp).document
        run_id = new_id()
        raw_path = (
            save_raw_response(settings, run_id, extraction.result.raw)
            if extraction.result
            else None
        )
        with transaction(conn, immediate=True):
            repo.replace_parsed(conn, document["id"], result.parse.document, stamp)
            repo.insert_run(
                conn,
                id=run_id,
                document_id=document["id"],
                provider=provider.name,
                model=provider.model,
                prompt_version=PROMPT_VERSION,
                effort=extraction.effort,
                request_hash=extraction.request_hash,
                started_at=stamp,
            )
            repo.finish_run(
                conn,
                run_id,
                status="succeeded",
                effort=extraction.effort,
                request_hash=extraction.request_hash,
                model=extraction.result.model if extraction.result else provider.model,
                stop_reason=extraction.result.stop_reason if extraction.result else None,
                error=None,
                input_tokens=extraction.input_tokens,
                output_tokens=extraction.output_tokens,
                duration_ms=0,
                raw_response_path=str(raw_path) if raw_path else None,
                finished_at=stamp,
            )
            job = repo.active_job(conn, document["id"])
            if job is not None:
                repo.finish_job(conn, job["id"], status="done", last_error=None, now=stamp)
        store_success(
            conn, document_id=document["id"], run_id=run_id, verified=result.run.verified, now=stamp
        )
        return str(document["id"])
    finally:
        conn.close()


# eval / record ---------------------------------------------------------------------------


def _split_docs(root: Path, split: str) -> list[Path]:
    splits = yaml.safe_load((root / "eval" / "splits.yaml").read_text(encoding="utf-8")) or {}
    names = splits.get(split)
    if not isinstance(names, list):
        raise _fail(f"eval/splits.yaml has no '{split}' list.")
    docs = [root / "eval" / "docs" / f"{name}.pdf" for name in names]
    missing = [d.name for d in docs if not d.is_file()]
    if missing:
        raise _fail(f"Missing eval documents: {', '.join(missing)}")
    return docs


@app.command("eval")
def eval_command(
    split: Annotated[str, typer.Option("--split", help="dev or test")] = "dev",
    provider_name: Annotated[str, typer.Option("--provider", help="replay or claude")] = "replay",
    effort: EffortOption = None,
    gate: Annotated[
        bool, typer.Option("--gate", help="Fail if metrics fall below eval/baseline.json")
    ] = False,
    out_dir: Annotated[
        Path | None, typer.Option("--out", help="Report folder (default eval/reports)")
    ] = None,
) -> None:
    """Run the evaluation (BUILD_PLAN §12) and write a markdown + JSON report."""
    from papertrail.evaluation import (  # noqa: PLC0415
        AnswerKey,
        evaluate_document,
        gate_failures,
        render_markdown,
        summarize,
        write_report,
    )

    if provider_name not in ("replay", "claude"):
        raise _fail("--provider must be replay or claude", 2)
    root = find_repo_root()
    settings = _settings(PAPERTRAIL_PROVIDER=provider_name)
    chosen = _effort(settings, effort)
    provider = _provider(settings)
    results = []
    for pdf in _split_docs(root, split):
        key = AnswerKey.load(root / "eval" / "labels" / f"{pdf.stem}.yaml")
        try:
            results.append(
                evaluate_document(
                    pdf, key, provider=provider, effort=chosen, max_pages=settings.max_pages
                )
            )
        except ProviderError as error:
            raise _fail(f"{pdf.name}: {error.message}") from None
    summary = summarize(results, model=settings.model)
    notes = [
        f"Split: {split}. Provider: {provider_name}. Model: {settings.model}. Effort: {chosen}. Prompt: {PROMPT_VERSION}.",
    ]
    recordings = root / "eval" / "recorded"
    if provider_name == "replay" and any(
        json.loads(p.read_text(encoding="utf-8")).get("source") != "claude"
        for p in recordings.glob("*.json")
    ):
        notes.append(
            "Some recordings are hand-written placeholders, not real model output. These numbers test "
            "the harness and the verifier, not Claude's accuracy."
        )
    title = f"PaperTrail eval - {split} - {date.today().isoformat()}"
    markdown = render_markdown(summary, results, title=title, notes=notes)
    stem = f"{date.today().isoformat()}-{PROMPT_VERSION}-{chosen}-{split}"
    md_path, _ = write_report(out_dir or root / "eval" / "reports", stem, summary, markdown)
    typer.echo(markdown)
    typer.echo(f"\nreport: {md_path}")
    if gate:
        baseline_path = root / "eval" / "baseline.json"
        if not baseline_path.is_file():
            raise _fail("--gate needs eval/baseline.json")
        problems = gate_failures(summary, json.loads(baseline_path.read_text(encoding="utf-8")))
        if problems:
            raise _fail("Eval regressed: " + "; ".join(problems))


@app.command()
def record(
    split: Annotated[str, typer.Option("--split")] = "dev",
    effort: EffortOption = None,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt")] = False,
) -> None:
    """Call Claude on eval documents and save responses to eval/recorded/ (costs money)."""
    root = find_repo_root()
    settings = _settings(PAPERTRAIL_PROVIDER="claude")
    chosen = _effort(settings, effort)
    try:
        key = settings.require_api_key()
    except MissingApiKeyError as error:
        raise _fail(str(error)) from None
    provider = ClaudeProvider(
        api_key=key.get_secret_value(),
        model=settings.model,
        workspace_id=settings.anthropic_workspace_id,
        timeout_s=settings.api_timeout_s,
    )
    recordings = root / "eval" / "recorded"
    prompt_text = load_prompt(PROMPT_VERSION)
    todo: list[tuple[Path, str, str]] = []
    for pdf in _split_docs(root, split):
        parsed = parse_pdf(pdf, max_pages=settings.max_pages)
        if parsed.status != "ok" or parsed.document is None:
            typer.echo(f"skip {pdf.name}: {parsed.reason}")
            continue
        rendered = render_document(parsed.document)
        digest = request_hash(
            model=settings.model, effort=chosen, prompt_text=prompt_text, rendered_document=rendered
        )
        existing = recording_path(recordings, digest)
        if (
            existing.is_file()
            and json.loads(existing.read_text(encoding="utf-8")).get("source") == "claude"
        ):
            typer.echo(f"skip {pdf.name}: already recorded")
            continue
        todo.append((pdf, rendered, digest))
    if not todo:
        typer.echo("Nothing to record.")
        return
    try:
        tokens = sum(
            provider.count_input_tokens(r, prompt_version=PROMPT_VERSION) for _, r, _ in todo
        )
    except Exception:
        raise _fail("Couldn't count tokens; check your API key and connection.") from None
    # Output is unknown before the call; assume up to 5,000 output tokens per letter.
    estimate = estimate_cost_usd(settings.model, tokens, 5000 * len(todo))
    cost = f"about ${estimate:.4f}" if estimate is not None else "unknown"
    typer.echo(
        f"{len(todo)} document(s), {tokens} input tokens, estimated cost {cost} ({settings.model}, effort {chosen})."
    )
    if not yes and not typer.confirm("Send these documents to the Anthropic API?"):
        raise typer.Exit(1)

    def one(task: tuple[Path, str, str]) -> str:
        pdf, rendered, digest = task
        try:
            result = provider.extract(rendered, prompt_version=PROMPT_VERSION, effort=chosen)
        except ProviderError as error:
            return f"{pdf.name}: failed ({error.reason.value}) {error.message}"
        write_recording(
            recordings,
            digest=digest,
            response=result.raw,
            source="claude",
            document_name=pdf.name,
            document_sha256=file_sha256(pdf),
            model=settings.model,
            effort=chosen,
            prompt_version=PROMPT_VERSION,
            recorded_at=utc_iso(RealClock().now()),
        )
        return f"{pdf.name}: recorded ({result.stop_reason}, {result.input_tokens}+{result.output_tokens} tokens)"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:  # at most 2 at a time
        for line in pool.map(one, todo):
            typer.echo(line)


# serve / doctor / smoke ------------------------------------------------------------------


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@app.command()
def serve(
    port: Annotated[int | None, typer.Option("--port")] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the app in your browser")
    ] = False,
) -> None:
    """Run migrations and start the app on 127.0.0.1."""
    import uvicorn  # noqa: PLC0415

    from papertrail.api import create_app  # noqa: PLC0415

    settings = _settings()
    if port is not None:
        settings = settings.model_copy(update={"port": port})
    if settings.provider == "claude" and not settings.has_api_key:
        raise _fail(
            str(
                MissingApiKeyError(
                    f"ANTHROPIC_API_KEY is not set (data folder: {settings.data_dir})."
                )
            )
        )
    if not _port_free(settings.port):
        raise _fail(
            f"Port {settings.port} is already in use. Try `papertrail serve --port {settings.port + 1}`."
        )
    settings.ensure_dirs()
    configure_logging(settings.logs_dir)
    try:
        conn = connect(settings.db_path)
        report = migrate(conn, settings.db_path)
        conn.close()
    except SchemaTooNewError as error:
        raise _fail(str(error)) from None
    if report.backup_path:
        typer.echo(
            f"Database upgraded to version {report.to_version}; backup at {report.backup_path}"
        )
    url = f"http://127.0.0.1:{settings.port}/"
    typer.echo(f"PaperTrail is running at {url} (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_level="warning")


def _disk_usage(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


@app.command()
def doctor() -> None:
    """Check the setup. Exit code 0 only if everything needed to run is OK."""
    settings = _settings()
    problems: list[str] = []
    rows: list[tuple[str, str]] = [
        ("App version", __version__),
        ("Data folder", str(settings.data_dir)),
    ]

    if settings.db_path.exists():
        try:
            conn = connect(settings.db_path)
            current = schema_version(conn)
            conn.close()
            latest = latest_version()
            rows.append(("Database schema", f"{current} (this app: {latest})"))
            if current > latest:
                problems.append("The database is newer than this app; upgrade PaperTrail.")
        except sqlite3.Error as error:
            rows.append(("Database schema", "unreadable"))
            problems.append(f"Database can't be opened: {type(error).__name__}")
    else:
        rows.append(("Database schema", f"not created yet (this app: {latest_version()})"))

    sqlite_ok = sqlite3.sqlite_version_info >= MIN_SQLITE
    rows.append(
        ("SQLite version", f"{sqlite3.sqlite_version}{'' if sqlite_ok else ' (needs 3.35+)'}")
    )
    if not sqlite_ok:
        problems.append("SQLite is too old.")

    rows += [
        ("Provider", settings.provider),
        ("Model", settings.model),
        ("Effort", settings.effort),
    ]
    rows.append(("API key", "set" if settings.has_api_key else "not set"))
    rows.append(("Workspace ID", "set" if settings.anthropic_workspace_id else "not set"))
    if settings.provider == "claude" and not settings.has_api_key:
        problems.append("PAPERTRAIL_PROVIDER is claude but ANTHROPIC_API_KEY is not set.")
    if settings.provider == "replay":
        recordings = settings.resolved_recordings_dir()
        rows.append(("Recordings folder", str(recordings)))
        if not recordings.is_dir():
            problems.append(f"Recordings folder not found: {recordings}")

    frontend = (settings.static_dir / "index.html").is_file()
    rows.append(
        ("Built frontend", "present" if frontend else "not present (use the Vite dev server)")
    )
    rows.append(("Daily document cap", str(settings.max_docs_per_day)))
    rows.append(("Data folder size", f"{_disk_usage(settings.data_dir) / 1_048_576:.1f} MB"))

    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        typer.echo(f"{label.ljust(width)}  {value}")
    if problems:
        typer.echo("")
        for problem in problems:
            typer.echo(f"problem: {problem}")
        raise typer.Exit(1)
    typer.echo("\nAll good.")


@app.command()
def smoke(yes: Annotated[bool, typer.Option("--yes")] = False) -> None:
    """Send one bundled synthetic letter to the real API (a fraction of a cent). Never run in CI."""
    from importlib.resources import files  # noqa: PLC0415

    settings = _settings(PAPERTRAIL_PROVIDER="claude")
    try:
        key = settings.require_api_key()
    except MissingApiKeyError as error:
        raise _fail(str(error)) from None
    if not yes and not typer.confirm(f"Send a short synthetic letter to {settings.model}?"):
        raise typer.Exit(1)
    letter = (files("papertrail.extract") / "smoke_letter.txt").read_text(encoding="utf-8")
    provider = ClaudeProvider(
        api_key=key.get_secret_value(),
        model=settings.model,
        workspace_id=settings.anthropic_workspace_id,
        timeout_s=settings.api_timeout_s,
    )
    outcome = run_extraction(
        provider, letter, prompt_version=PROMPT_VERSION, effort=settings.effort
    )
    if not outcome.ok or outcome.result is None or outcome.result.extraction is None:
        reason = outcome.reason.value if outcome.reason else "unknown"
        message = outcome.message or describe(reason).message
        if WORKSPACE_HINT in message:
            message = WORKSPACE_HINT
        raise _fail(f"Smoke test failed: {reason} - {message}")
    extraction = outcome.result.extraction
    count = sum(
        len(group)
        for group in (
            extraction.actions,
            extraction.documents,
            extraction.deadlines,
            extraction.amounts,
            extraction.contacts,
        )
    )
    cost = estimate_cost_usd(settings.model, outcome.input_tokens, outcome.output_tokens)
    typer.echo(
        f"OK: {settings.model} answered ({outcome.result.stop_reason}), {count} items, "
        f"{outcome.input_tokens}+{outcome.output_tokens} tokens"
        + (f", about ${cost:.5f}" if cost is not None else "")
    )


# backup / restore / export-demo / openapi ------------------------------------------------


@app.command()
def backup(
    path: Annotated[Path | None, typer.Argument(help="Where to write the zip")] = None,
) -> None:
    """Write a zip of the database and all stored files."""
    from papertrail.backup import create_backup  # noqa: PLC0415

    settings = _settings()
    stamp = utc_iso(RealClock().now())
    target = path or Path.cwd() / f"papertrail-backup-{stamp[:10]}.zip"
    create_backup(settings, target, created_at=stamp)
    typer.echo(f"Backup written to {target}")


@app.command()
def restore(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Restore a backup into an empty data folder."""
    from papertrail.backup import RestoreError, restore_backup  # noqa: PLC0415

    settings = _settings()
    try:
        version = restore_backup(settings, path)
    except (RestoreError, SchemaTooNewError) as error:
        raise _fail(str(error)) from None
    typer.echo(f"Restored schema version {version} into {settings.data_dir}")


@app.command("export-demo")
def export_demo_command(
    out: Annotated[Path | None, typer.Option("--out", help="Default: frontend/public/demo")] = None,
) -> None:
    """Write the static demo data (Replay provider, no API calls)."""
    from papertrail.export.demo import export_demo  # noqa: PLC0415

    root = find_repo_root()
    splits = yaml.safe_load((root / "eval" / "splits.yaml").read_text(encoding="utf-8")) or {}
    docs = [root / "eval" / "docs" / f"{name}.pdf" for name in splits.get("demo", [])]
    if not docs:
        raise _fail("eval/splits.yaml has no 'demo' list.")
    target = out or root / "frontend" / "public" / "demo"
    if target.is_dir():
        shutil.rmtree(target)
    try:
        index = export_demo(
            documents=docs,
            recordings_dir=root / "eval" / "recorded",
            out_dir=target,
            base_settings=_settings(),
        )
    except RuntimeError as error:
        raise _fail(str(error)) from None
    typer.echo(f"Wrote {len(index)} demo documents to {target}")


def openapi_schema() -> dict[str, Any]:
    from papertrail.api import create_app  # noqa: PLC0415

    settings = Settings(PAPERTRAIL_PROVIDER="fake", PAPERTRAIL_DATA_DIR=Path("unused"))
    schema: dict[str, Any] = create_app(settings, start_worker=False).openapi()
    return schema


@app.command()
def openapi(
    out: Annotated[
        Path | None, typer.Option("--out", help="Default: frontend/src/api/openapi.json")
    ] = None,
) -> None:
    """Write the API's OpenAPI schema (the source of the frontend's TypeScript types)."""
    target = out or find_repo_root() / "frontend" / "src" / "api" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    typer.echo(f"Wrote {target}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
