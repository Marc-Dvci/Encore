"""Ask Encore, the MCP endpoint and the HTTP API, driven the way a coordinator, an assistant or the web app does."""
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from encore import agent as agent_mod
from encore.agent import TOOLS, Agent, _template_answer
from encore.ai import AI
from encore.app import create_app, from_this_machine, visitor_of
from encore.mcp_server import build_mcp
from encore.qloo import Qloo
from encore.service import Encore, NotFound
from encore.store import Store
from tests.conftest import make_config
from tests.fake_gemini import FakeGemini, call_reply, text_reply

MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture
async def enc_model(tmp_path, fake):
    cfg = make_config(tmp_path, ai_provider="gemini", gemini_api_key="k-test")
    store = Store(cfg.db_path)
    qloo = Qloo(cfg, store, transport=fake.transport())
    qloo.min_interval = 0
    gem = FakeGemini()
    e = Encore(cfg, store=store, qloo=qloo, ai=AI(cfg, store.kv_get, store.kv_set, transport=gem.transport()))
    await e.start()
    e.gemini = gem
    yield e
    await e.aclose()


@pytest.fixture
def no_backoff(monkeypatch):
    import asyncio
    real = asyncio.sleep

    async def quick(_seconds, *a, **k):
        await real(0)

    monkeypatch.setattr("encore.qloo.asyncio.sleep", quick)


def request(headers=None, client=("198.51.100.7", 4000)):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": client})


# ---- finding people by name -------------------------------------------------------------------

@pytest.mark.parametrize("name, pid", [("Tomasz", "r-tomasz"), ("tomasz", "r-tomasz"), ("r-rosa", "r-rosa"),
                                       ("min-ja", "r-minja"), ("MINJA", "r-minja")])
async def test_people_are_found_by_first_name_or_id(enc, name, pid):
    assert Agent(enc)._find(name, "resident")["id"] == pid


async def test_a_carer_is_not_a_resident_and_nobody_is_nobody(enc):
    a = Agent(enc)
    with pytest.raises(NotFound):
        a._find("Priya", "resident")
    with pytest.raises(NotFound):
        a._find(None)
    assert a._find("Priya", "carer")["id"] == "c-priya"


async def test_the_agent_cannot_reach_someone_a_visitor_added(enc):
    pid = (await enc.add_person("visitor-token-0123456789", "Mum", 1950, "Lyon", "France", [("Édith Piaf", "artist")]))["id"]
    with pytest.raises(NotFound):
        Agent(enc)._find("Mum")
    with pytest.raises(NotFound):
        Agent(enc)._find(pid)


# ---- every tool -------------------------------------------------------------------------------

async def test_list_people_names_every_resident_and_carer(enc):
    out, card = await Agent(enc).call("list_people", {}, None)
    assert len(out["residents"]) == 14 and len(out["carers"]) == 3 and card["kind"] == "people"
    assert {"name", "born", "from", "in_lounge"} <= out["residents"][0].keys()


async def test_resident_profile_gives_the_shelves_of_their_youth(enc):
    out, _ = await Agent(enc).call("resident_profile", {"resident": "Rosa"}, None)
    assert out["youth"] == (1950, 1970) and set(out) >= {"artist", "movie", "tv_show", "book", "family_favourites"}


async def test_a_lounge_film_for_named_residents_considers_only_them(enc):
    out, card = await Agent(enc).call("lounge_film", {"residents": ["Rosa", "Earl"], "max_minutes": 100}, None)
    assert out["residents"] == ["Rosa", "Earl"] and out["pick"] and (out["minutes"] or 0) <= 100
    assert card["kind"] == "lounge_film"


async def test_music_hour_and_plans_and_common_ground_and_week(enc):
    a = Agent(enc)
    music, _ = await a.call("music_hour", {}, None)
    assert music["playlist"] and music["coverage"]
    plan, _ = await a.call("plan_one_to_one", {"resident": "Tomasz", "carer": "Priya"}, None)
    assert plan["session_id"].startswith("s-") and plan["steps"]
    cg, _ = await a.call("common_ground", {"resident": "Tomasz", "carer": "Priya"}, None)
    assert cg["shared"] == ["Folk"]
    wk, _ = await a.call("week_plan", {}, None)
    assert len(wk["films"]) == 2 and len(wk["one_to_ones"]) == 14


