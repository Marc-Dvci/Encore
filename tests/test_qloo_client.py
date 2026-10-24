"""The Qloo client: what may leave, the private cache, retries, the request log and the agent trace."""
import asyncio
import json

import httpx
import pytest

from encore.qloo import (FREE_TEXT_KEYS, PrivacyGuard, PrivacyViolation, Qloo, QlooUnavailable, _count, _norm_params,
                         start_trace)
from encore.store import Store
from tests.conftest import make_config


class Recorder:
    """A transport that answers from a list of (status, body) and keeps every request."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.requests: list[httpx.Request] = []

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request):
        self.requests.append(request)
        r = self.replies.pop(0) if self.replies else (200, {"results": [{"entity_id": "x"}]})
        if isinstance(r, Exception):
            raise r
        status, body = r
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)


def client(tmp_path, rec: Recorder, **over) -> Qloo:
    cfg = make_config(tmp_path, **over)
    q = Qloo(cfg, Store(cfg.db_path), transport=rec.transport())
    q.min_interval = 0
    return q


@pytest.fixture
def no_backoff(monkeypatch):
    real = asyncio.sleep

    async def quick(_seconds, *a, **k):
        await real(0)

    monkeypatch.setattr("encore.qloo.asyncio.sleep", quick)


# ---- parameters -------------------------------------------------------------------------------

def test_params_are_normalised_and_sorted():
    norm = _norm_params({"take": 5, "b": ["x", "y"], "flag": True, "off": False, "none": None, "empty": "", "nil": []})
    assert norm == [("b", "x,y"), ("flag", "true"), ("off", "false"), ("take", "5")]


def test_pairs_and_dicts_normalise_the_same():
    assert _norm_params([("b", 1), ("a", 2)]) == _norm_params({"a": 2, "b": 1})


def test_repeated_keys_survive_normalisation():
    assert _norm_params([("filter.tags", "a"), ("filter.tags", "b")]) == [("filter.tags", "a"), ("filter.tags", "b")]


# ---- the privacy guard ------------------------------------------------------------------------

def test_registered_free_text_is_matched_without_case_or_spaces():
    g = PrivacyGuard()
    g.allow(["  Frank Sinatra "])
    g.check([("query", "FRANK SINATRA")])
    g.check([("query", "frank sinatra  ")])


@pytest.mark.parametrize("key", sorted(FREE_TEXT_KEYS))
def test_every_free_text_field_needs_registration(key):
    g = PrivacyGuard()
    with pytest.raises(PrivacyViolation, match="unregistered free text"):
        g.check([(key, "a stranger's words")])


def test_blank_values_are_never_registered():
    g = PrivacyGuard()
    g.allow(["", "   ", None])
    with pytest.raises(PrivacyViolation):
        g.check([("query", " ")])


@pytest.mark.parametrize("value", ["urn:tag:genre:music:oldies", "1950", "55_and_older", "United States",
                                   "0A1B2C3D-0000-1111-2222-333344445555,0A1B2C3D-0000-1111-2222-333344445556",
                                   "urn:entity:movie", "true"])
def test_structured_values_pass(value):
    PrivacyGuard().check([("filter.tags", value)])


@pytest.mark.parametrize("value", ["needs a hearing aid; speaks little", "<script>", "she's shy", "line\nbreak",
                                   "50%", "x" * 4001, "rosa@example.com"])
def test_anything_unstructured_is_refused_outside_free_text_fields(value):
    with pytest.raises(PrivacyViolation, match="unstructured value"):
        PrivacyGuard().check([("filter.tags", value)])


def test_a_protected_name_is_caught_as_a_whole_word_only():
    g = PrivacyGuard()
    g.protect(["Ana"])
    g.check([("filter.tags", "urn:tag:genre:media:banana")])
    with pytest.raises(PrivacyViolation, match="protected value"):
        g.check([("filter.tags", "urn:tag:keyword:ana")])


def test_protected_values_ignore_case():
    g = PrivacyGuard()
    g.protect(["Walter"])
    with pytest.raises(PrivacyViolation):
        g.check([("filter.tags", "urn:tag:WALTER")])


def test_names_shorter_than_three_letters_are_not_patterns():
    # Two letters would match inside ordinary tag words and block real requests.
    g = PrivacyGuard()
    g.protect(["Al", "", None])
    g.check([("filter.tags", "urn:tag:genre:music:al")])


def test_free_text_allowed_is_still_checked_only_as_free_text():
    # A favourite's title is allowed in a free-text field; protecting a name does not block it there.
    g = PrivacyGuard()
    g.allow(["Rosa Parks"])
    g.protect(["Rosa"])
    g.check([("query", "Rosa Parks")])
    with pytest.raises(PrivacyViolation):
        g.check([("filter.tags", "urn:tag:rosa")])


async def test_a_refused_request_never_reaches_the_network_or_the_log(tmp_path):
    rec = Recorder()
    q = client(tmp_path, rec)
    with pytest.raises(PrivacyViolation):
        await q.search("Tomasz from room 4")
    assert rec.requests == [] and q.recent_log() == []
    await q.aclose()


# ---- the wire ---------------------------------------------------------------------------------

async def test_the_key_is_sent_as_x_api_key_only(tmp_path):
    rec = Recorder()
    q = client(tmp_path, rec, qloo_api_key="qloo-secret")
    q.guard.allow(["Elvis"])
    await q.search("Elvis", types="urn:entity:artist")
    req = rec.requests[0]
    assert req.headers["x-api-key"] == "qloo-secret"
    assert "qloo-secret" not in str(req.url)
    assert req.url.path == "/search" and req.url.host == "qloo.test"
    await q.aclose()


async def test_without_a_key_and_without_a_cache_nothing_is_sent(tmp_path):
    rec = Recorder()
    q = client(tmp_path, rec, qloo_api_key=None)
    assert not q.live
    with pytest.raises(QlooUnavailable, match="no Qloo key"):
        await q.insights({"filter.type": "urn:entity:movie"}, purpose="x")
    assert rec.requests == []
    await q.aclose()


# ---- the private cache ------------------------------------------------------------------------

async def test_parameter_order_does_not_defeat_the_cache(tmp_path):
    rec = Recorder()
    q = client(tmp_path, rec)
    await q.get("/v2/insights", {"take": 3, "filter.type": "urn:entity:movie"}, "x")
    await q.get("/v2/insights", [("filter.type", "urn:entity:movie"), ("take", 3)], "x")
    assert len(rec.requests) == 1
    await q.aclose()


async def test_an_expired_entry_is_fetched_again(tmp_path):
    rec = Recorder([(200, {"results": [1]}), (200, {"results": [1, 2]})])
    q = client(tmp_path, rec)
    await q.get("/search", {"types": "urn:entity:movie"}, "x")
    q.store.x("UPDATE qloo_cache SET fetched_at = 0")
    assert await q.get("/search", {"types": "urn:entity:movie"}, "x") == {"results": [1, 2]}
    assert len(rec.requests) == 2 and q.live_calls == 2
    await q.aclose()


async def test_cache_only_mode_serves_old_answers(tmp_path):
    rec = Recorder([(200, {"results": [7]})])
    live = client(tmp_path, rec)
    await live.get("/search", {"types": "urn:entity:book"}, "x")
    live.store.x("UPDATE qloo_cache SET fetched_at = 0")
    await live.aclose()
    offline = client(tmp_path, Recorder(), qloo_api_key=None)
    assert await offline.get("/search", {"types": "urn:entity:book"}, "x") == {"results": [7]}
    await offline.aclose()


async def test_errors_are_never_cached(tmp_path, no_backoff):
    rec = Recorder([(400, {"error": "bad"}), (200, {"results": [1]})])
    q = client(tmp_path, rec)
    with pytest.raises(QlooUnavailable):
        await q.get("/search", {"types": "urn:entity:movie"}, "x")
    assert await q.get("/search", {"types": "urn:entity:movie"}, "x") == {"results": [1]}
    await q.aclose()


# ---- retries ----------------------------------------------------------------------------------

@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_busy_answers_are_retried(tmp_path, no_backoff, status):
    rec = Recorder([(status, {}), (status, {}), (200, {"results": [1]})])
    q = client(tmp_path, rec)
    assert await q.get("/search", {"types": "urn:entity:artist"}, "x") == {"results": [1]}
    assert len(rec.requests) == 3
    await q.aclose()


async def test_four_busy_answers_give_up_and_say_so(tmp_path, no_backoff):
    rec = Recorder([(503, {"error": "busy"})] * 4)
    q = client(tmp_path, rec)
    with pytest.raises(QlooUnavailable, match="Qloo answered 503"):
        await q.get("/search", {"types": "urn:entity:artist"}, "x")
    assert len(rec.requests) == 4
    assert q.recent_log()[0]["status"] == 503
    await q.aclose()


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_client_errors_are_not_retried(tmp_path, no_backoff, status):
    rec = Recorder([(status, {"error": "no"})])
    q = client(tmp_path, rec)
    with pytest.raises(QlooUnavailable, match=f"Qloo answered {status}"):
        await q.get("/search", {"types": "urn:entity:artist"}, "x")
    assert len(rec.requests) == 1
    await q.aclose()


async def test_an_unreachable_server_raises_after_four_tries(tmp_path, no_backoff):
    rec = Recorder([httpx.ConnectError("down")] * 4)
    q = client(tmp_path, rec)
    with pytest.raises(QlooUnavailable, match="unreachable: ConnectError"):
        await q.get("/search", {"types": "urn:entity:artist"}, "x")
    assert len(rec.requests) == 4
    await q.aclose()


async def test_a_timeout_then_an_answer_succeeds(tmp_path, no_backoff):
    rec = Recorder([httpx.ReadTimeout("slow"), (200, {"results": [3]})])
    q = client(tmp_path, rec)
    assert await q.get("/search", {"types": "urn:entity:artist"}, "x") == {"results": [3]}
    await q.aclose()


async def test_a_non_json_error_page_is_reported_not_crashed_on(tmp_path, no_backoff):
    rec = Recorder([(400, "<html>Bad gateway</html>")])
    q = client(tmp_path, rec)
    with pytest.raises(QlooUnavailable, match="Bad gateway"):
        await q.get("/search", {"types": "urn:entity:artist"}, "x")
    await q.aclose()


# ---- the request log and the trace ------------------------------------------------------------

async def test_every_request_is_logged_with_its_purpose_and_result_count(tmp_path):
    rec = Recorder([(200, {"results": {"entities": [{"entity_id": "a"}, {"entity_id": "b"}]}})])
    q = client(tmp_path, rec)
    params = [("filter.type", "urn:entity:movie"), ("take", 2)]
    await q.insights(params, purpose="films of their youth")
    await q.insights(params, purpose="films of their youth")
    second, first = q.recent_log()
    assert first["purpose"] == "films of their youth" and first["results"] == 2
    assert first["cached"] == 0 and second["cached"] == 1
    assert first["params"] == [["filter.type", "urn:entity:movie"], ["take", "2"]]
    assert first["path"] == "/v2/insights" and first["status"] == 200
    await q.aclose()


async def test_the_log_never_holds_the_key(tmp_path):
    q = client(tmp_path, Recorder(), qloo_api_key="qloo-secret")
    await q.get("/search", {"types": "urn:entity:artist"}, "x")
    assert "qloo-secret" not in json.dumps(q.recent_log())
    await q.aclose()


async def test_a_trace_collects_only_the_requests_made_inside_it(tmp_path):
    q = client(tmp_path, Recorder())
    await q.get("/search", {"types": "urn:entity:artist"}, "before")

    async def tool():
        t = start_trace()
        await q.get("/search", {"types": "urn:entity:movie"}, "inside")
        return t

    trace = await asyncio.create_task(tool())
    assert [x["purpose"] for x in trace] == ["inside"]
    assert trace[0]["params"] == [("types", "urn:entity:movie")]
    await q.aclose()


# ---- typed helpers ----------------------------------------------------------------------------

async def test_entities_with_no_ids_asks_nothing(tmp_path):
    rec = Recorder()
    q = client(tmp_path, rec)
    assert await q.entities([]) == []
    assert rec.requests == []
    await q.aclose()


@pytest.mark.parametrize("body, n", [({"results": [{"entity_id": "a"}]}, 1),
                                     ({"results": {"entities": [{"entity_id": "a"}, {"entity_id": "b"}]}}, 2),
                                     ({"results": None}, 0)])
async def test_entities_reads_both_answer_shapes(tmp_path, body, n):
    q = client(tmp_path, Recorder([(200, body)]))
    assert len(await q.entities(["A" * 36])) == n
    await q.aclose()


async def test_insights_falls_back_to_tags(tmp_path):
    q = client(tmp_path, Recorder([(200, {"results": {"tags": [{"tag_id": "t"}]}})]))
    assert await q.insights([("filter.type", "urn:tag")], purpose="x") == [{"tag_id": "t"}]
    await q.aclose()


async def test_compare_sends_both_sides(tmp_path):
    rec = Recorder([(200, {"results": {"tags": []}})])
    q = client(tmp_path, rec)
    await q.compare(["A1", "A2"], ["B1"], purpose="x", take=10)
    params = dict(rec.requests[0].url.params)
    assert params == {"a.signal.interests.entities": "A1,A2", "b.signal.interests.entities": "B1", "take": "10"}
    assert rec.requests[0].url.path == "/v2/analysis/compare"
    await q.aclose()


async def test_tags_lookup_uses_the_registered_term(tmp_path):
    rec = Recorder([(200, {"results": {"tags": [{"id": "urn:tag:genre:music:polish"}]}})])
    q = client(tmp_path, rec)
    q.guard.allow(["polish"])
    assert await q.tags("polish") == [{"id": "urn:tag:genre:music:polish"}]
    assert dict(rec.requests[0].url.params)["filter.query"] == "polish"
    await q.aclose()


@pytest.mark.parametrize("body, n", [(None, None), ({}, None), ({"results": [1, 2, 3]}, 3),
                                     ({"results": {"entities": [1]}}, 1), ({"results": {"tags": [1, 2]}}, 2),
                                     ({"results": {"other": 1}}, None)])
def test_result_counts(body, n):
    assert _count(body) == n
