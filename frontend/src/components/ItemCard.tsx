import { useState, type FormEvent } from "react";
import type { Item, ItemChanges, ReviewIn } from "../api/client";
import { formatDate, relativeLabel } from "../lib/dates";
import { formatCents, roleLabel } from "../lib/money";

const RULE_LABELS: Record<string, string> = {
  received_by: "must be received by",
  postmarked_by: "must be postmarked by",
  on_or_before: "on or before",
};

interface Props {
  item: Item;
  deadline: Item | undefined;
  today: string;
  active: boolean;
  readOnly?: boolean;
  onShow: (itemId: string) => void;
  onReview: (itemId: string, body: ReviewIn) => Promise<void>;
}

export function StatusLabel({ status }: { status: Item["status"] }) {
  if (status === "verified") {
    return (
      <span className="status status--verified">
        <span aria-hidden="true">✓</span> Verified against the letter
      </span>
    );
  }
  if (status === "needs_review") {
    return (
      <span className="status status--review">
        <span aria-hidden="true">!</span> Needs review
      </span>
    );
  }
  return (
    <span className="status status--rejected">
      <span aria-hidden="true">×</span> Not found in the letter
    </span>
  );
}

export function DueLine({ item, today }: { item: Item; today: string }) {
  if (!item.due_date) {
    return item.kind === "deadline" ? (
      <p className="due due--unknown">No exact date — check the letter for when this is due.</p>
    ) : null;
  }
  const passed = relativeLabel(item.due_date, today);
  const rule = item.due_rule ? RULE_LABELS[item.due_rule] : undefined;
  return (
    <p className={`due${passed.startsWith("This date has passed") ? " due--passed" : ""}`}>
      <strong>
        {rule ? `${rule[0]?.toUpperCase()}${rule.slice(1)} ` : "Due "}
        {formatDate(item.due_date)}
      </strong>{" "}
      · {passed}
    </p>
  );
}