async def test_recent_reactions_reads_what_staff_recorded(enc):
    item = {"entity_id": "0" * 36, "name": "Song Person", "type": "artist"}
    await enc.react("r-rosa", item, "lit_up", "c-ana", None)
    out, _ = await Agent(enc).call("recent_reactions", {"resident": "Rosa"}, None)
    assert out["reactions"][0]["reaction"] == "lit_up"


async def test_an_unknown_tool_is_refused(enc):
    with pytest.raises(NotFound):
        await Agent(enc).call("record_reaction", {}, None)


async def test_no_tool_can_write(enc):
    names = {t["name"] for t in TOOLS}
    assert not any(w in n for n in names for w in ("record", "add", "delete", "remove", "set", "update"))
    before = enc.store.one("SELECT (SELECT COUNT(*) FROM reactions) r, (SELECT COUNT(*) FROM avoid) a, "
                           "(SELECT COUNT(*) FROM favourites) f")
    for name, args in (("list_people", {}), ("resident_profile", {"resident": "Rosa"}), ("lounge_film", {}),
                       ("music_hour", {}), ("common_ground", {"resident": "Rosa", "carer": "Ana"}),
                       ("recent_reactions", {"resident": "Rosa"})):
        await Agent(enc).call(name, args, None)
    after = enc.store.one("SELECT (SELECT COUNT(*) FROM reactions) r, (SELECT COUNT(*) FROM avoid) a, "
                          "(SELECT COUNT(*) FROM favourites) f")
    assert after == before


# ---- the model plans with the tools -----------------------------------------------------------

async def test_the_model_calls_a_tool_and_answers_from_its_result(enc_model):
    enc_model.gemini.replies = [call_reply("lounge_film"), text_reply("Watch the pick on Thursday.")]
    r = await Agent(enc_model).ask("Which film for the lounge?")
    assert r["source"] == "model" and r["answer"] == "Watch the pick on Thursday."
    assert r["trace"][0]["tool"] == "lounge_film" and r["trace"][0]["ok"] and r["trace"][0]["qloo"]
    assert r["cards"][0]["kind"] == "lounge_film"
    second = enc_model.gemini.bodies()[1]["contents"]
    assert second[1]["parts"][0]["thoughtSignature"] == "sig-lounge_film"
    assert second[2]["parts"][0]["functionResponse"]["name"] == "lounge_film"
    assert second[2]["parts"][0]["functionResponse"]["response"]["result"]["pick"]


