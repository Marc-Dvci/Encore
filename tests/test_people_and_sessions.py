"""The family form, what a reaction teaches Encore, staff edits, and one-to-one session plans."""
import json

import pytest

from encore import family, learning, session
from encore.ai import AI
from encore.qloo import PrivacyViolation, Qloo
from encore.service import Encore, NotFound
from encore.store import Store
from tests.conftest import make_config
from tests.fake_gemini import FakeGemini, json_reply

OWNER = "visitor-token-0123456789"
OK = dict(relation="Mum", birth_year=1950, city="Lyon", country="France", favourites=[("Édith Piaf", "artist")])


@pytest.fixture
async def enc_model(tmp_path, fake):
    """Encore with a (synthetic) model, to check what the model is told and how its words are used."""
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


# ---- the family form --------------------------------------------------------------------------

@pytest.mark.parametrize("token, ok", [("a" * 16, True), ("A-b_9" * 4, True), ("a" * 64, True), ("a" * 15, False),
                                       ("a" * 65, False), ("has space here!!", False), ("dots.are.not.ok.x", False),
                                       ("", False), (None, False)])
def test_visitor_tokens(token, ok):
    assert (family.valid_owner(token) is not None) == ok


@pytest.mark.parametrize("change, message", [
    ({"relation": "Cousin"}, "relation must be one of"),
    ({"country": "Atlantis"}, "pick a country"),
    ({"birth_year": 1919}, "between 1920 and 1975"),
    ({"birth_year": 1976}, "between 1920 and 1975"),
    ({"city": "<b>Lyon</b>"}, "town or city"),
    ({"city": "L"}, "town or city"),
    ({"city": "Ly\non"}, "town or city"),
    ({"favourites": [("  ", "artist")]}, "at least one favourite"),
    ({"favourites": [("Serial", "podcast")]}, "singer, film, TV show or book"),
])
async def test_the_family_form_refuses_what_it_cannot_use(enc, change, message):
    with pytest.raises(ValueError, match=message):
        await enc.add_person(OWNER, **{**OK, **change})
    assert enc.store.one("SELECT COUNT(*) n FROM people WHERE owner IS NOT NULL")["n"] == 0


@pytest.mark.parametrize("year", [1920, 1975])
async def test_the_birth_year_bounds_are_inclusive(enc, year):
    assert (await enc.add_person(OWNER, **{**OK, "birth_year": year}))["id"].startswith("g-")


async def test_only_three_favourites_are_kept_each_at_most_80_characters(enc):
    favs = [("A" * 120, "artist"), ("Amélie", "movie"), ("Juliette Gréco", "artist"), ("Brel", "artist")]
    out = await enc.add_person(OWNER, **{**OK, "favourites": favs})
    labels = [f["label"] for f in out["favourites"]]
    assert labels == ["A" * 80, "Amélie", "Juliette Gréco"]


async def test_someone_added_is_away_from_the_lounge_and_named_only_by_relation(enc):
    pid = (await enc.add_person(OWNER, **OK))["id"]
    p = enc.person(pid)
    assert p["first_name"] == "Mum" and p["last_initial"] is None and p["present"] == 0
    assert p["languages"] == "French, English" and p["demonym"] == "French" and p["owner"] == OWNER
    us = enc.person((await enc.add_person(OWNER, **{**OK, "country": "United States"}))["id"])
    assert us["languages"] == "English" and us["music_genre"] is None


async def test_the_relation_is_never_registered_as_text_qloo_may_receive(enc):
    await enc.add_person(OWNER, **{**OK, "relation": "Grandma"})
    enc.qloo.guard.check([("query", "Lyon")])
    with pytest.raises(PrivacyViolation):
        enc.qloo.guard.check([("query", "Grandma")])


async def test_the_whole_demo_has_a_guest_limit(enc):
    for i in range(family.MAX_GUESTS):
        enc.store.x("INSERT INTO people(id, kind, first_name, birth_year, owner) VALUES(?, 'resident', 'Mum', 1950, ?)",
                    (f"g-{i}", f"other-visitor-{i:08d}"))
    with pytest.raises(ValueError, match="demo is full"):
        await enc.add_person(OWNER, **OK)


def test_fifty_four_countries_each_with_a_demonym():
    assert len(family.COUNTRIES) == 54
    assert all(len(v) == 4 and v[0] for v in family.COUNTRIES.values())


async def test_removing_someone_takes_their_favourites_reactions_and_sessions(enc):
    pid = (await enc.add_person(OWNER, **OK))["id"]
    plan = await enc.plan(pid, "c-ana")
    item = next(s["item"] for s in plan["steps"] if s.get("item"))
    await enc.react(pid, {**item, "type": item.get("type", "artist")}, "lit_up", "c-ana", plan["id"])
    assert not family.remove_person(enc.store, "someone-else-0123456789", pid)
    enc.remove_person(OWNER, pid)
    for table, col in (("people", "id"), ("favourites", "person_id"), ("reactions", "person_id")):
        assert enc.store.q(f"SELECT 1 FROM {table} WHERE {col}=?", (pid,)) == []
    assert enc.store.q("SELECT 1 FROM sessions WHERE id=?", (plan["id"],)) == []
    with pytest.raises(NotFound):
        enc.remove_person(OWNER, pid)


