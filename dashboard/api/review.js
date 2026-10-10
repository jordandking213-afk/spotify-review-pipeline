// Look up one review's saved labels by its original review ID (labels only; review text is not stored here).
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  try {
    const id = String(req.query.id || "").trim();
    const rows = await sql`SELECT * FROM records WHERE review_id = ${id}`;
    if (!rows.length) return res.status(404).json({ error: "review ID not found" });
    const quote = await sql`SELECT issue_id, quote FROM evidence WHERE review_id = ${id}`;
    send(res, { record: rows[0], evidence_quote: quote[0]?.quote ?? null });
  } catch (e) { fail(res, e); }
}
