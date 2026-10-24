"""The model gateway: the key stays out of URLs and logs, budgets hold, and every failure has a way out."""
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from encore.ai import AI, AIUnavailable, request_key
from encore.app import create_app
from tests.conftest import make_config
from tests.fake_gemini import FakeGemini, call_reply, json_reply, text_reply

SECRET = "AQ.test-gemini-key-0123456789"
SCHEMA = {"type": "OBJECT", "properties": {"a": {"type": "INTEGER"}}}


def make_ai(tmp_path, fake: FakeGemini, kv: dict | None = None, **over) -> AI:
    kv = {} if kv is None else kv
    base = dict(ai_provider="gemini", gemini_api_key=SECRET)
    base.update(over)
    return AI(make_config(tmp_path, **base), kv.get, kv.__setitem__, transport=fake.transport())


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---- the key ----------------------------------------------------------------------------------

async def test_the_key_travels_in_a_header_and_never_in_the_url(tmp_path):
    fake = FakeGemini([json_reply({"a": 1})])
    ai = make_ai(tmp_path, fake)
    await ai.json("t", "system", "prompt", SCHEMA)
    req = fake.requests[0]
    assert SECRET not in str(req.url)
    assert not req.url.query
    assert req.headers["x-goog-api-key"] == SECRET
    assert req.url.path.endswith("/models/gemini-test:generateContent")
    await ai.aclose()


async def test_httpx_request_lines_never_carry_the_key(tmp_path, caplog):
    # Even with httpx logging every request at INFO, the logged URL has nothing secret in it.
    caplog.set_level(logging.INFO, logger="httpx")
    fake = FakeGemini([json_reply({"a": 1}), call_reply("list_people")])
    ai = make_ai(tmp_path, fake)
    await ai.json("t", "system", "prompt", SCHEMA)
    await ai.turn("system", [{"role": "user", "parts": [{"text": "hi"}]}], [])
    assert "HTTP Request" in caplog.text
    assert SECRET not in caplog.text
    await ai.aclose()


def test_importing_the_app_keeps_httpx_quiet():
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


async def test_mounting_mcp_does_not_turn_request_logging_back_on(enc):
    create_app(enc, warm=False)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


# ---- budgets ----------------------------------------------------------------------------------

@pytest.mark.parametrize("over, reason", [
    ({"ai_provider": "none"}, "no model configured"),
    ({"gemini_api_key": None}, "no model configured"),
    ({"ai_until": date.today() - timedelta(days=2)}, "model access ended"),
])
def test_the_model_is_off_when_configuration_says_so(tmp_path, over, reason):
    assert make_ai(tmp_path, FakeGemini(), **over).why_not_live(None) == reason


def test_the_model_is_live_on_its_last_day(tmp_path):
    assert make_ai(tmp_path, FakeGemini(), ai_until=date.today() + timedelta(days=1)).why_not_live(None) is None


def test_the_daily_budget_stops_live_calls(tmp_path):
    kv = {f"ai_calls:{today()}": "10"}
    assert make_ai(tmp_path, FakeGemini(), kv).why_not_live(None) == "daily model budget used"
    kv[f"ai_calls:{today()}"] = "9"
    assert make_ai(tmp_path, FakeGemini(), kv).why_not_live(None) is None


def test_each_visitor_has_an_hourly_budget_of_their_own(tmp_path):
    ai = make_ai(tmp_path, FakeGemini())
    for _ in range(5):
        ai._spend("v1")
    assert ai.why_not_live("v1") == "hourly model budget for this visitor used"
    assert ai.why_not_live("v2") is None
    assert ai.why_not_live(None) is None


def test_an_hour_later_the_visitor_budget_is_back(tmp_path):
    ai = make_ai(tmp_path, FakeGemini())
    ai._visitors["v1"] = [time.time() - 3700] * 5
    assert ai.why_not_live("v1") is None
    assert ai._visitors["v1"] == []


async def test_live_calls_are_counted_per_day(tmp_path):
    fake = FakeGemini([json_reply({"a": 1}), json_reply({"a": 2})])
    kv: dict = {}
    ai = make_ai(tmp_path, fake, kv)
    await ai.json("t", "s", "one", SCHEMA)
    await ai.json("t", "s", "two", SCHEMA)
    assert ai.calls_today() == 2 and kv[f"ai_calls:{today()}"] == "2"
    await ai.aclose()


async def test_a_refused_call_sends_nothing(tmp_path):
    fake = FakeGemini()
    ai = make_ai(tmp_path, fake, ai_provider="none")
    with pytest.raises(AIUnavailable, match="no model configured"):
        await ai.json("t", "s", "p", SCHEMA)
    assert fake.requests == []
    await ai.aclose()


# ---- the private cache ------------------------------------------------------------------------

async def test_the_same_request_is_answered_from_the_cache(tmp_path):
    fake = FakeGemini([json_reply({"a": 1})])
    ai = make_ai(tmp_path, fake)
    assert await ai.json("t", "s", "p", SCHEMA) == {"a": 1}
    assert await ai.json("t", "s", "p", SCHEMA) == {"a": 1}
    assert len(fake.requests) == 1 and ai.calls_today() == 1
    await ai.aclose()


