"""A stand-in for Gemini on Vertex AI, used by the tests.

It answers generateContent with scripted replies (a reply body, an HTTP status or a transport error)
and records every request, so tests can check what was sent and how failures are handled.
"""
from __future__ import annotations

import json
from typing import Any, Union

import httpx

Reply = Union[dict, int, Exception]


def text_reply(text: str, thought: str | None = None) -> dict:
    parts: list[dict] = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    return {"candidates": [{"content": {"role": "model", "parts": parts}}], "usageMetadata": {"totalTokenCount": 7}}


def json_reply(value: Any) -> dict:
    return text_reply(json.dumps(value))


def call_reply(name: str, args: dict | None = None) -> dict:
    part = {"functionCall": {"name": name, "args": args or {}}, "thoughtSignature": "sig-" + name}
    return {"candidates": [{"content": {"role": "model", "parts": [part]}}]}


class FakeGemini:
    def __init__(self, replies: list[Reply] | None = None) -> None:
        self.replies: list[Reply] = list(replies or [])
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.replies.pop(0) if self.replies else text_reply("{}")
        if isinstance(r, Exception):
            raise r
        if isinstance(r, int):
            return httpx.Response(r, json={"error": {"code": r, "message": "synthetic failure"}})
        return httpx.Response(200, json=r)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]
