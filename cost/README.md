# Cost and runtime calculator

Specification: `COST_CALCULATOR.md` in the course dataset ZIP.

## Offline replay (default: no API key, no network, no model calls)

```bash
python3 cost/calculator.py
```

This recomputes `cost/report.md` (and `report.json`) from the saved pilot evidence and the editable prices.
To try other prices or assumptions, copy and edit the files, then:

```bash
python3 cost/calculator.py --rates my_rates.csv --assumptions my_assumptions.json --out my_report.md
```

Editing prices or assumptions changes costs and projections. It never changes the measured usage or time.

## Paid pilot (separate, explicit command)

```bash
python3 cost/calculator.py pilot --confirm-paid
```

This runs the real pipeline (enrich → verify 20% → group → rank → memo) on `cost_100.csv` unchanged, starting from
an empty result cache with one worker (**cold**), then runs it again on the saved results (**warm**: zero new
enrichment calls expected). It refuses to run if `runs/pilot-100/` already exists, so a pilot is never paid for
twice by accident. A $0 rehearsal with the fake model is `python3 cost/calculator.py pilot --client fake`; its output
goes to `cost/rehearsal-fake/` and is marked SIMULATED.

## Files

| File | Contents |
|---|---|
| `rates.csv` | Editable prices: model, billing item, unit, price, currency, tier, dated source link |
| `assumptions.json` | Editable full-run assumptions and controls: budget, output-token cap, workers, fallback fraction, retry rates, scenarios |
| `pilot_records.jsonl` | One record per pilot ID: grading-contract fields, row hash, status |
| `pilot_calls.jsonl` | Every attempted call (cold and warm), including failures and retries, with usage, timing, request IDs |
| `usage.csv` | The same usage as a table, with each call's billing items |
| `pilot_run.json` | Measured wall-clock time per phase and per stage, workers, input checksum, record counts |
| `report.md` / `report.json` | Measured 100-review results and full-run estimates, recomputed by the replay |
