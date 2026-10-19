"""`papertrail eval`: score the pipeline against hand-written answer keys (BUILD_PLAN §12)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from papertrail.extract.providers.base import Provider
from papertrail.locate import locate
from papertrail.parse.normalize import normalize_text
from papertrail.pipeline import run_in_memory
from papertrail.pricing import estimate_cost_usd
from papertrail.verify.models import ItemKind, Rect, VerifiedItem
from papertrail.verify.text import best_match, concat_blocks

KINDS = ("action", "document", "deadline", "amount", "contact")
TEXT_MATCH_SCORE = 70


@dataclass
class Expected:
    kind: str
    page: int | None
    text: str = ""
    quote_contains: str = ""
    due: str | None = None
    relative: dict[str, Any] | None = None
    role: str | None = None
    cents: int | None = None

    @classmethod
    def from_yaml(cls, data: dict[str, Any]) -> Expected:
        due = data.get("due")
        return cls(
            kind=str(data["kind"]),
            page=data.get("page"),
            text=str(data.get("text") or data.get("what") or ""),
            quote_contains=str(data.get("quote_contains") or ""),
            due=str(due) if due else None,
            relative=data.get("relative"),
            role=data.get("role"),
            cents=data.get("cents"),
        )


@dataclass
class AnswerKey:
    document: str
    document_date: str | None
    items: list[Expected]
    must_not_include: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> AnswerKey:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            document=str(data["document"]),
            document_date=str(data["document_date"]) if data.get("document_date") else None,
            items=[Expected.from_yaml(i) for i in data.get("items") or []],
            must_not_include=list(data.get("must_not_include") or []),
        )


def item_page(item: VerifiedItem) -> int | None:
    return item.rects[0].page_no if item.rects else None


def is_shown(item: VerifiedItem) -> bool:
    return item.status.value in ("verified", "needs_review")


def match_score(item: VerifiedItem, expected: Expected) -> float:
    """0 = no match. Rules from BUILD_PLAN §12."""
    if item.kind.value != expected.kind:
        return 0.0
    page_ok = expected.page is None or item_page(item) == expected.page
    if expected.kind == "deadline":
        if expected.due:
            return 100.0 if item.due_date == expected.due and page_ok else 0.0
        if expected.relative and page_ok and item.due_date is None:
            amount = str(expected.relative.get("amount", ""))
            return 100.0 if amount and amount in normalize_text(item.quote) else 0.0
        return 0.0
    if expected.kind == "amount":
        same = item.amount_cents == expected.cents and (
            expected.role is None or item.amount_role == expected.role
        )
        return 100.0 if same else 0.0
    if not page_ok:
        return 0.0
    if expected.quote_contains and normalize_text(expected.quote_contains) in normalize_text(
        item.quote
    ):
        return 100.0
    score = float(fuzz.token_set_ratio(normalize_text(item.text), normalize_text(expected.text)))
    return score if score >= TEXT_MATCH_SCORE else 0.0


def violates(item: VerifiedItem, rule: dict[str, Any]) -> bool:
    """A shown item matching every field of a `must_not_include` rule."""
    if item.kind.value != rule.get("kind"):
        return False
    values = {"role": item.amount_role, "cents": item.amount_cents, "due": item.due_date}
    for key, value in rule.items():
        if key == "kind":
            continue
        if key == "quote_contains":
            if normalize_text(str(value)) not in normalize_text(item.quote):
                return False
        elif values.get(key) != (str(value) if key == "due" else value):
            return False
    return True


def rects_overlap(a: list[Rect], b: list[Rect]) -> bool:
    return any(
        r.page_no == s.page_no
        and r.x0 < s.x1
        and s.x0 < r.x1
        and r.top < s.bottom
        and s.top < r.bottom
        for r in a
        for s in b
    )


@dataclass
class DocResult:
    name: str
    status: str
    expected: int = 0
    matched: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    input_tokens: int = 0
    output_tokens: int = 0


def evaluate_document(
    pdf: Path, key: AnswerKey, *, provider: Provider, effort: str, max_pages: int
) -> DocResult:
    result = DocResult(name=pdf.name, status="ok")
    pipeline = run_in_memory(pdf, provider=provider, effort=effort, max_pages=max_pages)
    counts = result.counts
    for expected in key.items:
        counts[expected.kind]["expected"] += 1
        if expected.kind == "deadline" and expected.due:
            counts["deadline"]["expected_dated"] += 1
    if pipeline.run is None or pipeline.run.verified is None or pipeline.parse.document is None:
        result.status = f"failed ({pipeline.reason})"
        result.expected = len(key.items)
        return result
    result.input_tokens = pipeline.run.extraction.input_tokens
    result.output_tokens = pipeline.run.extraction.output_tokens

    blocks = pipeline.parse.document.blocks
    document = concat_blocks(sorted(blocks, key=lambda b: b.seq))
    by_id = {b.id: b for b in blocks}
    predicted = [i for i in pipeline.run.verified.items if i.kind != ItemKind.uncertainty]

    pairs = sorted(
        (
            (match_score(item, expected), p, e)
            for p, item in enumerate(predicted)
            for e, expected in enumerate(key.items)
        ),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    pred_to_exp: dict[int, int] = {}
    used: set[int] = set()
    for score, p, e in pairs:
        if score <= 0 or p in pred_to_exp or e in used:
            continue
        # Only shown items count as finding an expected item.
        if not is_shown(predicted[p]):
            continue
        pred_to_exp[p] = e
        used.add(e)

    for p, item in enumerate(predicted):
        kind = item.kind.value
        shown = is_shown(item)
        matched = p in pred_to_exp
        correct_but_hidden = not matched and any(match_score(item, x) > 0 for x in key.items)
        if shown:
            counts[kind]["shown"] += 1
        if matched:
            counts[kind]["matched"] += 1
            expected = key.items[pred_to_exp[p]]
            if item.status.value == "verified":
                counts[kind]["verified_correct"] += 1
            else:
                counts[kind]["false_alarm"] += 1
            if kind == "deadline" and expected.due and item.due_date == expected.due:
                counts[kind]["date_correct"] += 1
            if expected.quote_contains:
                match = best_match(normalize_text(expected.quote_contains).strip(), document)
                if match.score >= 92 and rects_overlap(
                    item.rects, locate(match.source_ranges(), by_id)
                ):
                    counts[kind]["highlight_ok"] += 1
                counts[kind]["highlight_checked"] += 1
        elif correct_but_hidden:
            counts[kind]["false_alarm"] += 1  # a correct item the verifier rejected
        elif item.status.value == "verified":
            counts[kind]["wrong_but_verified"] += 1
        else:
            counts[kind]["mistakes_caught"] += 1
        result.rows.append(
            {
                "kind": kind,
                "status": item.status.value,
                "text": item.text,
                "matched": matched,
                "reasons": [c.detail for c in item.checks if c.result.value != "pass"],
            }
        )
    counts["_"]["must_not_violations"] = sum(
        1
        for item in predicted
        if is_shown(item)
        for rule in key.must_not_include
        if violates(item, rule)
    )
    result.expected = len(key.items)
    result.matched = len(used)
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def summarize(results: list[DocResult], *, model: str) -> dict[str, Any]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for result in results:
        for kind, values in result.counts.items():
            for name, value in values.items():
                totals[kind][name] += value
    per_kind = {
        kind: {
            "expected": totals[kind]["expected"],
            "shown": totals[kind]["shown"],
            "recall": _ratio(totals[kind]["matched"], totals[kind]["expected"]),
            "precision": _ratio(totals[kind]["matched"], totals[kind]["shown"]),
        }
        for kind in KINDS
    }

    def total(name: str) -> int:
        return sum(totals[k][name] for k in KINDS)

    matched = total("matched")
    input_tokens = sum(r.input_tokens for r in results)
    output_tokens = sum(r.output_tokens for r in results)
    n = max(1, len(results))
    cost = estimate_cost_usd(model, input_tokens, output_tokens)
    return {
        "documents": len(results),
        "failed_documents": sum(1 for r in results if r.status != "ok"),
        "per_kind": per_kind,
        "wrong_but_verified": total("wrong_but_verified"),
        "deadline_accuracy": _ratio(
            totals["deadline"]["date_correct"], totals["deadline"]["expected_dated"]
        ),
        "highlight_accuracy": _ratio(total("highlight_ok"), total("highlight_checked")),
        "mistakes_caught": total("mistakes_caught"),
        "false_alarms": total("false_alarm"),
        "verified_share": _ratio(total("verified_correct"), matched),
        "must_not_violations": totals["_"]["must_not_violations"],
        "mean_input_tokens": round(input_tokens / n),
        "mean_output_tokens": round(output_tokens / n),
        "mean_cost_usd": round(cost / n, 6) if cost is not None else None,
    }


GATED = ("deadline_accuracy", "verified_share", "highlight_accuracy")


def gate_failures(summary: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Regressions against eval/baseline.json (the CI gate from week 6)."""
    problems: list[str] = []
    if summary["wrong_but_verified"] > baseline.get("wrong_but_verified", 0):
        problems.append("wrong_but_verified went up")
    if summary["must_not_violations"] > baseline.get("must_not_violations", 0):
        problems.append("must_not_violations went up")
    for name in GATED:
        if baseline.get(name) is not None and (summary[name] or 0) < baseline[name]:
            problems.append(f"{name} fell below {baseline[name]}")
    for kind, values in baseline.get("per_kind", {}).items():
        for metric in ("recall", "precision"):
            floor = values.get(metric)
            if floor is not None and (summary["per_kind"][kind][metric] or 0) < floor:
                problems.append(f"{kind} {metric} fell below {floor}")
    return problems