export function ItemCard({ item, deadline, today, active, readOnly, onShow, onReview }: Props) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasons = [...new Set([...item.reasons, ...(deadline?.reasons ?? [])])];
  const page = item.page_no;

  async function review(body: ReviewIn) {
    setBusy(true);
    setError(null);
    try {
      await onReview(item.id, body);
      setEditing(false);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`item${active ? " item--active" : ""}`} id={`item-${item.id}`}>
      <div className="item__meta">
        <StatusLabel status={deadline?.status === "needs_review" ? "needs_review" : item.status} />
        {item.review_state === "edited" && <span className="tag">Edited by you</span>}
        {item.review_state === "accepted" && <span className="tag">Accepted</span>}
      </div>
      <p className="item__text">{item.text}</p>
      {item.condition && <p className="item__condition">{item.condition}</p>}
      {item.kind === "amount" && item.amount_cents !== null && (
        <p className="amount">
          <span className="amount__role">{roleLabel(item.amount_role)}</span>{" "}
          <strong>{formatCents(item.amount_cents)}</strong>
        </p>
      )}
      {item.kind === "deadline" && <DueLine item={item} today={today} />}
      {deadline && <DueLine item={deadline} today={today} />}
      {(item.due_calc || deadline?.due_calc) && (
        <p className="calc">Calculated: {item.due_calc ?? deadline?.due_calc}</p>
      )}
      {reasons.length > 0 && (
        <ul className="reasons" aria-label="Why to double-check this">
          {reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      )}
      <blockquote className="quote">
        <p>{item.quote}</p>
      </blockquote>
      <div className="item__actions">
        {page !== null && (
          <button type="button" className="link-button" onClick={() => onShow(item.id)}>
            Show on page {page}
          </button>
        )}
        {!readOnly && !editing && (
          <span className="review-buttons">
            {item.review_state !== "accepted" && (
              <button type="button" disabled={busy} onClick={() => review({ action: "accept" })}>
                Accept
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => setEditing(true)}>
              Edit
            </button>
            {item.review_state === "dismissed" ? (
              <button type="button" disabled={busy} onClick={() => review({ action: "restore" })}>
                Restore
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => review({ action: "dismiss" })}>
                Dismiss
              </button>
            )}
            {(item.review_state === "edited" || item.review_state === "accepted") && (
              <button type="button" disabled={busy} onClick={() => review({ action: "restore" })}>
                Undo
              </button>
            )}
          </span>
        )}
      </div>
      {item.original && (
        <p className="original">PaperTrail first read this as: “{item.original.text}”</p>
      )}
      {editing && (
        <EditForm
          item={item}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSave={(changes) => review({ action: "edit", changes })}
        />
      )}
      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

function EditForm({
  item,
  busy,
  onSave,
  onCancel,
}: {
  item: Item;
  busy: boolean;
  onSave: (changes: ItemChanges) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(item.text);
  const [dueDate, setDueDate] = useState(item.due_date ?? "");
  const [amount, setAmount] = useState(
    item.amount_cents !== null ? (item.amount_cents / 100).toFixed(2) : "",
  );
  const [requirement, setRequirement] = useState(item.requirement);
  const [condition, setCondition] = useState(item.condition);
  const [problem, setProblem] = useState<string | null>(null);
  const prefix = `edit-${item.id}`;

  function submit(event: FormEvent) {
    event.preventDefault();
    const changes: ItemChanges = {};
    if (!text.trim()) return setProblem("The description can't be empty.");
    if (text !== item.text) changes.text = text.trim();
    if (item.kind === "deadline" && dueDate !== (item.due_date ?? "")) {
      if (!dueDate) return setProblem("Pick a date, or cancel.");
      changes.due_date = dueDate;
    }
    if (item.kind === "amount") {
      const cents = Math.round(Number(amount.replace(/[$,\s]/g, "")) * 100);
      if (!Number.isFinite(cents) || cents < 0) return setProblem("Enter an amount like 1240.00.");
      if (cents !== item.amount_cents) changes.amount_cents = cents;
    }
    if (requirement !== item.requirement) changes.requirement = requirement;
    if (condition !== item.condition) changes.condition = condition;
    if (Object.keys(changes).length === 0) return onCancel();
    setProblem(null);
    onSave(changes);
  }

  return (
    <form className="edit-form" onSubmit={submit}>
      <label htmlFor={`${prefix}-text`}>Description</label>
      <input
        id={`${prefix}-text`}
        value={text}
        maxLength={500}
        onChange={(e) => setText(e.target.value)}
      />
      {item.kind === "deadline" && (
        <>
          <label htmlFor={`${prefix}-date`}>Due date</label>
          <input
            id={`${prefix}-date`}
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </>
      )}
      {item.kind === "amount" && (
        <>
          <label htmlFor={`${prefix}-amount`}>Amount (USD)</label>
          <input
            id={`${prefix}-amount`}
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </>
      )}
      {(item.kind === "action" || item.kind === "document" || item.kind === "deadline") && (
        <>
          <label htmlFor={`${prefix}-req`}>Applies</label>
          <select
            id={`${prefix}-req`}
            value={requirement}
            onChange={(e) => setRequirement(e.target.value as Item["requirement"])}
          >
            <option value="required">Always</option>
            <option value="conditional">Only in some cases</option>
            <option value="optional">Optional</option>
          </select>
          <label htmlFor={`${prefix}-cond`}>Condition</label>
          <input
            id={`${prefix}-cond`}
            value={condition}
            maxLength={500}
            onChange={(e) => setCondition(e.target.value)}
          />
        </>
      )}
      <p className="hint">The quote and its place in the letter can't be edited.</p>
      {problem && (
        <p className="notice notice--error" role="alert">
          {problem}
        </p>
      )}
      <div className="edit-form__buttons">
        <button type="submit" className="primary" disabled={busy}>
          Save
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}
