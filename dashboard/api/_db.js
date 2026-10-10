// Shared database access for the API routes. DATABASE_URL is a read-only role, set in Vercel's environment
// (never committed). Every route only reads saved results; nothing here calls a model.
import { neon } from "@neondatabase/serverless";

export const sql = neon(process.env.DATABASE_URL);

export function send(res, body, seconds = 3600) {
  res.setHeader("Cache-Control", `public, s-maxage=${seconds}, stale-while-revalidate=86400`);
  res.status(200).json(body);
}

export function fail(res, error) {
  res.status(500).json({ error: String(error && error.message ? error.message : error) });
}

export const AREAS = { access: "access", usability: "usability", playback: "playback", downloads: "playback",
  billing: "billing/support", support: "billing/support", catalog: "catalog (outside the four areas)",
  other: "other (outside the four areas)" };
