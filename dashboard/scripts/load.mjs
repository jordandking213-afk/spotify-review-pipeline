// Load the full run's saved outputs from this repository into the Neon Postgres database.
// No model calls. Reads only committed files (grading/, evals/, outputs/) plus DATABASE_URL_OWNER from dashboard/.env.
//   cd dashboard && npm install && npm run load

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import pg from "pg";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const read = (p) => fs.readFileSync(path.join(REPO, p), "utf8");
const json = (p) => JSON.parse(read(p));

function env() {
  const file = path.join(HERE, "..", ".env");
  const vars = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const i = line.indexOf("=");
    if (i > 0) vars[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return vars;
}

function csv(p) {                      // simple CSV parser (quoted fields, no embedded newlines in these files)
  const lines = read(p).trim().split("\n");
  const split = (l) => {
    const out = []; let cur = ""; let q = false;
    for (let i = 0; i < l.length; i++) {
      const c = l[i];
      if (q) { if (c === '"' && l[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
      else if (c === '"') q = true; else if (c === ",") { out.push(cur); cur = ""; } else cur += c;
    }
    out.push(cur); return out;
  };
  const head = split(lines[0]);
  return lines.slice(1).map((l) => Object.fromEntries(split(l).map((v, i) => [head[i], v])));
}

async function insertMany(client, table, columns, rows, batch = 1000) {
  for (let i = 0; i < rows.length; i += batch) {
    const chunk = rows.slice(i, i + batch);
    const params = [];
    const values = chunk.map((row, r) => `(${columns.map((_, c) => `$${r * columns.length + c + 1}`).join(",")})`);
    for (const row of chunk) for (const c of columns) params.push(row[c] ?? null);
    await client.query(`INSERT INTO ${table} (${columns.join(",")}) VALUES ${values.join(",")}`, params);
  }
}

const client = new pg.Client({ connectionString: env().DATABASE_URL_OWNER });
await client.connect();
console.log("schema…");
await client.query(read("dashboard/db/schema.sql"));

// Membership: issue per review.
const membership = new Map(csv("grading/membership.csv").map((r) => [r.review_id, r.issue_id]));

// Records: labels only (no review text, no evidence quote), streamed from the gzip export.
console.log("records…");
const cols = ["review_id", "source_sha256", "status", "reason", "topic", "intent", "severity", "sentiment",
  "needs_review", "review_flag", "paywall_named_feature", "entities", "cache_source_id", "issue_id"];
const rl = readline.createInterface({ input: fs.createReadStream(path.join(REPO, "grading/records.jsonl.gz")).pipe(zlib.createGunzip()) });
let buffer = [], loaded = 0;
for await (const line of rl) {
  if (!line.trim()) continue;
  const r = JSON.parse(line);
  buffer.push({ ...r, entities: r.entities ?? null, issue_id: membership.get(r.review_id) ?? null });
  if (buffer.length === 5000) {
    await insertMany(client, "records", cols, buffer); loaded += buffer.length; buffer = [];
    if (loaded % 100000 === 0) console.log(`  ${loaded.toLocaleString()} records`);
  }
}
await insertMany(client, "records", cols, buffer); loaded += buffer.length;
console.log(`  ${loaded.toLocaleString()} records loaded`);

console.log("issues, rankings, aggregates…");
const issues = json("evals/rank_full/issues.json").issues;
await insertMany(client, "issues", ["issue_id", "name", "description", "grouping_rule", "name_source", "example_review_ids"],
  issues.map((i) => ({ ...i, grouping_rule: i.rule })));
for (const [view, file] of [["baseline", "grading/ranking.csv"],
  ["business_excl_other_general", "evals/rank_full/ranking_business_excl_other_general.csv"],
  ["paywall_sev2", "evals/rank_full/ranking_paywall_sev2.csv"]]) {
  await insertMany(client, "rankings", ["view", "rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"],
    csv(file).map((r) => ({ ...r, view })));
}
const aggCols = Object.keys(csv("evals/rank_full/aggregates.csv")[0]);
await insertMany(client, "aggregates", aggCols, csv("evals/rank_full/aggregates.csv"));

console.log("memo, claims, quantities, evidence…");
const q = json("outputs/memo/quantities.json");
const used = new Set(csv("grading/claims.csv").map((c) => c.claim_id));
await insertMany(client, "claims", ["claim_id", "issue_id", "metric", "value", "used_in_memo"],
  q.claims.map((c) => ({ ...c, used_in_memo: used.has(c.claim_id) })));
await insertMany(client, "quantities", ["id", "label", "value", "formula"], q.other_quantities);
const ev = [];
for (const [issue_id, info] of Object.entries(q.evidence)) for (const e of info.examples) ev.push({ review_id: e.review_id, issue_id, quote: e.quote });
await insertMany(client, "evidence", ["review_id", "issue_id", "quote"], ev);

const raw = json("outputs/memo/memo_raw.json").memo;
const md = read("memo.md");
const headings = { recommendation: "Recommendation", supporting_evidence: "Supporting evidence",
  alternatives: "Alternatives considered", sensitivity: "Sensitivity check: paywall severity", limitations: "Limitations" };
const sections = Object.entries(headings).map(([key, heading], i) => {
  const start = md.indexOf(`## ${heading}`) + heading.length + 3;
  const end = md.indexOf("\n## ", start);
  return { position: i + 1, section: key, template: raw[key], rendered: md.slice(start, end).trim() };
});
const note = md.match(/> \*\*Analyst's note[^\n]*/)[0].replace(/^> /, "");
sections.unshift({ position: 0, section: "analyst_note", template: note, rendered: note });
await insertMany(client, "memo_sections", ["position", "section", "template", "rendered"], sections);

console.log("run metrics…");
const metrics = {
  ingestion: json("outputs/ingestion_report.json"),
  manifest: json("outputs/data_manifest.json"),
  self_check: json("outputs/self_check_summary.json"),
  verifier: json("evals/verify_full/summary.json"),
  planted_errors: (({ planted, caught }) => ({ planted, caught }))(json("evals/verify_full/planted_errors.json")),
  golden_v1: json("evals/golden/results_v1/summary.json"),
  golden_v2: json("evals/golden/results_v2/summary.json"),
  injection: (({ passed, cases }) => ({ passed, cases }))(json("evals/injection/results.json")),
  run_summary: json("outputs/run_summary.json"),
};
delete metrics.manifest.outputs_sha256;
delete metrics.golden_v1.per_topic; delete metrics.golden_v2.per_topic;
await insertMany(client, "run_metrics", ["key", "value"], Object.entries(metrics).map(([key, value]) => ({ key, value: JSON.stringify(value) })));

const counts = await client.query("SELECT status, count(*)::int AS n FROM records GROUP BY status ORDER BY status");
console.log("done:", counts.rows);
await client.end();