# ---- reactions --------------------------------------------------------------------------------

ITEM = {"entity_id": "0A1B2C3D-0000-1111-2222-333344445555", "name": "Song Person", "type": "artist",
        "genre_tags": [{"tag_id": f"urn:tag:genre:music:g{i}", "name": f"G{i}"} for i in range(5)]}


def test_an_unknown_reaction_or_person_is_refused(enc):
    with pytest.raises(ValueError):
        learning.log_reaction(enc.store, "r-rosa", ITEM, "bored")
    with pytest.raises(KeyError):
        learning.log_reaction(enc.store, "r-nobody", ITEM, "lit_up")


@pytest.mark.parametrize("reaction", ["lit_up", "sang_along"])
def test_both_good_reactions_add_a_signal_once(enc, reaction):
    first = learning.log_reaction(enc.store, "r-rosa", ITEM, reaction, "c-ana")
    again = learning.log_reaction(enc.store, "r-rosa", ITEM, reaction, "c-ana")
    assert "is now a signal" in first["change"] and "already a signal" in again["change"]
    rows = enc.store.q("SELECT source FROM favourites WHERE person_id='r-rosa' AND entity_id=?", (ITEM["entity_id"],))
    assert rows == [{"source": "session"}]


def test_upset_adds_the_item_to_the_avoid_list_and_offers_three_genres(enc):
    eff = learning.log_reaction(enc.store, "r-rosa", ITEM, "upset")
    assert len(eff["suggest_tags"]) == 3 and "avoid list" in eff["change"]
    assert ITEM["entity_id"] in [a["entity_id"] for a in enc.person("r-rosa")["avoid"]]


def test_no_response_changes_neither_favourites_nor_avoid_list(enc):
    before = enc.person("r-rosa")
    eff = learning.log_reaction(enc.store, "r-rosa", ITEM, "no_response")
    after = enc.person("r-rosa")
    assert "14 days" in eff["change"]
    assert len(after["favourites"]) == len(before["favourites"]) and after["avoid"] == before["avoid"]


def test_history_is_newest_first_with_the_carer_s_name(enc):
    learning.log_reaction(enc.store, "r-rosa", ITEM, "no_response", "c-ana")
    learning.log_reaction(enc.store, "r-rosa", ITEM, "lit_up", "c-marcus", note="hummed the chorus")
    h = learning.history(enc.store, "r-rosa")
    assert [(r["reaction"], r["carer"]) for r in h] == [("lit_up", "Marcus"), ("no_response", "Ana")]
    assert h[0]["note"] == "hummed the chorus"
    assert len(learning.history(enc.store, "r-rosa", limit=1)) == 1


def test_diff_reports_what_entered_and_left_a_shelf():
    d = learning.diff([{"entity_id": "a"}, {"entity_id": "b"}], [{"entity_id": "b"}, {"entity_id": "c"}])
    assert d == {"in": [{"entity_id": "c"}], "out": [{"entity_id": "a"}]}


async def test_a_reaction_reports_how_the_shelf_changed(enc):
    shelf = (await enc.profile("r-rosa"))["era"]["shelves"]["artist"]["items"]
    eff = await enc.react("r-rosa", shelf[0], "upset", "c-ana", None)
    assert shelf[0]["name"] in {x["name"] for x in eff["shelf_out"]}


# ---- staff edits ------------------------------------------------------------------------------

def test_avoid_tags_can_be_added_and_removed(enc):
    enc.add_avoid_tag("r-rosa", "urn:tag:genre:media:war", "War films")
    aid = next(a["id"] for a in enc.person("r-rosa")["avoid"] if a["tag_id"] == "urn:tag:genre:media:war")
    enc.remove_avoid("r-rosa", aid)
    assert enc.person("r-rosa")["avoid"] == []
    with pytest.raises(NotFound):
        enc.add_avoid_tag("r-nobody", "urn:tag:x", "x")


def test_presence_toggles_for_residents_but_not_for_family_added_people(enc):
    enc.set_present("r-rosa", False)
    assert "Rosa" not in {r["first_name"] for r in enc.home()["residents"] if r["present"]}
    enc.store.x("INSERT INTO people(id, kind, first_name, birth_year, owner) VALUES('g-x', 'resident', 'Mum', 1950, ?)",
                (OWNER,))
    with pytest.raises(ValueError):
        enc.set_present("g-x", True)


async def test_a_favourite_staff_add_is_matched_and_can_be_confirmed_or_removed(enc):
    r = await enc.add_favourite("r-rosa", "  Frank Sinatra  ", "artist")
    assert r["status"] == "resolved"
    fav = enc.store.one("SELECT * FROM favourites WHERE id=?", (r["id"],))
    assert fav["label"] == "Frank Sinatra" and fav["source"] == "family"
    enc.confirm_favourite(r["id"], "0" * 36, "Someone Else")
    assert enc.store.one("SELECT entity_name FROM favourites WHERE id=?", (r["id"],))["entity_name"] == "Someone Else"
    enc.remove_favourite("r-rosa", r["id"])
    assert enc.store.one("SELECT 1 FROM favourites WHERE id=?", (r["id"],)) is None
    with pytest.raises(ValueError):
        await enc.add_favourite("r-rosa", "Serial", "podcast")


