"""The home's own records: storage, the demo roster, privacy registration and matching a family's words."""
import sqlite3

import pytest

from encore import roster
from encore.config import ROOT
from encore.qloo import PrivacyGuard, PrivacyViolation
from encore.store import Store

HOME = ROOT / "data" / "maple_court.json"


class StubQloo:
    """Answers every search with the same results, so each matching rule can be pinned down."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    async def search(self, query, types=None, take=5, purpose=""):
        self.calls.append((query, types, take))
        return self.results


def ent(name, pop, year=None, kind="release_year", eid=None):
    props = {kind: year} if year else {}
    return {"entity_id": eid or f"id-{name}-{year}", "name": name, "popularity": pop, "properties": props}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    roster.load_home(s, HOME)
    return s


# ---- storage ----------------------------------------------------------------------------------

def test_kv_values_overwrite_and_parse(tmp_path):
    s = Store(tmp_path / "kv.db")
    assert s.kv_get("k") is None and s.kv_json("k", {"d": 1}) == {"d": 1}
    s.kv_set("k", "1")
    s.kv_set("k", '{"a": [1, 2]}')
    assert s.kv_json("k") == {"a": [1, 2]}


def test_rows_come_back_as_plain_dicts(tmp_path):
    s = Store(tmp_path / "rows.db")
    rid = s.x("INSERT INTO kv(k, v) VALUES('a', 'b')")
    assert rid == 1
    assert s.q("SELECT k, v FROM kv") == [{"k": "a", "v": "b"}]
    assert s.one("SELECT * FROM kv WHERE k='zzz'") is None


def test_a_database_from_before_the_family_form_gains_the_owner_column(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE people (id TEXT PRIMARY KEY, kind TEXT NOT NULL, first_name TEXT NOT NULL, last_initial TEXT, "
               "birth_year INTEGER NOT NULL, city TEXT, country TEXT, demonym TEXT, cuisine TEXT, music_genre TEXT, "
               "languages TEXT, room TEXT, present INTEGER NOT NULL DEFAULT 1, care_note TEXT, family_note TEXT, portrait TEXT)")
    db.execute("INSERT INTO people(id, kind, first_name, birth_year) VALUES('r-x', 'resident', 'X', 1940)")
    db.commit()
    db.close()
    s = Store(path)
    assert s.one("SELECT owner FROM people WHERE id='r-x'") == {"owner": None}


def test_records_survive_reopening(tmp_path):
    Store(tmp_path / "p.db").kv_set("seen", "yes")
    assert Store(tmp_path / "p.db").kv_get("seen") == "yes"


# ---- the demo home ----------------------------------------------------------------------------

def test_the_demo_home_loads_fourteen_residents_and_three_carers(store):
    assert len(roster.people(store, "resident")) == 14
    assert [c["first_name"] for c in roster.people(store, "carer")] == ["Ana", "Marcus", "Priya"]
    assert roster.home(store)["name"] == "Maple Court"


def test_loading_twice_does_not_duplicate_anyone(store):
    roster.load_home(store, HOME)
    assert store.one("SELECT COUNT(*) n FROM people")["n"] == 17
    assert store.one("SELECT COUNT(*) n FROM favourites")["n"] == 17 * 3


def test_a_reset_clears_the_day_and_reloads_the_home(store):
    store.x("INSERT INTO reactions(person_id, entity_id, entity_name, entity_type, reaction) "
            "VALUES('r-rosa', 'e', 'x', 'artist', 'lit_up')")
    store.x("UPDATE people SET present=0 WHERE id='r-rosa'")
    roster.load_home(store, HOME, reset=True)
    assert store.q("SELECT * FROM reactions") == []
    assert roster.person(store, "r-rosa")["present"] == 1


def test_family_favourites_start_pending_and_family_avoids_are_kept(store):
    t = roster.person(store, "r-tomasz")
    assert {f["status"] for f in t["favourites"]} == {"pending"}
    assert {f["source"] for f in t["favourites"]} == {"family"}
    assert roster.avoid_tags(t) == ["urn:tag:genre:media:war"]
    assert t["avoid"][0]["source"] == "family"


def test_a_person_carries_age_and_the_house_rules(store):
    p = roster.person(store, "r-dorothy")
    assert p["age"] == 2026 - 1932
    assert p["house_rules"] == [["urn:tag:genre:media:horror", "No horror in shared spaces"]]
    assert roster.person(store, "r-nobody") is None


def test_present_only_leaves_out_residents_who_are_away(store):
    store.x("UPDATE people SET present=0 WHERE id IN ('r-rosa', 'r-earl')")
    names = {p["first_name"] for p in roster.people(store, "resident", present_only=True)}
    assert len(names) == 12 and not {"Rosa", "Earl"} & names


def test_people_a_visitor_added_are_listed_last_and_only_for_them(store):
    store.x("INSERT INTO people(id, kind, first_name, birth_year, owner) VALUES('g-1', 'resident', 'Aaron', 1950, 'tok')")
    assert "g-1" not in {p["id"] for p in roster.people(store, "resident")}
    mine = roster.people(store, "resident", owner="tok")
    assert mine[-1]["id"] == "g-1" and len(mine) == 15


# ---- privacy registration ---------------------------------------------------------------------

def test_names_and_notes_are_protected_and_towns_and_favourites_allowed(store):
    g = PrivacyGuard()
    roster.register_privacy(store, g)
    for ok in ("Kraków", "Evanston, Illinois", "Czesław Niemen", "Polish"):
        g.check([("query", ok)])
    with pytest.raises(PrivacyViolation):
        g.check([("filter.tags", "urn:tag:genre:music:tomasz")])
    with pytest.raises(PrivacyViolation):
        g.check([("query", "Few words this week. Hearing aid on the left.")])
    with pytest.raises(PrivacyViolation):
        g.check([("query", "Tomasz W")])


# ---- seeds and avoid lists --------------------------------------------------------------------

def fav(eid, source="family", status="resolved"):
    return {"entity_id": eid, "source": source, "status": status}


def test_seeds_put_the_latest_session_sparks_before_family_favourites():
    p = {"favourites": [fav("f1"), fav("f2"), fav("s1", "session"), fav("s2", "session"), fav("s3", "session"),
                        fav("s4", "session")]}
    assert roster.seed_ids(p) == ["s4", "s3", "s2", "f1", "f2", "s1"]


def test_seeds_skip_unresolved_favourites_and_duplicates():
    p = {"favourites": [fav("f1"), fav(None, status="needs_input"), fav("f2", status="unresolved"), fav("f1", "session")]}
    assert roster.seed_ids(p) == ["f1"]


def test_seeds_are_capped():
    p = {"favourites": [fav(f"f{i}") for i in range(10)]}
    assert roster.seed_ids(p) == [f"f{i}" for i in range(6)]
    assert roster.seed_ids(p, limit=2) == ["f0", "f1"]


def test_avoid_lists_split_into_tags_and_items():
    p = {"avoid": [{"tag_id": "urn:tag:a", "entity_id": None}, {"tag_id": None, "entity_id": "E1"}]}
    assert roster.avoid_tags(p) == ["urn:tag:a"] and roster.avoid_entities(p) == ["E1"]


@pytest.mark.parametrize("raw, expected", [("Édith Piaf", "edithpiaf"), ("West Side Story!", "westsidestory"),
                                           ("Min-ja", "minja"), ("  The  Beatles ", "thebeatles")])
def test_names_compare_without_accents_case_or_punctuation(raw, expected):
    assert roster.norm(raw) == expected


# ---- matching a family's words to one Qloo entity ---------------------------------------------

async def test_nothing_found_is_unresolved():
    assert (await roster.resolve_favourite(StubQloo([]), "Rejs", "movie"))["status"] == "unresolved"


async def test_one_exact_title_resolves():
    q = StubQloo([ent("Amélie", 0.4, 2001), ent("Amelie Sings", 0.9)])
    r = await roster.resolve_favourite(q, "Amelie", "movie")
    assert r["status"] == "resolved" and r["entity_name"] == "Amélie"
    assert q.calls == [("Amelie", "urn:entity:movie", 6)]


async def test_the_clearly_better_known_of_two_exact_titles_resolves():
    r = await roster.resolve_favourite(StubQloo([ent("Lulu", 0.8, eid="big"), ent("Lulu", 0.5, eid="small")]), "Lulu", "artist")
    assert r["status"] == "resolved" and r["entity_id"] == "big"


async def test_two_exact_titles_too_close_to_call_go_to_staff():
    r = await roster.resolve_favourite(StubQloo([ent("Lulu", 0.80), ent("Lulu", 0.78)]), "Lulu", "artist")
    assert r["status"] == "needs_input" and len(r["candidates"]) == 2


async def test_a_remake_loses_to_the_release_of_their_youth():
    q = StubQloo([ent("West Side Story", 0.95, 2021), ent("West Side Story", 0.90, 1961)])
    r = await roster.resolve_favourite(q, "West Side Story", "movie", birth_year=1941)
    assert r["status"] == "resolved" and r["entity_id"] == "id-West Side Story-1961"
    assert "1961" in r["reason"]


async def test_without_a_birth_year_the_better_known_release_wins():
    q = StubQloo([ent("West Side Story", 0.95, 2021), ent("West Side Story", 0.80, 1961)])
    r = await roster.resolve_favourite(q, "West Side Story", "movie")
    assert r["entity_id"] == "id-West Side Story-2021"


async def test_a_famous_near_match_resolves_when_nothing_is_exact():
    q = StubQloo([ent("Frank Sinatra Jr", 0.95), ent("Frankie Valli", 0.6)])
    r = await roster.resolve_favourite(q, "Sinatra", "artist")
    assert r["status"] == "resolved" and r["entity_name"] == "Frank Sinatra Jr"


async def test_several_near_matches_go_to_staff():
    q = StubQloo([ent("Bobby Darin", 0.92), ent("Bobby Vinton", 0.88)])
    assert (await roster.resolve_favourite(q, "Bobby", "artist"))["status"] == "needs_input"


async def test_candidates_carry_year_and_image_for_staff_to_choose():
    e = ent("Irena Santor", 0.5, 1950, kind="start_year")
    e["properties"]["image"] = {"url": "https://images.qloo.com/i/x.jpg"}
    r = await roster.resolve_favourite(StubQloo([e, ent("Irena", 0.5)]), "Irena", "artist")
    c = next(c for c in r["candidates"] if c["name"] == "Irena Santor")
    assert c["year"] == 1950 and c["image"].endswith("x.jpg")


async def test_resolving_pending_favourites_updates_every_row(store, fake):
    from encore.qloo import Qloo
    from tests.conftest import make_config
    cfg = make_config(store.path.parent)
    q = Qloo(cfg, store, transport=fake.transport())
    q.min_interval = 0
    roster.register_privacy(store, q.guard)
    counts = await roster.resolve_pending(store, q)
    assert sum(counts.values()) == 17 * 3
    assert store.one("SELECT COUNT(*) n FROM favourites WHERE status='pending'")["n"] == 0
    rejs = store.one("SELECT status, entity_id FROM favourites WHERE label='Rejs'")
    assert rejs == {"status": "unresolved", "entity_id": None}
    await q.aclose()