async def test_the_cache_answers_after_the_model_is_switched_off(tmp_path):
    fake = FakeGemini([json_reply({"a": 1})])
    first = make_ai(tmp_path, fake)
    await first.json("t", "s", "p", SCHEMA)
    await first.aclose()
    off = make_ai(tmp_path, FakeGemini(), ai_provider="none")
    assert await off.json("t", "s", "p", SCHEMA) == {"a": 1}
    await off.aclose()


async def test_the_cache_file_keeps_model_timing_and_usage(tmp_path):
    ai = make_ai(tmp_path, FakeGemini([json_reply({"a": 3})]))
    await ai.json("words", "s", "p", SCHEMA)
    files = list((tmp_path / "ai_cache" / "words").glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["model"] == "gemini-test" and saved["output"] == {"a": 3}
    assert saved["usage"] == {"totalTokenCount": 7} and saved["ms"] >= 0
    assert SECRET not in files[0].read_text(encoding="utf-8")
    await ai.aclose()


def test_request_keys_ignore_dict_order_and_separate_tasks():
    a = request_key("t", {"x": 1, "y": [1, 2]})
    assert a == request_key("t", {"y": [1, 2], "x": 1})
    assert a != request_key("u", {"x": 1, "y": [1, 2]})
    assert a != request_key("t", {"x": 1, "y": [2, 1]})
    assert len(a) == 32


# ---- what is sent and what comes back -----------------------------------------------------------

async def test_json_requests_ask_for_structured_output(tmp_path):
    fake = FakeGemini([json_reply({"a": 1})])
    ai = make_ai(tmp_path, fake)
    await ai.json("t", "be brief", "the facts", SCHEMA)
    body = fake.bodies()[0]
    assert body["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert body["contents"] == [{"role": "user", "parts": [{"text": "the facts"}]}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"] == SCHEMA
    await ai.aclose()


async def test_thinking_parts_are_left_out_of_the_answer(tmp_path):
    ai = make_ai(tmp_path, FakeGemini([text_reply('{"a": 5}', thought="{ not json")]))
    assert await ai.json("t", "s", "p", SCHEMA) == {"a": 5}
    await ai.aclose()


async def test_unparseable_output_is_refused(tmp_path):
    ai = make_ai(tmp_path, FakeGemini([text_reply("Sure! Here you go")]))
    with pytest.raises(AIUnavailable, match="unparseable"):
        await ai.json("t", "s", "p", SCHEMA)
    await ai.aclose()


async def test_a_turn_returns_the_model_parts_unchanged(tmp_path):
    fake = FakeGemini([call_reply("lounge_film", {"max_minutes": 90})])
    ai = make_ai(tmp_path, fake)
    tools = [{"name": "lounge_film", "parameters": {"type": "OBJECT", "properties": {}}}]
    content = await ai.turn("s", [{"role": "user", "parts": [{"text": "film?"}]}], tools)
    assert content["parts"][0]["thoughtSignature"] == "sig-lounge_film"
    assert fake.bodies()[0]["tools"] == [{"functionDeclarations": tools}]
    await ai.aclose()


async def test_an_empty_turn_is_refused(tmp_path):
    ai = make_ai(tmp_path, FakeGemini([{"candidates": []}]))
    with pytest.raises(AIUnavailable, match="empty model turn"):
        await ai.turn("s", [{"role": "user", "parts": [{"text": "x"}]}], [])
    await ai.aclose()


# ---- failures ---------------------------------------------------------------------------------

@pytest.mark.parametrize("status", [429, 500, 503])
async def test_one_busy_answer_is_retried(tmp_path, status):
    fake = FakeGemini([status, json_reply({"a": 1})])
    ai = make_ai(tmp_path, fake)
    assert await ai.json("t", "s", "p", SCHEMA) == {"a": 1}
    assert len(fake.requests) == 2
    await ai.aclose()


async def test_two_busy_answers_give_up(tmp_path):
    fake = FakeGemini([503, 503])
    ai = make_ai(tmp_path, fake)
    with pytest.raises(AIUnavailable, match="model error 503"):
        await ai.json("t", "s", "p", SCHEMA)
    assert len(fake.requests) == 2
    await ai.aclose()


@pytest.mark.parametrize("status", [400, 403, 404])
async def test_a_client_error_is_not_retried(tmp_path, status):
    fake = FakeGemini([status])
    ai = make_ai(tmp_path, fake)
    with pytest.raises(AIUnavailable, match=f"model error {status}"):
        await ai.json("t", "s", "p", SCHEMA)
    assert len(fake.requests) == 1
    await ai.aclose()


async def test_an_unreachable_model_is_tried_twice(tmp_path):
    fake = FakeGemini([httpx.ConnectError("down"), httpx.ConnectError("down")])
    ai = make_ai(tmp_path, fake)
    with pytest.raises(AIUnavailable, match="model unreachable: ConnectError"):
        await ai.json("t", "s", "p", SCHEMA)
    await ai.aclose()


async def test_a_dropped_connection_then_an_answer_succeeds(tmp_path):
    fake = FakeGemini([httpx.ReadTimeout("slow"), json_reply({"a": 9})])
    ai = make_ai(tmp_path, fake)
    assert await ai.json("t", "s", "p", SCHEMA) == {"a": 9}
    await ai.aclose()


async def test_errors_never_echo_the_key(tmp_path):
    ai = make_ai(tmp_path, FakeGemini([403]))
    with pytest.raises(AIUnavailable) as e:
        await ai.json("t", "s", "p", SCHEMA)
    assert SECRET not in str(e.value)
    await ai.aclose()
