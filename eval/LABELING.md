# Labeling rules

Answer keys live in `labels/<document>.yaml`. Write a key **before** running the model on the
document, so the key doesn't copy the model's choices. Every key follows these rules.

## What to label

- **Action**: something the reader must or may do (pay, respond, call to schedule, submit).
  Not actions: "keep this for your records", "no action is needed", general information,
  and instructions *not* to do something ("wait for a bill before you pay").
- **Alternatives** ("pay in full by X or set up a plan by Y") are one action. Each date is a
  separate deadline.
- **Document**: each thing the reader must send. Two things in one sentence are two documents.
- **Deadline**: a date by which the reader must do something. Letter dates, service dates and
  "your assistance may end on ..." consequences are not deadlines.
- **Amount**: `owed` only when the letter asks the reader to pay it. "You may owe" on an
  explanation of benefits is `balance`. Billed amounts are `charged`; plan payments are
  `paid_by_insurer`.
- **Contact**: phone numbers, email addresses and websites the reader is told to use.

## Fields

```yaml
document: tax_notice_01.pdf
document_date: 2026-11-02
items:
  - kind: deadline
    what: respond if you disagree
    due: 2027-01-01            # resolved date; null if the letter gives no start date
    relative: {amount: 60, unit: calendar_days}   # only when due is null
    page: 1
    quote_contains: "within 60 days"
  - kind: amount
    role: owed
    cents: 124000
    page: 1
must_not_include:
  - kind: amount
    role: owed                 # e.g. the letter says it is not a bill
```

- `page` is the page where the supporting passage starts.
- `quote_contains` is a short exact phrase from the supporting passage. It is used to match
  actions, documents and contacts, and to check highlight positions.
- `text` / `what` is a plain-language description; matching uses fuzzy token-set similarity
  (>= 70) when `quote_contains` doesn't match.
- `must_not_include` entries match on `kind` plus any of `role`, `cents`, `due` and
  `quote_contains`.
