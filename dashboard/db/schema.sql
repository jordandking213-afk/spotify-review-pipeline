-- Database for the Spotify review dashboard. Stores the processed full-run outputs (labels only, no review text
-- except the short evidence quotes the memo cites), aggregates, rankings and the AI-generated memo.
-- Loaded by dashboard/scripts/load.mjs from files committed in this repository.

DROP TABLE IF EXISTS records, issues, rankings, aggregates, claims, quantities, memo_sections, evidence, run_metrics CASCADE;

CREATE TABLE records (               -- one row per source review ID (660,622)
    review_id              text PRIMARY KEY,
    source_sha256          char(64) NOT NULL,
    status                 text NOT NULL CHECK (status IN ('completed', 'quarantined')),
    reason                 text,      -- quarantine reason
    topic                  text,
    intent                 text,
    severity               smallint,
    sentiment              real,
    needs_review           boolean,
    review_flag            text,
    paywall_named_feature  boolean,
    entities               text[],
    cache_source_id        text,      -- direct exact-text reuse provenance
    issue_id               text       -- issue membership (complaints/cancellations only)
);
CREATE INDEX records_issue ON records (issue_id);

CREATE TABLE issues (
    issue_id           text PRIMARY KEY,
    name               text NOT NULL,
    description        text NOT NULL,
    grouping_rule      text NOT NULL,
    name_source        text NOT NULL,
    example_review_ids text[] NOT NULL
);

CREATE TABLE rankings (              -- view: baseline | business_excl_other_general | paywall_sev2
    view            text NOT NULL,
    rank            integer NOT NULL,
    issue_id        text NOT NULL,
    complaint_count integer NOT NULL,
    severity_sum    integer NOT NULL,
    mean_severity   text NOT NULL,     -- six decimals, half-up, exactly as exported
    priority_score  integer NOT NULL,
    PRIMARY KEY (view, rank)
);

CREATE TABLE aggregates (
    issue_id text PRIMARY KEY, complaint_count integer, severity_sum integer, mean_severity text,
    priority_score integer, cancellation_count integer, complaint_intent_count integer,
    sev1 integer, sev2 integer, sev3 integer, sev4 integer, sev5 integer,
    paywall_named_feature_count integer, needs_review_count integer
);

CREATE TABLE claims (claim_id text PRIMARY KEY, issue_id text, metric text, value text, used_in_memo boolean);
CREATE TABLE quantities (id text PRIMARY KEY, label text, value text, formula text);
CREATE TABLE memo_sections (position integer PRIMARY KEY, section text, template text, rendered text);
CREATE TABLE evidence (review_id text, issue_id text, quote text, PRIMARY KEY (review_id, issue_id));
CREATE TABLE run_metrics (key text PRIMARY KEY, value jsonb NOT NULL);
