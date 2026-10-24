"""One gateway for every model call (Gemini on Vertex AI).

The model writes words: session openers, conversation prompts, the agent's replies. It never
produces a number, a ranking or a pick; those come from code and Qloo. A request is answered from
the private cache when it can be, then live while the budget allows it. When the model is
unavailable every caller has a template path, so the product keeps working.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import Config

log = logging.getLogger("encore.ai")


class AIUnavailable(RuntimeError):
    pass


def request_key(task: str, payload: Any) -> str:
    return hashlib.sha256((task + json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:32]


class AI:
    def __init__(self, cfg: Config, kv_get, kv_set, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.cfg = cfg
        self.kv_get, self.kv_set = kv_get, kv_set
        self.cache_dir: Path = cfg.data_dir / "ai_cache"
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0), transport=transport)
        self._visitors: dict[str, list[float]] = {}

    @property
    def model(self) -> str:
        return self.cfg.gemini_model

    def why_not_live(self, visitor: Optional[str]) -> Optional[str]:
        cfg = self.cfg
        if cfg.ai_provider != "gemini" or not cfg.gemini_api_key:
            return "no model configured"
        today = datetime.now(timezone.utc).date()
        if cfg.ai_until and today > cfg.ai_until:
            return "model access ended"
        if int(self.kv_get(f"ai_calls:{today.isoformat()}") or 0) >= cfg.ai_daily_cap:
            return "daily model budget used"
        if visitor:
            now = time.time()
            hits = [t for t in self._visitors.get(visitor, []) if now - t < 3600]
            self._visitors[visitor] = hits
            if len(hits) >= cfg.ai_per_visitor_hourly:
                return "hourly model budget for this visitor used"
        return None

    def _spend(self, visitor: Optional[str]) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        self.kv_set(f"ai_calls:{today}", str(int(self.kv_get(f"ai_calls:{today}") or 0) + 1))
        if visitor:
            self._visitors.setdefault(visitor, []).append(time.time())

    def calls_today(self) -> int:
        return int(self.kv_get(f"ai_calls:{datetime.now(timezone.utc).date().isoformat()}") or 0)

    def _cached(self, task: str, key: str) -> Optional[dict]:
        f = self.cache_dir / task / f"{key}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def _store(self, task: str, key: str, value: dict) -> None:
        d = self.cache_dir / task
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")

    async def _generate(self, body: dict) -> dict:
        # The key travels in a header, never in the URL, so no request log can record it.
        url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.cfg.gemini_api_key or ""}
        r = None
        for attempt in range(2):
            try:
                r = await self._http.post(url, json=body, headers=headers)
                if r.status_code in (429, 500, 503) and attempt == 0:
                    continue
                break
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt == 1:
                    raise AIUnavailable(f"model unreachable: {type(e).__name__}")
        assert r is not None
        if r.status_code >= 400:
            raise AIUnavailable(f"model error {r.status_code}")
        return r.json()

    async def json(self, task: str, system: str, prompt: str, schema: dict, visitor: Optional[str] = None) -> dict:
        key = request_key(task, {"system": system, "prompt": prompt, "schema": schema, "model": self.model})
        hit = self._cached(task, key)
        if hit is not None:
            return hit["output"]
        why = self.why_not_live(visitor)
        if why:
            raise AIUnavailable(why)
        self._spend(visitor)
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                                     "temperature": 0.4, "thinkingConfig": {"thinkingLevel": "LOW"}}}
        t0 = time.perf_counter()
        res = await self._generate(body)
        try:
            text = "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"] if not p.get("thought"))
            out = json.loads(text)
        except (KeyError, IndexError, ValueError) as e:
            raise AIUnavailable(f"unparseable model output: {e}")
        self._store(task, key, {"task": task, "model": self.model, "ms": round((time.perf_counter() - t0) * 1000),
                                "usage": res.get("usageMetadata"), "output": out})
        return out

    async def turn(self, system: str, contents: list[dict], tools: list[dict], visitor: Optional[str] = None) -> dict:
        """One function-calling turn; model parts are returned unchanged so thought signatures round-trip."""
        key = request_key("agent", {"system": system, "contents": contents, "tools": tools, "model": self.model})
        hit = self._cached("agent", key)
        if hit is not None:
            return hit["output"]
        why = self.why_not_live(visitor)
        if why:
            raise AIUnavailable(why)
        self._spend(visitor)
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "tools": [{"functionDeclarations": tools}],
                "generationConfig": {"temperature": 0.2, "thinkingConfig": {"thinkingLevel": "LOW"}}}
        res = await self._generate(body)
        try:
            content = res["candidates"][0]["content"]
        except (KeyError, IndexError):
            raise AIUnavailable("empty model turn")
        self._store("agent", key, {"model": self.model, "output": content})
        return content

    async def aclose(self) -> None:
        await self._http.aclose()
