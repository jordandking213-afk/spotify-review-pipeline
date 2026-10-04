"""Model clients. Every client returns the same Response shape so the orchestrator never depends on a provider.

FakeClient makes no network calls and costs nothing. It produces plausible labels from keywords and can be
told to misbehave (drop items, return bad JSON, rate-limit, time out) so the safeguards can be tested at $0.
Its usage numbers are simulated and every call it makes is logged with simulated=1.
"""

import json
import random
import re
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Response:
    text: str                     # raw model output (expected: JSON)
    request_id: str
    complete: bool                # False when the provider reports truncated/incomplete output
    usage: dict = field(default_factory=dict)  # input, cached_input, output, reasoning (tokens)


class TransientError(Exception):
    """Rate limit, server error or timeout: safe to retry with backoff. `usage_known` is False for timeouts,
    where the provider may have billed a request we never saw finish."""

    def __init__(self, message, request_id, usage_known=True):
        super().__init__(message)
        self.request_id = request_id
        self.usage_known = usage_known


class PermanentError(Exception):
    """Authentication, bad request, or insufficient credit: retrying will not help, so the run stops."""


# --- Fake model ------------------------------------------------------------------------------------------

ALWAYS_INVALID_MARKER = "[[FAKE_ALWAYS_INVALID]]"   # test fixture texts containing this always get a bad answer
_REVIEW = re.compile(r"^#(\d+)\n((?:<\d+> .*(?:\n|$))+)", re.MULTILINE)

_TOPIC_WORDS = [
    ("access", r"log ?in|password|account|sign ?in"),
    ("billing", r"premium|price|charg|subscri|refund|pay"),
    ("downloads", r"offline|downloaded"),
    ("playback", r"crash|lag|stop|buffer|won.t play"),
    ("catalog", r"lyric|search|recommend|song.*missing"),
    ("support", r"support|customer service"),
    ("usability", r"\bads?\b|shuffle|queue|button|interface"),
]


class FakeClient:
    model = "fake-model"
    simulated = True

    def __init__(self, behaviors=None, seed=0, latency_s=0.0):
        """`behaviors` is a list consumed one per call: ok, drop_one, dup_one, bad_segment, bad_json, truncated,
        rate_limit, server_error, timeout, no_credit. After the list runs out, every call is ok."""
        self.behaviors = list(behaviors or [])
        self.rng = random.Random(seed)
        self.latency_s = latency_s
        self.calls = 0

    def _label(self, number, segs):
        text = " ".join(segs).lower()
        topic = next((t for t, pattern in _TOPIC_WORDS if re.search(pattern, text)), "other")
        negative = bool(re.search(r"bad|worst|hate|can.t|cannot|not|crash|too many|useless|fix", text))
        if re.search(r"uninstall|cancel|switching|delete (this|the) app", text):
            intent = "cancellation"
        elif negative:
            intent = "complaint"
        elif re.search(r"please add|wish|would be nice|need", text):
            intent = "request"
        elif re.search(r"good|great|love|nice|best|awesome|excellent", text):
            intent = "praise"
        else:
            intent = "unclear"
        severity = {"cancellation": 2, "complaint": 3 if topic != "other" else 2}.get(intent, 1)
        sentiment = -0.5 if intent in ("complaint", "cancellation") else 0.5 if intent == "praise" else 0
        item = {"i": number, "t": topic, "n": intent, "s": severity, "m": sentiment, "q": 1, "f": None}
        if ALWAYS_INVALID_MARKER.lower() in text:
            item["q"] = len(segs) + 7   # a segment number that does not exist
        return item

    def enrich(self, system_prompt, user_message, schema, max_output_tokens):
        self.calls += 1
        request_id = f"fake-{uuid.uuid4().hex}"   # unique across runs, like real provider request IDs
        behavior = self.behaviors.pop(0) if self.behaviors else "ok"
        if self.latency_s:
            time.sleep(self.latency_s)
        if behavior == "rate_limit":
            raise TransientError("simulated 429 rate limit", request_id)
        if behavior == "server_error":
            raise TransientError("simulated 500 server error", request_id)
        if behavior == "timeout":
            raise TransientError("simulated timeout", request_id, usage_known=False)
        if behavior == "no_credit":
            raise PermanentError("simulated 429 insufficient_quota")

        reviews = [(int(n), [line.split("> ", 1)[1] for line in body.strip().split("\n")])
                   for n, body in _REVIEW.findall(user_message)]
        items = [self._label(n, segs) for n, segs in reviews]
        if behavior == "drop_one" and items:
            items.pop(self.rng.randrange(len(items)))
        elif behavior == "dup_one" and items:
            items.append(dict(items[0]))
        elif behavior == "bad_segment" and items:
            items[-1]["q"] = 999
        text = json.dumps({"r": items}, separators=(",", ":"))
        complete = True
        if behavior == "bad_json":
            text = text[: len(text) // 2]
        elif behavior == "truncated":
            text, complete = text[: len(text) // 3], False

        prompt_tokens = (len(system_prompt) + len(user_message)) // 4
        cached = len(system_prompt) // 4 if self.calls > 1 else 0   # simulate provider prompt caching
        usage = {"input": prompt_tokens, "cached_input": cached, "output": len(text) // 4, "reasoning": 0}
        return Response(text=text, request_id=request_id, complete=complete, usage=usage)
