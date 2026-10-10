// Recompute the baseline ranking live with SQL over all stored records and compare it with the saved ranking;
// also check every memo claim against the saved ranking. Shows the dashboard's numbers match saved calculations.
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  try {
    const [live, saved, claims] = await Promise.all([
      sql`SELECT issue_id, count(*)::int AS complaint_count, sum(severity)::int AS severity_sum,
            to_char(round(sum(severity)::numeric / count(*), 6), 'FM999990.000000') AS mean_severity
          FROM records WHERE issue_id IS NOT NULL AND status = 'completed'
          GROUP BY issue_id ORDER BY sum(severity) DESC, issue_id`,
      sql`SELECT issue_id, complaint_count, severity_sum, mean_severity FROM rankings WHERE view = 'baseline' ORDER BY rank`,
      sql`SELECT c.claim_id, c.metric, c.value, r.complaint_count, r.severity_sum, r.mean_severity, r.priority_score
          FROM claims c JOIN rankings r ON r.issue_id = c.issue_id AND r.view = 'baseline' WHERE c.used_in_memo`,
    ]);
    const mismatches = saved.filter((s, i) => !live[i] || live[i].issue_id !== s.issue_id ||
      live[i].complaint_count !== s.complaint_count || live[i].severity_sum !== s.severity_sum ||
      live[i].mean_severity !== s.mean_severity);
    const badClaims = claims.filter((c) => String(c[c.metric]) !== c.value);
    send(res, { ranking_matches: mismatches.length === 0 && live.length === saved.length, issues_compared: saved.length,
      records_aggregated: live.reduce((n, r) => n + r.complaint_count, 0), mismatches,
      memo_claims_checked: claims.length, memo_claims_matching: claims.length - badClaims.length, bad_claims: badClaims }, 600);
  } catch (e) { fail(res, e); }
}
