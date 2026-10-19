# 0012. pdf.js legacy build; isEvalSupported kept

Status: Accepted

## Decision

The viewer uses `pdfjs-dist` 6.4 from its `legacy/build` folder and passes `isEvalSupported: false`.

## Why

The modern build of pdf.js 6 calls `Map.getOrInsertComputed`, which Chromium 141 and Safari don't have, so pages rendered blank. The legacy build includes polyfills. pdf.js removed the eval code path (CVE-2024-4367) in 5.7.284, so the option no longer does anything on this version; it stays in case an older version is ever pinned.
