import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import type { ReviewIn } from "../api/client";
import { source } from "../api/source";
import { Checklist } from "../components/Checklist";
import { RunDetails } from "../components/RunDetails";
import { formatDate, localToday } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import { undatedDeadlines } from "../lib/grouping";
import { STEP_LABELS, isProcessing } from "../lib/status";
import { href } from "../router";
import { linkClick } from "./UploadPage";

const POLL_MS = 2000;
// pdf.js is large; load it only on the document page.
const PdfViewer = lazy(() =>
  import("../components/PdfViewer").then((m) => ({ default: m.PdfViewer })),
);
const STEPS = ["queued", "parsing", "extracting", "verifying"] as const;

export function DocumentPage({ id }: { id: string }) {
  const load = useCallback(async () => {
    const document = await source.getDocument(id);
    const items = document.current_run_id ? await source.getItems(id) : null;
    return { document, items };
  }, [id]);
  const state = useAsync(load);
  const { reload, mutate } = state;
  const doc = state.data?.document ?? null;
  const payload = state.data?.items ?? null;
  const [problem, setProblem] = useState<string | null>(null);
  const error = problem ?? state.error;
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [onlyNeedsReview, setOnlyNeedsReview] = useState(false);
  const today = localToday();

  const processing = doc ? isProcessing(doc.status) : false;
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(reload, POLL_MS);
    return () => window.clearInterval(timer);
  }, [processing, reload]);

  async function review(itemId: string, body: ReviewIn) {
    const updated = await source.review(itemId, body);
    mutate((current) =>
      current.items
        ? {
            ...current,
            items: {
              ...current.items,
              items: current.items.items.map((i) => (i.id === itemId ? updated : i)),
            },
          }
        : current,
    );
  }

  async function retry() {
    setProblem(null);
    try {
      await source.reprocess(id);
      reload();
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "Couldn't start again.");
    }
  }

  function show(itemId: string) {
    setActiveItemId(itemId);
    document.getElementById(`item-${itemId}`)?.scrollIntoView({ block: "nearest" });
  }

  if (error && !doc) {
    return (
      <p className="notice notice--error" role="alert">
        {error}
      </p>
    );
  }
  if (!doc) return <p>Loading…</p>;

  const calendar = source.calendarUrl(id);
  const undated = payload ? undatedDeadlines(payload.items).length : 0;
  const shownItems =
    payload?.items.filter((i) => i.status !== "rejected" && i.review_state !== "dismissed") ?? [];

  return (
    <div className="page-document">
      <header className="doc-header">
        <p className="crumb">
          <a href={href("/")} onClick={(e) => linkClick(e, "/")}>
            ← All letters
          </a>
        </p>
        <h1>{doc.filename}</h1>
        <p className="doc-meta">
          {doc.document_date ? `Dated ${formatDate(doc.document_date)}` : "Date not found"} ·{" "}
          {doc.page_count} {doc.page_count === 1 ? "page" : "pages"}
          {doc.document_type !== "other" && ` · ${doc.document_type.replace("_", " ")}`}
        </p>
        {doc.current_run_id && (
          <div className="doc-actions">
            {calendar ? (
              <a className="button" href={calendar} download>
                Download deadlines (.ics)
              </a>
            ) : (
              <span className="hint">Calendar download works in the installed app.</span>
            )}
            <a
              className="button"
              href={href(`/documents/${id}/print`)}
              onClick={(e) => linkClick(e, `/documents/${id}/print`)}
            >
              Printable action plan
            </a>
            {!source.demo && (
              <button type="button" onClick={() => void retry()} disabled={processing}>
                Process again
              </button>
            )}
          </div>
        )}
        {calendar && undated > 0 && (
          <p className="hint">
            {undated} {undated === 1 ? "deadline has" : "deadlines have"} no exact date and won't be
            in the calendar file.
          </p>
        )}
        {doc.current_run && <RunDetails run={doc.current_run} />}
      </header>

      {processing && (
        <section className="state" aria-live="polite">
          <h2>Processing</h2>
          <ol className="steps">
            {STEPS.map((step) => (
              <li
                key={step}
                aria-current={doc.status === step ? "step" : undefined}
                className={doc.status === step ? "steps__current" : ""}
              >
                {STEP_LABELS[step]}
              </li>
            ))}
          </ol>
          {doc.status_detail === "daily_limit" && <p>{doc.status_message}</p>}
        </section>
      )}

      {doc.status === "failed" && (
        <section className="state notice notice--error" role="alert">
          <h2>This letter couldn't be processed</h2>
          <p>{doc.status_message ?? "Something went wrong."}</p>
          {doc.next_step && <p>{doc.next_step}</p>}
          {!source.demo && (
            <button type="button" className="primary" onClick={() => void retry()}>
              Retry
            </button>
          )}
        </section>
      )}

      {doc.status === "unsupported" && (
        <section className="state notice" role="status">
          <h2>PaperTrail can't read this file</h2>
          <p>{doc.status_message}</p>
          {doc.next_step && <p>{doc.next_step}</p>}
        </section>
      )}

      {doc.status === "ready" && doc.status_detail && (
        <p className="notice" role="status">
          Processing again failed: {doc.status_message} Showing the earlier result.
        </p>
      )}
      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      {payload && doc.current_run_id && (
        <div className="panels">
          <div className="panel panel--checklist">
            <Checklist
              payload={payload}
              today={today}
              activeItemId={activeItemId}
              onlyNeedsReview={onlyNeedsReview}
              onToggleFilter={() => setOnlyNeedsReview((v) => !v)}
              onShow={show}
              onReview={review}
            />
          </div>
          {/* Focusable so keyboard users can scroll the letter (it scrolls on its own). */}
          <section className="panel panel--viewer" tabIndex={0} aria-label="The letter">
            <Suspense fallback={<p>Loading the letter…</p>}>
              <PdfViewer
                url={source.fileUrl(id)}
                pages={doc.pages}
                items={shownItems}
                activeItemId={activeItemId}
                onSelect={show}
              />
            </Suspense>
          </section>
        </div>
      )}
    </div>
  );
}