async def test_a_tool_error_goes_back_to_the_model_not_to_the_screen(enc_model):
    enc_model.gemini.replies = [call_reply("resident_profile", {"resident": "Nobody"}), text_reply("I can't find them.")]
    r = await Agent(enc_model).ask("Tell me about Nobody")
    assert r["trace"][0]["ok"] is False and "Nobody" in r["trace"][0]["error"] and r["cards"] == []
    sent = enc_model.gemini.bodies()[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "error" in sent


async def test_the_agent_stops_after_six_rounds(enc_model):
    enc_model.gemini.replies = [call_reply("list_people")] * 6
    r = await Agent(enc_model).ask("loop forever")
    assert r["answer"].startswith("I ran out of steps") and len(r["trace"]) == 6


async def test_when_the_model_fails_midway_the_matching_tool_runs_on_its_own(enc_model):
    enc_model.gemini.replies = [503, 503]
    r = await Agent(enc_model).ask("Make a playlist for music hour")
    assert r["source"] == "template" and r["trace"][-1]["tool"] == "music_hour"
    assert "model error 503" in r["note"] and r["answer"].startswith("Music hour:")


async def test_only_the_last_six_turns_and_800_characters_are_sent(enc_model):
    enc_model.gemini.replies = [text_reply("ok")]
    history = [{"role": "user" if i % 2 else "model", "text": f"turn {i}"} for i in range(10)]
    await Agent(enc_model).ask("x" * 2000, history)
    contents = enc_model.gemini.bodies()[0]["contents"]
    assert [c["parts"][0]["text"] for c in contents[:-1]] == [f"turn {i}" for i in range(4, 10)]
    assert len(contents[-1]["parts"][0]["text"]) == 800


async def test_the_system_prompt_names_the_home_and_the_rules(enc_model):
    enc_model.gemini.replies = [text_reply("ok")]
    await Agent(enc_model).ask("hello")
    system = enc_model.gemini.bodies()[0]["systemInstruction"]["parts"][0]["text"]
    assert "Maple Court" in system and "Dana" in system and "Never mention care notes" in system


# ---- without the model ------------------------------------------------------------------------

@pytest.mark.parametrize("message, tool", [
    ("Plan a session for Tomasz with Priya", "plan_one_to_one"),
    ("Can Rosa sit with Marcus for a one-to-one?", "plan_one_to_one"),
    ("What do Rosa and Marcus have in common?", "common_ground"),
    ("Show me this week's rota", "week_plan"),
    ("Make a playlist for music hour", "music_hour"),
    ("What should the lounge watch?", "lounge_film"),
    ("Tell me about Eleanor", "resident_profile"),
    ("hello", "list_people"),
])
async def test_the_keyword_router_picks_the_matching_tool(enc, message, tool):
    r = await Agent(enc).ask(message)
    assert r["source"] == "template" and r["trace"][0]["tool"] == tool and r["trace"][0]["ok"]


def test_template_answers_for_each_tool():
    film = {"pick": "Film 01", "year": 1958, "minutes": 95, "least_served": "Rosa", "least_served_fit": 0.6,
            "average_fit": 0.75}
    assert _template_answer("lounge_film", film).startswith("Film 01 (1958, 95 min)")
    assert "0.60" in _template_answer("lounge_film", film)
    assert _template_answer("music_hour", {"playlist": ["a", "b"]}) == "Music hour: a; b."
    assert _template_answer("plan_one_to_one", {"steps": [{"step": "Open", "item": "Song"}]}) == "Session plan: Open: Song."
    assert _template_answer("common_ground", {"shared": ["Folk"], "bridges": ["X (artist, 1960)"]}) == \
        "They share Folk. Try X (artist, 1960)."
    assert _template_answer("resident_profile", {"name": "Rosa", "youth": (1950, 1970), "artist": ["A (1955)"]}) == \
        "Rosa's youth ran 1950 to 1970. Songs: A (1955)."
    assert _template_answer("week_plan", {"films": ["A", "B"], "least_served_with_two_films": 0.9,
                                          "least_served_with_one_film": 0.5, "one_to_ones": ["Mon: R with C"]}) == \
        "This week: A and B. With both, the least-served resident's better film fits at 0.9, against 0.5 with one film. Mon: R with C."
    assert _template_answer("anything", {"error": "no resident called Bob"}) == "I couldn't do that: no resident called Bob."


async def test_every_mcp_tool_is_an_agent_tool(enc):
    mcp_names = {t.name for t in await build_mcp(Agent(enc)).list_tools()}
    assert len(mcp_names) == 7 and mcp_names <= {t["name"] for t in agent_mod.TOOLS}


# ---- MCP over HTTP ----------------------------------------------------------------------------

def rpc(c, method, params=None, i=1):
    r = c.post("/mcp/", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})
    assert r.status_code == 200
    return r.json()


async def test_mcp_lists_the_seven_tools(enc):
    with TestClient(create_app(enc, warm=False)) as c:
        init = rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1"}})
        assert "list_people" in init["result"]["instructions"]
        tools = rpc(c, "tools/list", i=2)["result"]["tools"]
    assert sorted(t["name"] for t in tools) == ["common_ground", "list_people", "lounge_film", "music_hour",
                                                "plan_one_to_one", "resident_profile", "week_plan"]
    assert all(t["description"] for t in tools)


async def test_an_assistant_can_plan_over_mcp(enc):
    with TestClient(create_app(enc, warm=False)) as c:
        people = rpc(c, "tools/call", {"name": "list_people", "arguments": {}})["result"]
        film = rpc(c, "tools/call", {"name": "lounge_film", "arguments": {"residents": ["Rosa", "Earl"]}}, 2)["result"]
    assert len(json.loads(people["content"][0]["text"])["residents"]) == 14
    assert json.loads(film["content"][0]["text"])["residents"] == ["Rosa", "Earl"]


