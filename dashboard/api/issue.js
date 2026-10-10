// One issue: name, rule, aggregates, the memo's evidence quotes, and member review IDs from the records table.
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  try {
    const id = String(req.query.id || "");
    const [issue, agg, evidence, members] = await Promise.all([
      sql`SELECT * FROM issues WHERE issue_id = ${id}`,
      sql`SELECT * FROM aggregates WHERE issue_id = ${id}`,
      sql`SELECT review_id, quote FROM evidence WHERE issue_id = ${id}`,
      sql`SELECT review_id, intent, severity FROM records WHERE issue_id = ${id} ORDER BY review_id LIMIT 25`,
    ]);
    if (!issue.length) return res.status(404).json({ error: "unknown issue" });
    send(res, { issue: issue[0], aggregates: agg[0] ?? null, evidence, member_sample: members });
  } catch (e) { fail(res, e); }
}
