"""OpenAI Responses API client for the enrichment role. Standard library only (urllib); no OpenAI SDK needed.

Request shape follows the official docs (checked 2026-10-03):
  - POST https://api.openai.com/v1/responses
  - structured output: text.format = {type: json_schema, name, schema, strict}
  - reasoning.effort = "none" (GPT-6 Luna's default is "medium", which is not the cheapest)
  - prompt_cache_options.mode = "explicit" with a breakpoint on the instructions only. Implicit mode would put a
    breakpoint after each unique batch of reviews and charge every request a 1.25x cache write.
  - store = false: responses are not kept on OpenAI's side.
The API key is read from the environment and is never logged, returned, or written anywhere.
"""

import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import config
from .clients import PermanentError, Response, TransientError

API_URL = "https://api.openai.com/v1/responses"


def load_dotenv(path=config.REPO / ".env"):
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win; values are never printed."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


def parse_usage(usage):
    usage = usage or {}
    details_in = usage.get("input_tokens_details") or {}
    details_out = usage.get("output_tokens_details") or {}
    return {"input": int(usage.get("input_tokens", 0)), "cached_input": int(details_in.get("cached_tokens", 0) or 0),
            "cache_write": int(details_in.get("cache_write_tokens", 0) or 0),
            "output": int(usage.get("output_tokens", 0)), "reasoning": int(details_out.get("reasoning_tokens", 0) or 0)}


def parse_response(body):
    """Return (text, complete). A refusal or a response without text yields text that will fail validation."""
    texts, refused = [], False
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "refusal":
                refused = True
    complete = body.get("status") == "completed" and not refused
    return "".join(texts), complete


class OpenAIClient:
    simulated = False

    def __init__(self, model=config.ENRICH_MODEL, effort=config.ENRICH_EFFORT, timeout_s=config.REQUEST_TIMEOUT_S,
                 opener=urllib.request.urlopen):
        load_dotenv()
        self._key = os.environ.get("OPENAI_API_KEY", "")
        if not self._key:
            raise PermanentError("OPENAI_API_KEY is not set. Paste it into spotify-pipeline/.env (never into chat).")
        self.model, self.effort, self.timeout_s, self._open = model, effort, timeout_s, opener

    def build_body(self, system_prompt, user_message, schema, max_output_tokens):
        return {
            "model": self.model,
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": system_prompt,
                                                    "prompt_cache_breakpoint": {"mode": "explicit"}}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_message}]},
            ],
            "reasoning": {"effort": self.effort},
            "text": {"format": {"type": "json_schema", "name": schema["name"], "schema": schema["schema"],
                                "strict": schema["strict"]}},
            "max_output_tokens": max_output_tokens,
            "prompt_cache_options": {"mode": "explicit"},
            "store": False,
        }

    def enrich(self, system_prompt, user_message, schema, max_output_tokens):
        body = json.dumps(self.build_body(system_prompt, user_message, schema, max_output_tokens)).encode("utf-8")
        request = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        try:
            with self._open(request, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                request_id = payload.get("id") or resp.headers.get("x-request-id") or f"no-id-{uuid.uuid4().hex}"
        except urllib.error.HTTPError as e:
            request_id = (e.headers.get("x-request-id") if e.headers else None) or f"http-{e.code}-{uuid.uuid4().hex}"
            try:
                error = json.loads(e.read().decode("utf-8")).get("error") or {}
            except (ValueError, AttributeError):
                error = {}
            detail = f"HTTP {e.code} {error.get('code') or error.get('type') or ''}: {(error.get('message') or '')[:200]}"
            if e.code == 429 and error.get("code") == "insufficient_quota":
                raise PermanentError(detail) from None
            if e.code in (408, 409, 429) or e.code >= 500:
                raise TransientError(detail, request_id) from None
            raise PermanentError(detail) from None          # 400 bad request, 401/403 auth, 404 model
        except (TimeoutError, socket.timeout) as e:
            # The provider may have processed (and billed) this request; usage is unknown.
            raise TransientError(f"timeout after {self.timeout_s}s", f"timeout-{uuid.uuid4().hex}", usage_known=False) from None
        except urllib.error.URLError as e:
            raise TransientError(f"connection error: {e.reason}", f"connection-{uuid.uuid4().hex}", usage_known=False) from None

        text, complete = parse_response(payload)
        return Response(text=text, request_id=request_id, complete=complete, usage=parse_usage(payload.get("usage")))