async def test_mcp_reports_an_unknown_resident_as_a_tool_error(enc):
    with TestClient(create_app(enc, warm=False)) as c:
        out = rpc(c, "tools/call", {"name": "resident_profile", "arguments": {"resident": "Nobody"}})
    assert out["result"]["isError"] is True


# ---- the HTTP API -----------------------------------------------------------------------------

@pytest.fixture
def api(enc):
    with TestClient(create_app(enc, warm=False)) as c:
        yield c


def test_status_reports_qloo_and_the_model(api):
    s = api.get("/api/status").json()
    assert s["qloo"] == "live" and s["model_live"] is False and s["model"] == "gemini-test"
    assert set(s["reactions"]) == {"lit_up", "sang_along", "no_response", "upset"}


def test_every_response_carries_the_security_headers(api):
    for path in ("/api/home", "/api/people/r-nobody/profile", "/img/x.jpg"):
        h = api.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "SAMEORIGIN"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"


def test_home_lists_relations_and_countries_for_the_family_form(api):
    h = api.get("/api/home").json()
    assert len(h["residents"]) == 14 and h["present"] == 14 and len(h["countries"]) == 54
    assert "Grandma" in h["relations"] and h["countries"] == sorted(h["countries"])


def test_presence_from_the_api_changes_the_lounge(api):
    assert api.post("/api/people/r-rosa/present", json={"present": False}).json() == {"ok": True}
    assert api.get("/api/home").json()["present"] == 13
    assert "Rosa" not in api.get("/api/lounge").json()["residents"]


@pytest.mark.parametrize("minutes, status", [(29, 422), (30, 200), (240, 200), (241, 422)])
def test_lounge_runtime_bounds(api, minutes, status):
    assert api.post("/api/lounge", json={"max_minutes": minutes}).status_code == status


def test_music_hour_over_the_api(api):
    out = api.post("/api/lounge", json={"domain": "artist", "residents": ["r-rosa", "r-earl"]}).json()
    assert out["residents"] == ["Rosa", "Earl"] and out["playlist"]


def test_the_week_and_the_qloo_log(api):
    assert len(api.get("/api/week").json()["one_to_ones"]) == 14
    log = api.get("/api/qloo/log?limit=5000").json()
    assert log["total"] > 0 and len(log["rows"]) <= 500
    assert {p["path"] for p in log["paths"]} >= {"/v2/insights", "/search"}


@pytest.mark.parametrize("path, body", [
    ("/api/people/r-rosa/avoid", {"tag_id": "not a tag", "label": "x"}),
    ("/api/people/r-rosa/favourites", {"label": "x", "kind": "artist"}),
    ("/api/favourites/1/confirm", {"entity_id": "short", "entity_name": "x"}),
    ("/api/sessions", {"resident": "r-rosa"}),
    ("/api/agent", {"message": ""}),
    ("/api/agent", {"message": "x" * 801}),
    ("/api/people", {"relation": "Mum", "birth_year": 1900, "city": "Lyon", "country": "France",
                     "favourites": [{"label": "Piaf", "kind": "artist"}]}),
])
def test_malformed_requests_are_rejected_before_any_work(api, path, body):
    assert api.post(path, json=body).status_code == 422


def test_a_bad_favourite_kind_or_reaction_is_a_400(api):
    assert api.post("/api/people/r-rosa/favourites", json={"label": "Serial", "kind": "podcast"}).status_code == 400
    bad = {"person_id": "r-rosa", "reaction": "bored", "item": {"entity_id": "0" * 36, "name": "x"}}
    assert api.post("/api/reactions", json=bad).status_code == 400


def test_confirming_a_favourite_that_does_not_exist_is_a_404(api):
    assert api.post("/api/favourites/99999/confirm", json={"entity_id": "0" * 36, "entity_name": "x"}).status_code == 404


