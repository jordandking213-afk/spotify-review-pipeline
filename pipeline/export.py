"""Convert saved state into the formats GRADING_CONTRACT.md specifies (records and call-log lines)."""

from . import config

CONTRACT_LABEL_FIELDS = ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review")


def contract_record(rec):
    """One final record per source ID: completed (with labels) or quarantined (with a reason).
    Pending records are reported as such so incomplete runs stay visible; they are never 'completed'."""
    out = {"review_id": rec["review_id"], "source_sha256": rec["source_sha256"], "status": rec["status"]}
    if rec["status"] == "completed":
        labels = rec["labels"]
        out.update({k: labels[k] for k in CONTRACT_LABEL_FIELDS})
        out["label_config"] = config.LABEL_CONFIG
        if rec["cache_source_id"]:
            out["cache_source_id"] = rec["cache_source_id"]
        # Extra (non-graded) fields, kept for analysis and the memo's sensitivity check.
        out["paywall_named_feature"] = labels.get("paywall_named_feature")
        out["review_flag"] = labels.get("review_flag")
    elif rec["status"] == "quarantined":
        out["reason"] = rec["reason"]
        out["attempts"] = rec["attempts"]
    else:
        out["reason"] = "pending: not yet classified"
    return out


def contract_call(call):
    """A call-log line with the contract's fields plus the usage, timing and cost evidence behind them."""
    return {
        "request_id": call["request_id"], "role": call["role"], "review_ids": call["review_ids"],
        "model": call["model"], "phase": call["phase"], "outcome": call["outcome"],
        "label_config": call["label_config"], "input_tokens": call["input_tokens"],
        "output_tokens": call["output_tokens"], "cached_input_tokens": call["cached_input_tokens"],
        "cache_write_tokens": call["cache_write_tokens"], "reasoning_tokens": call["reasoning_tokens"],
        "usage_known": bool(call["usage_known"]), "cost_usd": call["cost_usd"], "reserved_usd": call["reserved_usd"],
        "error": call["error"], "attempt": call["attempt"], "is_retry_of_invalid": bool(call["is_retry_of_invalid"]),
        "simulated": bool(call["simulated"]), "run_id": call["run_id"], "started_at": call["started_at"],
        "duration_s": call["duration_s"],
    }
