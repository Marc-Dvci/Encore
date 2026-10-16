"""Qloo Taste AI client.

Every request goes through `Qloo.get`, which
- refuses to send any protected string (a resident's or carer's name, a care note) to Qloo,
- answers from the private server-side cache when it can,
- retries a failed call once, then raises `QlooUnavailable`,
- writes one row per request to the request log that the "What Qloo saw" page shows.

The API key travels only in the X-Api-Key header and never appears in the log.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import re
import time
from typing import Any, Iterable, Optional, Sequence, Union
from urllib.parse import urlencode

import httpx

from .config import Config
from .store import Store

Params = Union[dict[str, Any], Sequence[tuple[str, Any]]]

# Requests made while a tool runs are collected here so the agent trace can show them.
_trace: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("qloo_trace", default=None)

AGE_BUCKET = "55_and_older"


class QlooUnavailable(RuntimeError):
    pass


class PrivacyViolation(RuntimeError):
    pass


FREE_TEXT_KEYS = {"query", "filter.query", "signal.location.query", "filter.location.query"}
_STRUCTURED = re.compile(r"^[\w:.,\- ]{0,4000}$")


class PrivacyGuard:
    """An allow-list for what may leave the building.

    Free-text parameters may only carry text registered here: a favourite as the family typed it, a
    hometown, the home's own town, a tag search term. Every other parameter must be structured (an
    entity ID, a tag URN, a year, a number, a country). Names and care notes are registered as
    protected, and a request containing one is refused even inside a structured value.
    """

    def __init__(self) -> None:
        self._allowed: set[str] = set()
        self._protected: list[re.Pattern] = []

    def allow(self, values: Iterable[Optional[str]]) -> None:
        self._allowed.update(v.strip().lower() for v in values if v and v.strip())

    def protect(self, values: Iterable[Optional[str]]) -> None:
        for v in values:
            if v and len(v.strip()) >= 3:
                self._protected.append(re.compile(r"\b" + re.escape(v.strip().lower()) + r"\b"))

    def check(self, norm: list[tuple[str, str]]) -> None:
        for k, v in norm:
            low = v.lower()
            if k in FREE_TEXT_KEYS:
                if low.strip() not in self._allowed:
                    raise PrivacyViolation(f"unregistered free text in {k}")
                continue
            if not _STRUCTURED.match(v):
                raise PrivacyViolation(f"unstructured value in {k}")
            for p in self._protected:
                if p.search(low):
                    raise PrivacyViolation(f"a protected value was about to be sent in {k}")


def _norm_params(params: Params) -> list[tuple[str, str]]:
    items = params.items() if isinstance(params, dict) else params
    out: list[tuple[str, str]] = []
    for k, v in items:
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        elif isinstance(v, bool):
            v = "true" if v else "false"
        out.append((k, str(v)))
    return sorted(out)


def start_trace() -> list:
    t: list = []
    _trace.set(t)
    return t


class Qloo:
    def __init__(self, cfg: Config, store: Store, guard: Optional[PrivacyGuard] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.cfg = cfg
        self.store = store
        self.guard = guard or PrivacyGuard()
        self._http = httpx.AsyncClient(base_url=cfg.qloo_base_url, timeout=httpx.Timeout(30.0, connect=10.0),
                                       transport=transport)
        self._sem = asyncio.Semaphore(3)
        self._pace = asyncio.Lock()
        self._next_slot = 0.0
        self.min_interval = 0.25  # at most four requests a second
        self.live_calls = 0

    @property
    def live(self) -> bool:
        return bool(self.cfg.qloo_api_key)

    async def get(self, path: str, params: Params, purpose: str) -> dict:
        norm = _norm_params(params)
        self.guard.check(norm)
        query = urlencode(norm)
        key = hashlib.sha256(f"{path}?{query}".encode()).hexdigest()
        hit = self.store.one("SELECT body, fetched_at FROM qloo_cache WHERE key=?", (key,))
        fresh = hit and (time.time() - hit["fetched_at"]) < self.cfg.qloo_cache_days * 86400
        if hit and (fresh or not self.live):
            body = json.loads(hit["body"])
            self._log(purpose, path, norm, 200, 0, True, body)
            return body
        if not self.live:
            raise QlooUnavailable("no Qloo key configured and no cached answer")
        body, status, ms = await self._fetch(path, norm)
        if status >= 400:
            self._log(purpose, path, norm, status, ms, False, None)
            if hit:  # stale cache beats no answer
                return json.loads(hit["body"])
            raise QlooUnavailable(f"Qloo answered {status}: {json.dumps(body)[:200]}")
        self.store.x("INSERT INTO qloo_cache(key,path,body,fetched_at) VALUES(?,?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET body=excluded.body, fetched_at=excluded.fetched_at",
                     (key, path, json.dumps(body, ensure_ascii=False), time.time()))
        self._log(purpose, path, norm, status, ms, False, body)
        return body

    async def _fetch(self, path: str, norm: list[tuple[str, str]]) -> tuple[dict, int, int]:
        last: Optional[Exception] = None
        async with self._sem:
            for attempt in range(4):
                async with self._pace:
                    wait = self._next_slot - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._next_slot = time.monotonic() + self.min_interval
                t0 = time.perf_counter()
                try:
                    r = await self._http.get(path, params=norm, headers={"X-Api-Key": self.cfg.qloo_api_key or ""})
                    ms = round((time.perf_counter() - t0) * 1000)
                    self.live_calls += 1
                    if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                        await asyncio.sleep((2.0 if r.status_code == 429 else 0.6) * (attempt + 1))
                        continue
                    try:
                        body = r.json()
                    except ValueError:
                        body = {"error": r.text[:300]}
                    return body, r.status_code, ms
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last = e
                    await asyncio.sleep(0.5)
        raise QlooUnavailable(f"Qloo unreachable: {type(last).__name__}")

    def _log(self, purpose: str, path: str, norm: list[tuple[str, str]], status: int, ms: int, cached: bool,
             body: Optional[dict]) -> None:
        n = _count(body)
        self.store.x("INSERT INTO qloo_log(at,purpose,path,params,status,ms,cached,results) VALUES(?,?,?,?,?,?,?,?)",
                     (time.time(), purpose, path, json.dumps(norm), status, ms, int(cached), n))
        t = _trace.get()
        if t is not None:
            t.append({"purpose": purpose, "path": path, "params": norm, "status": status, "cached": cached,
                      "results": n, "ms": ms})

    # ---- typed helpers -------------------------------------------------------------------------

    async def search(self, query: str, types: Optional[str] = None, take: int = 5, purpose: str = "resolve") -> list[dict]:
        body = await self.get("/search", {"query": query, "types": types, "take": take}, purpose)
        return body.get("results") or []

    async def entities(self, ids: Sequence[str], purpose: str = "entity details") -> list[dict]:
        if not ids:
            return []
        body = await self.get("/entities", {"entity_ids": list(ids)}, purpose)
        res = body.get("results")
        return res if isinstance(res, list) else (res or {}).get("entities", [])

    async def insights(self, params: Params, purpose: str) -> list[dict]:
        body = await self.get("/v2/insights", params, purpose)
        res = body.get("results") or {}
        return res.get("entities") or res.get("tags") or []

    async def tags(self, query: str, purpose: str = "tag lookup", take: int = 15) -> list[dict]:
        body = await self.get("/v2/tags", {"filter.query": query, "take": take}, purpose)
        return (body.get("results") or {}).get("tags") or []

    async def compare(self, a: Sequence[str], b: Sequence[str], purpose: str, take: int = 40) -> dict:
        body = await self.get("/v2/analysis/compare", {"a.signal.interests.entities": list(a),
                                                       "b.signal.interests.entities": list(b), "take": take}, purpose)
        return body.get("results") or {}

    def recent_log(self, limit: int = 200) -> list[dict]:
        rows = self.store.q("SELECT * FROM qloo_log ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["params"] = json.loads(r["params"])
        return rows

    async def aclose(self) -> None:
        await self._http.aclose()


def _count(body: Optional[dict]) -> Optional[int]:
    if not body:
        return None
    res = body.get("results")
    if isinstance(res, list):
        return len(res)
    if isinstance(res, dict):
        for k in ("entities", "tags"):
            if isinstance(res.get(k), list):
                return len(res[k])
    return None
