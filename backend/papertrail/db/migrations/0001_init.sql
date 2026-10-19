-- 0001_init.sql (BUILD_PLAN §7)

CREATE TABLE documents (
  id              TEXT PRIMARY KEY,                -- uuid4
  sha256          TEXT NOT NULL UNIQUE,
  filename        TEXT NOT NULL,                   -- display only; never used as a file path
  page_count      INTEGER NOT NULL,
  status          TEXT NOT NULL CHECK (status IN
                    ('queued','parsing','extracting','verifying','ready','failed','unsupported')),
  status_detail   TEXT NOT NULL DEFAULT '',
  parser_version  TEXT NOT NULL DEFAULT '',
  document_type   TEXT NOT NULL DEFAULT 'other',
  document_date   TEXT,                            -- ISO date if found and verified
  current_run_id  TEXT,                            -- the run whose items are shown (§8.13)
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE pages (
  document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_no      INTEGER NOT NULL,                   -- 1-based
  width        REAL NOT NULL,                      -- PDF points
  height       REAL NOT NULL,
  is_scanned   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (document_id, page_no)
);

CREATE TABLE blocks (
  document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  id           TEXT NOT NULL,                      -- "p2:b14"
  page_no      INTEGER NOT NULL,
  seq          INTEGER NOT NULL,                   -- reading order across the document
  text         TEXT NOT NULL,
  x0 REAL NOT NULL, top REAL NOT NULL, x1 REAL NOT NULL, bottom REAL NOT NULL,
  PRIMARY KEY (document_id, id)
);

CREATE TABLE words (
  document_id  TEXT NOT NULL,
  block_id     TEXT NOT NULL,
  idx          INTEGER NOT NULL,
  text         TEXT NOT NULL,
  char_start   INTEGER NOT NULL,                   -- offset into blocks.text
  char_end     INTEGER NOT NULL,
  x0 REAL NOT NULL, top REAL NOT NULL, x1 REAL NOT NULL, bottom REAL NOT NULL,
  PRIMARY KEY (document_id, block_id, idx),
  FOREIGN KEY (document_id, block_id) REFERENCES blocks(document_id, id) ON DELETE CASCADE
);

CREATE TABLE runs (
  id                 TEXT PRIMARY KEY,
  document_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  provider           TEXT NOT NULL,                -- claude | replay | fake
  model              TEXT NOT NULL,                -- e.g. claude-haiku-5-5
  prompt_version     TEXT NOT NULL,                -- e.g. extract_v1
  effort             TEXT NOT NULL,                -- low | medium | high
  status             TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
  request_hash       TEXT NOT NULL,                -- links the run to its recording (§8.5)
  stop_reason        TEXT,
  error              TEXT,
  input_tokens       INTEGER,
  output_tokens      INTEGER,
  duration_ms        INTEGER,
  raw_response_path  TEXT,
  started_at         TEXT NOT NULL,
  finished_at        TEXT
);

CREATE TABLE items (
  id              TEXT PRIMARY KEY,
  document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  item_key        TEXT NOT NULL,                   -- stable hash: document sha256 + kind + normalized quote (§8.13)
  kind            TEXT NOT NULL CHECK (kind IN
                    ('action','document','deadline','amount','contact','uncertainty')),
  text            TEXT NOT NULL,                   -- plain-language line
  requirement     TEXT NOT NULL DEFAULT 'required' CHECK (requirement IN
                    ('required','optional','conditional')),
  condition       TEXT NOT NULL DEFAULT '',
  quote           TEXT NOT NULL,
  due_date        TEXT,                            -- ISO date (deadlines only)
  due_rule        TEXT,                            -- received_by | postmarked_by | on_or_before | unspecified
  due_calc        TEXT,                            -- "60 calendar days from 2026-03-03 = 2026-05-02"
  amount_cents    INTEGER,
  amount_role     TEXT,                            -- owed | charged | paid_by_insurer | balance | refund | other
  parent_item_id  TEXT REFERENCES items(id) ON DELETE SET NULL,  -- deadline attached to an action
  status          TEXT NOT NULL CHECK (status IN ('verified','needs_review','rejected')),
  review_state    TEXT NOT NULL DEFAULT 'none' CHECK (review_state IN
                    ('none','accepted','edited','dismissed')),
  created_at      TEXT NOT NULL
);

CREATE TABLE item_sources (
  item_id     TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  block_id    TEXT NOT NULL,
  char_start  INTEGER NOT NULL,
  char_end    INTEGER NOT NULL,
  PRIMARY KEY (item_id, block_id, char_start)
);

CREATE TABLE item_rects (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  page_no  INTEGER NOT NULL,
  x0 REAL NOT NULL, top REAL NOT NULL, x1 REAL NOT NULL, bottom REAL NOT NULL
);

CREATE TABLE checks (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  name     TEXT NOT NULL,                          -- e.g. quote_found
  result   TEXT NOT NULL CHECK (result IN ('pass','flag','fail')),
  detail   TEXT NOT NULL,                          -- human-readable reason
  PRIMARY KEY (item_id, name)
);

CREATE TABLE reviews (
  id           TEXT PRIMARY KEY,
  item_id      TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  action       TEXT NOT NULL CHECK (action IN ('accept','edit','dismiss','restore','carry_over')),
  before_json  TEXT NOT NULL,
  after_json   TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

CREATE TABLE jobs (
  id            TEXT PRIMARY KEY,
  document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  status        TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
  attempts      INTEGER NOT NULL DEFAULT 0,
  last_error    TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE INDEX idx_blocks_doc_seq   ON blocks(document_id, seq);
CREATE INDEX idx_items_doc_status ON items(document_id, status);
CREATE INDEX idx_items_run        ON items(run_id);
CREATE INDEX idx_items_key        ON items(document_id, item_key);
CREATE INDEX idx_rects_item       ON item_rects(item_id);
CREATE INDEX idx_jobs_status      ON jobs(status, created_at);

-- At most one active job per document (enforces the 409 rule in §8.13 at the database level)
CREATE UNIQUE INDEX uq_jobs_active ON jobs(document_id) WHERE status IN ('queued','running');

-- Key-value app settings, e.g. whether the first-run privacy notice was acknowledged
CREATE TABLE settings (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);