def test_avoid_tags_round_trip_over_the_api(api):
    assert api.post("/api/people/r-rosa/avoid", json={"tag_id": "urn:tag:genre:media:war", "label": "War"}).json() == {"ok": True}
    avoid = api.get("/api/record/r-rosa").json()["avoid"]
    assert avoid[0]["label"] == "War"
    assert api.delete(f"/api/people/r-rosa/avoid/{avoid[0]['id']}").json() == {"ok": True}
    assert api.get("/api/record/r-rosa").json()["avoid"] == []


def test_sessions_list_counts_reactions(api):
    s = api.post("/api/sessions", json={"resident": "r-rosa", "carer": "c-ana"}).json()
    item = next(st["item"] for st in s["steps"] if st.get("item"))
    api.post("/api/reactions", json={"person_id": "r-rosa", "reaction": "lit_up", "session_id": s["id"],
                                     "item": {"entity_id": item["entity_id"], "name": item["name"]}})
    row = next(r for r in api.get("/api/sessions").json() if r["id"] == s["id"])
    assert row == {"id": s["id"], "at": row["at"], "resident": "Rosa", "resident_id": "r-rosa", "carer": "Ana",
                   "reactions": 1}


def test_ask_encore_over_the_api(api):
    r = api.post("/api/agent", json={"message": "Which film tonight?", "history": [{"role": "model", "text": "Hi"}]}).json()
    assert r["source"] == "template" and r["trace"][0]["tool"] == "lounge_film"


def test_qloo_down_with_nothing_cached_is_a_503_with_a_plain_message(api, fake, no_backoff):
    fake.fail_next = [500] * 4
    r = api.post("/api/people/r-rosa/favourites", json={"label": "Agustín Lara", "kind": "artist"})
    assert r.status_code == 503 and "Qloo is not answering" in r.json()["error"]


def test_the_api_docs_are_served(api):
    assert api.get("/api/docs").status_code == 200
    paths = api.get("/api/openapi.json").json()["paths"]
    assert "/api/lounge" in paths and "/img/{name}" not in paths


def test_a_cached_image_is_served_with_a_week_of_browser_cache(api, enc):
    name = "0A1B2C3D-0000-1111-2222-333344445555-420x-auto.jpg"
    (enc.cfg.data_dir / "img" / name).write_bytes(b"\xff\xd8\xff fake jpeg")
    r = api.get(f"/img/{name}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=604800"


async def test_without_a_key_a_missing_image_is_a_404_and_nothing_is_fetched(tmp_path, fake):
    cfg = make_config(tmp_path, qloo_api_key=None)
    store = Store(cfg.db_path)
    e = Encore(cfg, store=store, qloo=Qloo(cfg, store, transport=fake.transport()), ai=AI(cfg, store.kv_get, store.kv_set))
    with TestClient(create_app(e, warm=False)) as c:
        n = len(fake.requests)
        assert c.get("/img/0A1B2C3D-0000-1111-2222-333344445555-420x-auto.jpg").status_code == 404
        assert len(fake.requests) == n
        assert c.get("/api/status").json()["qloo"] == "cache only"


def test_a_second_reset_within_twenty_seconds_is_refused(enc):
    with TestClient(create_app(enc, warm=False), client=("127.0.0.1", 50000)) as c:
        assert c.post("/api/demo/reset").status_code == 200
        assert c.post("/api/demo/reset").status_code == 429


# ---- who is asking ----------------------------------------------------------------------------

def test_the_visitor_id_is_a_hash_of_the_first_forwarded_address():
    a = visitor_of(request({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}))
    b = visitor_of(request({"x-forwarded-for": "203.0.113.9"}))
    c = visitor_of(request({"x-forwarded-for": "203.0.113.10"}))
    assert a == b != c and len(a) == 16 and "203" not in a
    assert visitor_of(request()) == visitor_of(request(client=("198.51.100.7", 1)))


@pytest.mark.parametrize("client, headers, ok", [(("127.0.0.1", 1), {}, True), (("::1", 1), {}, True),
                                                 (("127.0.0.1", 1), {"x-forwarded-for": "203.0.113.9"}, False),
                                                 (("10.0.0.5", 1), {}, False), (None, {}, False)])
def test_only_the_machine_itself_counts_as_local(client, headers, ok):
    assert from_this_machine(request(headers, client)) is ok