async def test_a_favourite_waiting_for_staff_shows_its_candidates(enc):
    prof = await enc.profile("r-tomasz")
    rejs = next(f for f in prof["favourites"] if f["label"] == "Rejs")
    assert rejs["status"] == "unresolved"
    assert all("candidates" in p for p in prof["pending"])


# ---- one-to-one sessions ----------------------------------------------------------------------

def test_song_lines():
    assert session._song_line(None) is None
    assert session._song_line({"name": "Niemen", "songs": ["Dziwny jest ten świat"]}) == "Dziwny jest ten świat by Niemen"
    assert session._song_line({"name": "Niemen", "songs": []}) == "Niemen"


def test_why_explains_age_home_and_the_favourite_behind_it():
    r = {"first_name": "Rosa", "birth_year": 1940, "country": "Mexico"}
    film = {"type": "movie", "year": 1958, "age_then": 18, "lanes": ["home"], "because": ["Pedro Infante"]}
    assert session._why(film, r) == "Rosa was 18 in 1958; from Mexico; Qloo links it to Pedro Infante."
    artist = {"type": "artist", "year": 1950, "age_then": 20, "lanes": [], "because": []}
    assert session._why(artist, r) == "Rosa was 20 in 1960."
    assert session._why({"type": "movie", "lanes": []}, r) == ""


def test_template_words_follow_what_the_plan_holds():
    r = {"first_name": "Rosa", "city": "Guadalajara"}
    food = {"kind": "food", "place": {"dishes": ["Pozole"]}}
    song = {"kind": "open", "item": {"name": "Pedro Infante"}}
    w = session._template(r, {}, [song, food])
    assert w["opener"].startswith("I found a song") and w["prompts"][-1] == "Who made the best pozole when you were young?"
    bare = session._template(r, {}, [])
    assert bare["opener"] == "I'd love to hear about Guadalajara, Rosa."
    assert bare["prompts"] == ["Tell me about Sunday dinner in Guadalajara."]
    assert all(not p.lower().startswith("do you remember") for p in w["prompts"] + bare["prompts"])


async def test_a_plan_is_saved_and_reloads_with_its_reactions(enc):
    plan = await enc.plan("r-rosa", "c-ana")
    item = next(s["item"] for s in plan["steps"] if s.get("item"))
    await enc.react("r-rosa", {**item, "type": item.get("type", "artist")}, "lit_up", "c-ana", plan["id"])
    saved = enc.session(plan["id"])
    assert saved["steps"] == plan["steps"] and len(saved["reactions"]) == 1
    assert session.load_plan(enc.store, "s-missing") is None
    with pytest.raises(NotFound):
        enc.session("s-missing")


async def test_the_next_plan_skips_a_song_already_tried(enc):
    first = await enc.plan("r-rosa", "c-ana")
    disc = next(s for s in first["steps"] if s["kind"] == "discover")
    await enc.react("r-rosa", disc["item"], "no_response", "c-ana", first["id"])
    second = await enc.plan("r-rosa", "c-ana")
    assert next(s for s in second["steps"] if s["kind"] == "discover")["item"]["entity_id"] != disc["item"]["entity_id"]


async def test_the_activity_record_lists_sessions_with_their_items(enc):
    plan = await enc.plan("r-rosa", "c-ana")
    rec = enc.record("r-rosa")
    assert rec["sessions"][0]["id"] == plan["id"] and rec["sessions"][0]["carer"] == "Ana"
    assert rec["sessions"][0]["items"] and rec["home"]["name"] == "Maple Court"


async def test_model_words_are_used_trimmed_to_three_prompts(enc_model):
    words = {"opener": "Here is a song.", "prompts": ["Tell me about A.", "", "Tell me about B.", "Tell me about C.",
                                                      "Tell me about D."], "if_quiet": "Sit together.", "greeting": ""}
    enc_model.gemini.replies = [json_reply(words)]
    plan = await enc_model.plan("r-tomasz", "c-priya")
    assert plan["words_source"] == "model"
    assert plan["words"]["prompts"] == ["Tell me about A.", "Tell me about B.", "Tell me about C."]


async def test_the_model_is_told_the_plan_but_never_a_care_note_or_family_note(enc_model):
    enc_model.gemini.replies = [json_reply({"opener": "x", "prompts": [], "if_quiet": "x", "greeting": ""})]
    await enc_model.plan("r-tomasz", "c-priya")
    prompt = json.dumps(enc_model.gemini.bodies()[0], ensure_ascii=False)
    t = enc_model.person("r-tomasz")
    assert "Tomasz" in prompt and "Kraków" in prompt
    assert t["care_note"] not in prompt and t["family_note"][:40] not in prompt
    assert "Do you remember" in prompt  # the rule, stated to the model
