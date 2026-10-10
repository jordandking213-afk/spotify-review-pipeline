// The AI-generated recommendation (memo role output) with every number it cites and the evidence it uses.
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  try {
    const [sections, claims, quantities, evidence] = await Promise.all([
      sql`SELECT position, section, template, rendered FROM memo_sections ORDER BY position`,
      sql`SELECT * FROM claims ORDER BY length(claim_id), claim_id`,
      sql`SELECT * FROM quantities ORDER BY length(id), id`,
      sql`SELECT e.review_id, e.issue_id, e.quote, r.topic, r.intent, r.severity
          FROM evidence e JOIN records r USING (review_id) ORDER BY e.issue_id, e.review_id`,
    ]);
    const cited = new Set(sections.flatMap((s) => [...s.template.matchAll(/\{([CX]\d+)\}/g)].map((m) => m[1])));
    send(res, { sections, claims: claims.filter((c) => cited.has(c.claim_id)),
      quantities: quantities.filter((x) => cited.has(x.id)), evidence });
  } catch (e) { fail(res, e); }
}
