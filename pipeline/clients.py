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
    usage: dict = field(default_factory=dict)  # input (total), cached_input, cache_write, output, reasoning


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

    def __init__(self, behaviors=None, seed=0, latency_s=0.0, perturb_every=0):
        """`behaviors` is a list consumed one per call: ok, drop_one, dup_one, bad_segment, bad_json, truncated,
        rate_limit, server_error, timeout, no_credit. After the list runs out, every call is ok."""
        self.behaviors = list(behaviors or [])
        self.rng = random.Random(seed)
        self.latency_s = latency_s
        self.calls = 0
        self.perturb_every = perturb_every   # every k-th item gets a different topic (simulates a disagreeing verifier)
        self.messages = []                   # what was sent, so tests can check what each role saw

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
        paywall = topic == "billing" and bool(re.search(r"lyric|skip|queue|repeat|shuffle", text))
        item = {"i": number, "t": topic, "n": intent, "s": severity, "m": sentiment, "q": 1, "p": paywall, "f": None}
        if ALWAYS_INVALID_MARKER.lower() in text:
            item["q"] = len(segs) + 7   # a segment number that does not exist
        return item

    def enrich(self, system_prompt, user_message, schema, max_output_tokens):
        self.calls += 1
        self.messages.append((system_prompt, user_message))
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

        if schema["name"].startswith("group"):
            return self._group(user_message, request_id, behavior, system_prompt)
        reviews = [(int(n), [line.split("> ", 1)[1] for line in body.strip().split("\n")])
                   for n, body in _REVIEW.findall(user_message)]
        items_raw = [self._label(n, segs) for n, segs in reviews]
        if self.perturb_every:
            order = [t for t, _ in _TOPIC_WORDS] + ["other"]
            for item in items_raw[self.perturb_every - 1::self.perturb_every]:
                item["t"] = order[(order.index(item["t"]) + 1) % len(order)]
        keys = schema["schema"]["properties"]["r"]["items"]["required"]   # answer only what this role's schema asks
        items = [{k: v for k, v in item.items() if k in keys} for item in items_raw]
        if behavior == "drop_one" and items:
            items.pop(self.rng.randrange(len(items)))
        elif behavior == "dup_one" and items:
            items.append(dict(items[0]))
        elif behavior == "bad_segment" and items:
            items[-1]["q" if "q" in items[-1] else "s"] = 999
        text = json.dumps({"r": items}, separators=(",", ":"))
        complete = True
        if behavior == "bad_json":
            text = text[: len(text) // 2]
        elif behavior == "truncated":
            text, complete = text[: len(text) // 3], False

        prompt_tokens = (len(system_prompt) + len(user_message)) // 4
        system_tokens = len(system_prompt) // 4      # simulate explicit caching of the instructions only
        cached, written = (system_tokens, 0) if self.calls > 1 else (0, system_tokens)
        usage = {"input": prompt_tokens, "cached_input": cached, "cache_write": written,
                 "output": len(text) // 4, "reasoning": 0}
        return Response(text=text, request_id=request_id, complete=complete, usage=usage)

    def _group(self, message, request_id, behavior, system_prompt):
        issues, current = {}, None
        for line in message.splitlines():
            if line.startswith("ISSUE "):
                current = line.split()[1]
                issues[current] = []
            elif line.startswith("[") and current:
                issues[current].append(line[1:line.index("]")])
        items = [{"id": iid, "name": f"Fake name: {iid}"[:60], "description": "Fake description of the examples.",
                  "examples": ex[:2]} for iid, ex in issues.items()]
        if behavior == "bad_names" and items:
            items[0]["description"] = "Affects 1,234 users"      # numbers are not allowed in descriptions
            items[0]["examples"] = ["invented-id"]               # an ID outside the evidence pack
        text = json.dumps({"issues": items})
        if behavior == "bad_json":
            text = text[: len(text) // 2]
        usage = {"input": (len(system_prompt) + len(message)) // 4, "cached_input": 0, "cache_write": 0,
                 "output": len(text) // 4, "reasoning": 0}
        return Response(text=text, request_id=request_id, complete=True, usage=usage)
