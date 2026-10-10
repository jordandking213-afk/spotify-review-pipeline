// Issue rankings saved by the rank stage: baseline (contract), business view, or paywall sensitivity.
import { sql, send, fail } from "./_db.js";

const VIEWS = ["baseline", "business_excl_other_general", "paywall_sev2"];

export default async function handler(req, res) {
  try {
    const view = VIEWS.includes(req.query.view) ? req.query.view : "baseline";
    const rows = await sql`SELECT r.rank, r.issue_id, i.name, r.complaint_count, r.severity_sum, r.mean_severity,
        r.priority_score FROM rankings r LEFT JOIN issues i USING (issue_id) WHERE r.view = ${view} ORDER BY r.rank`;
    send(res, { view, rows });
  } catch (e) { fail(res, e); }
}