def render_markdown(
    summary: dict[str, Any], results: list[DocResult], *, title: str, notes: list[str]
) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0%}"

    lines = [f"# {title}", ""]
    lines += [f"> {note}" for note in notes]
    lines += [
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Documents | {summary['documents']} ({summary['failed_documents']} failed) |",
        f"| Wrong-but-verified | {summary['wrong_but_verified']} |",
        f"| Deadline accuracy | {pct(summary['deadline_accuracy'])} |",
        f"| Highlight accuracy | {pct(summary['highlight_accuracy'])} |",
        f"| Mistakes caught | {summary['mistakes_caught']} |",
        f"| False alarms | {summary['false_alarms']} |",
        f"| Verified share | {pct(summary['verified_share'])} |",
        f"| Must-not violations | {summary['must_not_violations']} |",
        f"| Mean tokens in / out | {summary['mean_input_tokens']} / {summary['mean_output_tokens']} |",
        "",
        "| Kind | Expected | Shown | Recall | Precision |",
        "|---|---|---|---|---|",
    ]
    for kind, values in summary["per_kind"].items():
        lines.append(
            f"| {kind} | {values['expected']} | {values['shown']} | {pct(values['recall'])} | {pct(values['precision'])} |"
        )
    lines += ["", "## Per document", ""]
    for result in results:
        lines.append(
            f"### {result.name} - {result.status}, {result.matched}/{result.expected} expected items found"
        )
        for row in result.rows:
            if row["matched"] and row["status"] == "verified":
                continue
            mark = "matched" if row["matched"] else "no match in key"
            reasons = "; ".join(row["reasons"]) or "-"
            lines.append(f"- {row['kind']} · {row['status']} · {mark}: {row['text']} ({reasons})")
        lines.append("")
    return "\n".join(lines)


def write_report(
    out_dir: Path, stem: str, summary: dict[str, Any], markdown: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, json_path = out_dir / f"{stem}.md", out_dir / f"{stem}.json"
    md_path.write_text(markdown + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path
