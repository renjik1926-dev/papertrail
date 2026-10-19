# Limitations

An honest list of what PaperTrail can't do (yet).

## Documents
- **Scanned PDFs and photos are refused.** OCR is phase 2.
- **English, US-style letters only.** Date parsing assumes month/day/year.
- **Two-column layouts read across both columns.** Words at the same height are joined into
  one line, so side-by-side columns are mixed. Single-column letters are fine.
- **Tables:** each row becomes its own block, and rows with extra padding become separate blocks.
- **Rotated pages** (90/180/270 degrees) are supported and tested at 90 degrees. Pages that are
  both rotated *and* cropped are untested.
- **Block grouping thresholds are starting values.** The gap that starts a new block is
  0.6 x the line height (the plan's starting value of 1.2 merged ordinary paragraphs).

## Dates
- **Business days skip weekends but not holidays** (such items are flagged).
- A relative deadline ("within 60 days of ...") is calculated only from the letter's own date.
  "The date you received this letter" is flagged, because the letter can't know it.
- "This date has passed" is decided on your computer when you look at the item, not stored.

## Verifier
- Quote matching is fuzzy (scores 92 / 80) — tuned values come with the evaluation.
- An item flagged for text addressed to an AI is still shown (as needs review), not hidden.

## This draft
- **No real model responses yet.** The saved responses are hand-written placeholders, so there
  are no accuracy numbers. See the README.
- CI runs on Ubuntu only; Windows and macOS (including the child-process timeout on Windows)
  are not tested yet.
- Calendar reminders inside the `.ics` file haven't been checked in Google Calendar, Outlook
  and Apple Calendar; some apps replace them with their own defaults.
- pdf.js is loaded from its "legacy" build for wider browser support. The
  `isEvalSupported: false` option is passed, but pdf.js removed that code path in 5.7.284, so
  on the pinned version it has no effect (the fix for CVE-2024-4367 is built in).
- The large-upload limit is checked from the request size and while saving; the web framework
  buffers the upload first, so a huge upload still uses temporary disk space before it's refused.
