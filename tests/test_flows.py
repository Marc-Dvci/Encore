import httpx
import pytest

from encore import roster, taste
from encore.agent import Agent
from encore.app import create_app
from encore.qloo import QlooUnavailable


async def test_session_plan_uses_template_words_without_a_model(enc):
    plan = await enc.plan("r-tomasz", "c-priya")
    kinds = [s["kind"] for s in plan["steps"]]
    assert kinds[0] == "open" and "film" in kinds and "food" in kinds
    assert plan["words_source"] == "template"
    assert all(not p.lower().startswith("do you remember") for p in plan["words"]["prompts"])


async def test_lit_up_becomes_a_signal(enc):
    p = enc.person("r-rosa")
    shelf = await taste.shelf(enc.store, enc.qloo, p, "artist", limit=5)
    item = shelf["items"][0]
    eff = await enc.react("r-rosa", item, "lit_up", "c-marcus", None)
    assert item["entity_id"] in roster.seed_ids(enc.person("r-rosa"))
    assert "signal" in eff["change"]


async def test_upset_excludes_the_item_and_offers_its_genres(enc):
    p = enc.person("r-walter")
    item = (await taste.shelf(enc.store, enc.qloo, p, "movie", limit=5))["items"][0]
    eff = await enc.react("r-walter", item, "upset", "c-ana", None)
    after = await taste.shelf(enc.store, enc.qloo, enc.person("r-walter"), "movie", limit=50)
    assert item["entity_id"] not in {i["entity_id"] for i in after["items"]}
    assert eff["suggest_tags"]


async def test_no_response_rests_the_item(enc):
    p = enc.person("r-eleanor")
    item = (await taste.shelf(enc.store, enc.qloo, p, "artist", limit=5))["items"][0]
    await enc.react("r-eleanor", item, "no_response", None, None)
    after = await taste.shelf(enc.store, enc.qloo, enc.person("r-eleanor"), "artist", limit=50)
    assert item["entity_id"] not in {i["entity_id"] for i in after["items"]}


async def test_agent_falls_back_to_the_matching_tool(enc):
    r = await Agent(enc).ask("Which film should the lounge watch today?")
    assert r["source"] == "template"
    assert r["trace"][0]["tool"] == "lounge_film" and r["trace"][0]["qloo"]
    assert "fit" in r["answer"]


async def test_cache_answers_the_second_time(enc, fake):
    await enc.profile("r-ruth")
    n = len(fake.requests)
    await enc.profile("r-ruth")
    assert len(fake.requests) == n


async def test_rate_limit_is_retried(enc, fake):
    fake.fail_next = [429]
    out = await enc.qloo.search("Frank Sinatra", types="urn:entity:artist")
    assert out


async def test_stale_cache_is_served_when_qloo_fails(enc, fake):
    first = await enc.qloo.search("Frank Sinatra", types="urn:entity:artist", take=3)
    enc.store.x("UPDATE qloo_cache SET fetched_at = 0")
    fake.fail_next = [500] * 4
    again = await enc.qloo.search("Frank Sinatra", types="urn:entity:artist", take=3)
    assert again == first


async def test_unreachable_qloo_without_cache_raises(enc, fake):
    fake.fail_next = [500] * 4
    with pytest.raises(QlooUnavailable):
        await enc.qloo.search("Frank Sinatra", types="urn:entity:movie", take=2)


async def test_http_api_and_image_route(enc):
    app = create_app(enc, warm=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/api/home")).json()["name"] == "Maple Court"
        assert (await c.get("/api/people/r-nobody/profile")).status_code == 404
        for probe in ("/img/..%2F..%2Fencore.db", "/img/x.jpg", "/../var/encore.db"):
            r = await c.get(probe)
            assert b"SQLite format" not in r.content
        assert (await c.get("/img/not-an-image.jpg")).status_code == 404
        s = (await c.post("/api/sessions", json={"resident": "r-tomasz", "carer": "c-priya"})).json()
        assert (await c.get(f"/api/sessions/{s['id']}")).json()["resident"]["first_name"] == "Tomasz"
        bad = await c.post("/api/reactions", json={"person_id": "r-tomasz", "reaction": "lit_up",
                                                   "item": {"entity_id": "not-an-id", "name": "x"}})
        assert bad.status_code == 422
        rec = (await c.get("/api/record/r-tomasz")).json()
        assert rec["person"]["first_name"] == "Tomasz"
