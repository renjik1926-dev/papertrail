import { useCallback } from "react";
import type { Item } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { source } from "../api/source";
import { formatDate, isPassed, localToday } from "../lib/dates";
import { buildChecklist, undatedDeadlines } from "../lib/grouping";
import { formatCents, roleLabel } from "../lib/money";
import { href } from "../router";
import { linkClick } from "./UploadPage";

function Source({ item }: { item: Item }) {
  return (
    <p className="print-source">
      “{item.quote}”{item.page_no !== null && ` — page ${item.page_no}`}
    </p>
  );
}

export function PrintPage({ id }: { id: string }) {
  const load = useCallback(() => Promise.all([source.getDocument(id), source.getItems(id)]), [id]);
  const { data, error } = useAsync(load);
  const today = localToday();
  if (error) return <p className="notice notice--error">{error}</p>;
  const [doc, payload] = data ?? [null, null];

  if (!doc || !payload) return <p>Loading…</p>;
  const checklist = buildChecklist(payload.items);
  const live = payload.items.filter(
    (i) => i.status !== "rejected" && i.review_state !== "dismissed",
  );
  // Actions only: documents, deadlines and amounts have their own sections below.
  const tasks = checklist.groups
    .filter((g) => g.id === "do" || g.id === "conditional")
    .flatMap((g) => g.items)
    .filter((i) => i.kind === "action");
  const deadlines = live
    .filter((i) => i.kind === "deadline" && i.due_date)
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1));
  const undated = undatedDeadlines(payload.items);
  const documents = live.filter((i) => i.kind === "document");
  const amounts = live.filter((i) => i.kind === "amount");
  const contacts = live.filter((i) => i.kind === "contact");

  return (
    <article className="print">
      <p className="no-print">
        <a href={href(`/documents/${id}`)} onClick={(e) => linkClick(e, `/documents/${id}`)}>
          ← Back
        </a>{" "}
        <button type="button" className="primary" onClick={() => window.print()}>
          Print
        </button>
      </p>
      <h1>Action plan: {doc.filename}</h1>
      <p>
        {doc.document_date
          ? `Letter dated ${formatDate(doc.document_date)}`
          : "Letter date not found"}
      </p>

      <h2>To do</h2>
      <ul className="print-checklist">
        {tasks.map((item) => (
          <li key={item.id}>
            <span className="box" aria-hidden="true">
              ☐
            </span>{" "}
            {item.text}
            {item.condition && ` (${item.condition})`}
            {item.status === "needs_review" && " — needs review"}
            <Source item={item} />
          </li>
        ))}
      </ul>

      <h2>Deadlines</h2>
      {deadlines.length === 0 ? (
        <p>No dated deadlines.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">What</th>
              <th scope="col">Page</th>
            </tr>
          </thead>
          <tbody>
            {deadlines.map((item) => (
              <tr key={item.id}>
                <td>
                  {formatDate(item.due_date!)}
                  {isPassed(item.due_date!, today) && " (passed)"}
                </td>
                <td>
                  {item.text}
                  {item.due_calc && <span className="print-calc"> — {item.due_calc}</span>}
                </td>
                <td>{item.page_no ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {undated.length > 0 && (
        <>
          <h2>Check these dates yourself</h2>
          <ul>
            {undated.map((item) => (
              <li key={item.id}>
                {item.text}
                <Source item={item} />
              </li>
            ))}
          </ul>
        </>
      )}

      {documents.length > 0 && (
        <>
          <h2>Documents to send</h2>
          <ul className="print-checklist">
            {documents.map((item) => (
              <li key={item.id}>
                <span className="box" aria-hidden="true">
                  ☐
                </span>{" "}
                {item.text}
                {item.condition && ` (${item.condition})`}
                <Source item={item} />
              </li>
            ))}
          </ul>
        </>
      )}

      {amounts.length > 0 && (
        <>
          <h2>Amounts</h2>
          <ul>
            {amounts.map((item) => (
              <li key={item.id}>
                {roleLabel(item.amount_role)}:{" "}
                {item.amount_cents !== null ? formatCents(item.amount_cents) : "?"} ({item.text})
                <Source item={item} />
              </li>
            ))}
          </ul>
        </>
      )}

      {contacts.length > 0 && (
        <>
          <h2>Contacts</h2>
          <ul>
            {contacts.map((item) => (
              <li key={item.id}>
                {item.text}
                <Source item={item} />
              </li>
            ))}
          </ul>
        </>
      )}

      <footer className="print-footer">
        Generated by PaperTrail. Not legal, medical or financial advice — check each item against
        the original letter.
      </footer>
    </article>
  );
}
