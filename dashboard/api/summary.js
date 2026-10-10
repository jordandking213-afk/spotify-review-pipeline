// Overall metrics: live counts from the records table plus saved run metrics (cost, tokens, evaluations).
import { sql, send, fail, AREAS } from "./_db.js";

export default async function handler(req, res) {
  try {
    const [status, intents, review, reuse, byTopic, metrics] = await Promise.all([
      sql`SELECT status, count(*)::int AS n FROM records GROUP BY status`,
      sql`SELECT intent, count(*)::int AS n FROM records WHERE status = 'completed' GROUP BY intent ORDER BY n DESC`,
      sql`SELECT count(*) FILTER (WHERE needs_review)::int AS needs_review FROM records`,
      sql`SELECT count(*) FILTER (WHERE cache_source_id IS NOT NULL)::int AS cache_reuses FROM records`,
      sql`SELECT split_part(issue_id, '.', 1) AS topic, count(*)::int AS complaints, sum(severity)::int AS severity_sum
          FROM records WHERE issue_id IS NOT NULL GROUP BY 1`,
      sql`SELECT key, value FROM run_metrics`,
    ]);
    const m = Object.fromEntries(metrics.map((r) => [r.key, r.value]));
    const areas = {};
    for (const t of byTopic) {
      const a = (areas[AREAS[t.topic]] ??= { area: AREAS[t.topic], complaints: 0, severity_sum: 0 });
      a.complaints += t.complaints; a.severity_sum += t.severity_sum;
    }
    const areaList = Object.values(areas).map((a) => ({ ...a, mean_severity: (a.severity_sum / a.complaints).toFixed(6) }))
      .sort((x, y) => y.severity_sum - x.severity_sum);
    send(res, {
      records: Object.fromEntries(status.map((r) => [r.status, r.n])),
      intents, needs_review: review[0].needs_review, cache_reuses: reuse[0].cache_reuses, areas: areaList,
      quarantine_reasons: m.ingestion.final_accounting.quarantine_reasons,
      ingestion_checks: m.ingestion.checks_against_course_manifest,
      cost_usd: m.manifest.api_cost_usd, tokens: m.manifest.usage_totals, models: m.manifest.models,
      configs: m.manifest.configs, spend_cap_usd: m.manifest.settings.spend_cap_usd,
      wall_clock_s: m.run_summary.wall_clock_s, self_check: { status: m.self_check.status,
        coverage_point: m.self_check.working_coverage_point_candidate, issue_counts: m.self_check.issue_counts },
      verifier: { verified: m.verifier.verified, agreement: m.verifier.agreement },
      planted_errors: m.planted_errors, injection: m.injection,
      golden: { v1: m.golden_v1.agreement_strict, v2: m.golden_v2.agreement_strict,
        severity_mae_v1: m.golden_v1.severity_mae, severity_mae_v2: m.golden_v2.severity_mae },
    });
  } catch (e) { fail(res, e); }
}
