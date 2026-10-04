"""Offline tests for the OpenAI client: the network is replaced by canned responses, so nothing is sent or billed.
Response shapes follow the Responses API docs; the paid smoke test confirms them against the real service."""

import email.message
import io
import json
import os
import socket
import unittest
import urllib.error
from unittest import mock

from pipeline import config
from pipeline.clients import PermanentError, TransientError
from pipeline.enrich import cost_usd
from pipeline.openai_client import OpenAIClient

SCHEMA = json.loads((config.PROMPTS / "enrich_v1.schema.json").read_text())
DUMMY_KEY = "test-key-not-real-0000"


class Canned:
    def __init__(self, payload, headers=None):
        self.payload, self.headers = payload, headers or {}

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, error):
    headers = email.message.Message()
    headers["x-request-id"] = "req_err_1"
    return urllib.error.HTTPError(config.REPO.as_uri(), code, "error", headers, io.BytesIO(json.dumps({"error": error}).encode()))


OK_BODY = {
    "id": "resp_123", "status": "completed",
    "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"r":[]}'}]}],
    "usage": {"input_tokens": 2500, "input_tokens_details": {"cached_tokens": 1300, "cache_write_tokens": 0},
              "output_tokens": 1500, "output_tokens_details": {"reasoning_tokens": 0}},
}


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": DUMMY_KEY})
class OpenAIClientTests(unittest.TestCase):
    def client(self, behavior):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            if isinstance(behavior, Exception):
                raise behavior
            return Canned(behavior)
        return OpenAIClient(opener=opener), sent

    def call(self, client):
        return client.enrich("SYSTEM PROMPT", "<reviews>\n#1\n<1> hi\n</reviews>", SCHEMA, 4000)

    def test_request_body_matches_documented_shape(self):
        client, sent = self.client(OK_BODY)
        self.call(client)
        body = json.loads(sent[0].data)
        self.assertEqual(sent[0].full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertEqual(body["reasoning"], {"effort": "none"})
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["max_output_tokens"], 4000)
        self.assertEqual(body["prompt_cache_options"], {"mode": "explicit"})
        self.assertEqual(body["input"][0]["content"][0]["prompt_cache_breakpoint"], {"mode": "explicit"})
        self.assertNotIn("prompt_cache_breakpoint", body["input"][1]["content"][0], "reviews must not be cached")
        self.assertFalse(body["store"])
        self.assertNotIn(DUMMY_KEY, sent[0].data.decode(), "key only in the header")

    def test_usage_parsing_and_cost(self):
        client, _ = self.client(OK_BODY)
        resp = self.call(client)
        self.assertEqual(resp.request_id, "resp_123")
        self.assertTrue(resp.complete)
        self.assertEqual(resp.usage, {"input": 2500, "cached_input": 1300, "cache_write": 0, "output": 1500, "reasoning": 0})
        # 1200 ordinary x 0.10 + 1300 cached x 0.01 + 1500 output x 0.50, per million
        self.assertAlmostEqual(cost_usd("gpt-6-luna", resp.usage), (1200 * 0.10 + 1300 * 0.01 + 1500 * 0.50) / 1e6)

    def test_doubling_rates_doubles_cost(self):
        usage = {"input": 2500, "cached_input": 1000, "cache_write": 300, "output": 1500, "reasoning": 40}
        base = cost_usd("gpt-6-luna", usage)
        with mock.patch.dict(config.RATES, {"gpt-6-luna": {k: v * 2 if isinstance(v, float) else v
                                                           for k, v in config.RATES["gpt-6-luna"].items()}}):
            self.assertAlmostEqual(cost_usd("gpt-6-luna", usage), 2 * base)

    def test_incomplete_and_refusal_are_not_complete(self):
        client, _ = self.client({**OK_BODY, "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}})
        self.assertFalse(self.call(client).complete)
        refusal = {**OK_BODY, "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}
        client, _ = self.client(refusal)
        self.assertFalse(self.call(client).complete)

    def test_error_classification(self):
        cases = [
            (http_error(429, {"code": "rate_limit_exceeded", "message": "slow down"}), TransientError),
            (http_error(500, {"type": "server_error", "message": "oops"}), TransientError),
            (http_error(429, {"code": "insufficient_quota", "message": "no credit"}), PermanentError),
            (http_error(401, {"code": "invalid_api_key", "message": "bad key"}), PermanentError),
            (http_error(400, {"code": "invalid_request_error", "message": "bad"}), PermanentError),
            (socket.timeout("timed out"), TransientError),
            (urllib.error.URLError("no network"), TransientError),
        ]
        for error, expected in cases:
            client, _ = self.client(error)
            with self.assertRaises(expected) as ctx:
                self.call(client)
            self.assertNotIn(DUMMY_KEY, str(ctx.exception))
        client, _ = self.client(socket.timeout("timed out"))
        with self.assertRaises(TransientError) as ctx:
            self.call(client)
        self.assertFalse(ctx.exception.usage_known, "timeouts may have been billed")

    def test_missing_key_is_a_clear_permanent_error(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}), mock.patch("pipeline.openai_client.load_dotenv"):
            with self.assertRaises(PermanentError):
                OpenAIClient(opener=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
