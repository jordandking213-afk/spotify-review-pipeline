"""Deterministic issue rules: every completed complaint/cancellation gets exactly one issue.

issue_id = "<topic>.<facet>". The facet is the first rule below whose condition matches, using only saved fields
(the code-matched entities and the model's paywall flag), so membership can be recomputed without a model.
Rules are checked in order; the last rule for each topic is a catch-all, so no complaint is left ungrouped.
"""

ISSUE_RULES_VERSION = "issues-v1"

# topic -> ordered list of (facet, required entities (any), needs paywall flag)
RULES = {
    "access": [("login", {"login"}, False), ("account", {"account"}, False), ("general", set(), False)],
    "usability": [("ads", {"ads"}, False), ("playback_controls", {"skip", "shuffle", "repeat", "queue"}, False),
                  ("playlists", {"playlist"}, False), ("devices", {"car", "bluetooth", "widget"}, False),
                  ("update_changes", {"update"}, False), ("general", set(), False)],
    "playback": [("crashes", {"crash"}, False), ("devices", {"car", "bluetooth"}, False),
                 ("podcasts", {"podcast"}, False), ("general", set(), False)],
    "downloads": [("offline", {"offline"}, False), ("general", set(), False)],
    "catalog": [("lyrics", {"lyrics"}, False), ("search", {"search"}, False),
                ("recommendations", {"recommendations"}, False), ("podcasts_audiobooks", {"podcast", "audiobook"}, False),
                ("general", set(), False)],
    "billing": [("paywall_named_feature", set(), True), ("charges_refunds", {"charge"}, False),
                ("price", {"price"}, False), ("subscription", {"subscription"}, False),
                ("premium_other", {"premium"}, False), ("general", set(), False)],
    "support": [("general", set(), False)],
    "other": [("general", set(), False)],
}


def issue_for(labels):
    """Return (issue_id, rule description) for one completed record's labels."""
    entities = set(labels["entities"])
    for facet, needs_any, needs_paywall in RULES[labels["topic"]]:
        if needs_paywall and not labels.get("paywall_named_feature"):
            continue
        if needs_any and not (entities & needs_any):
            continue
        rule = ("paywall_named_feature = true" if needs_paywall else
                f"entities include any of {sorted(needs_any)}" if needs_any else "no earlier rule matched")
        return f"{labels['topic']}.{facet}", rule
    raise AssertionError("every topic ends with a catch-all rule")
