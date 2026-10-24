"""Choosing for a room and for a week: the shortlist, per-resident rankings, maximin, music hour, pairs and rotas."""
import json

import pytest

from encore import common, group, roster, taste, week
from encore.qloo import QlooUnavailable
from encore.store import Store


def res(i, birth=1940, seeds=(), care_note=None, avoid_tags=(), avoid_ids=()):
    favs = [{"entity_id": s, "status": "resolved", "source": "family"} for s in seeds]
    avoid = [{"tag_id": t, "entity_id": None} for t in avoid_tags] + [{"tag_id": None, "entity_id": e} for e in avoid_ids]
    return {"id": f"r{i}", "first_name": f"R{i}", "birth_year": birth, "favourites": favs, "avoid": avoid,
            "care_note": care_note, "city": "Town"}


def item(eid, score=0.5, year=1958, duration=95, tags=()):
    return {"entity_id": eid, "name": eid, "year": year, "duration": duration, "score": score, "tag_ids": list(tags)}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "c.db")
    s.kv_set("home", json.dumps({"house_rules": [["urn:tag:horror", "No horror"]], "max_film_minutes": 110}))
    return s


class StubQloo:
    def __init__(self, insights=None, compare=None):
        self._insights = insights or (lambda p: [])
        self._compare = compare or (lambda a, b: {"tags": []})
        self.calls: list[dict] = []

    async def insights(self, params, purpose):
        p = dict(params)
        self.calls.append(p)
        return self._insights(p)

    async def compare(self, a, b, purpose, take=40):
        out = self._compare(a, b)
        if isinstance(out, Exception):
            raise out
        return out


# ---- the shortlist ----------------------------------------------------------------------------

async def test_the_shortlist_takes_each_residents_best_allowed_items(store, monkeypatch):
    shelves = {"r1": [item("A", 0.9, tags=["urn:tag:horror"]), item("B", 0.8), item("C", 0.7), item("D", 0.6)],
               "r2": [item("E", 0.9, duration=150), item("B", 0.85), item("X", 0.8), item("F", 0.5)]}

    async def shelf(_s, _q, r, domain, limit):
        return {"items": shelves[r["id"]]}
    monkeypatch.setattr(taste, "shelf", shelf)
    residents = [res(1), res(2, avoid_ids=["X"])]
    pool, excluded = await group.candidate_pool(store, None, residents, "movie", per_person=2, max_minutes=110, cap=10)
    assert [c["entity_id"] for c in pool] == ["B", "C", "F"]
    assert pool[0]["nominated_by"] == ["R1", "R2"]
    assert {e["name"]: e["why"] for e in excluded} == {"A": "carries a tag on a resident's avoid list",
                                                       "E": "longer than 110 minutes", "X": "on a resident's avoid list"}


async def test_one_residents_avoid_tag_keeps_an_item_off_everyone_s_shortlist(store, monkeypatch):
    async def shelf(_s, _q, r, domain, limit):
        return {"items": [item("W", tags=["urn:tag:war"]), item("P")]}
    monkeypatch.setattr(taste, "shelf", shelf)
    pool, _ = await group.candidate_pool(store, None, [res(1, avoid_tags=["urn:tag:war"]), res(2)], "movie", 1, None, 10)
    assert [c["entity_id"] for c in pool] == ["P"]


async def test_the_shortlist_is_capped_with_shared_nominations_first(store, monkeypatch):
    async def shelf(_s, _q, r, domain, limit):
        own = [item(f"{r['id']}-{k}", 0.99) for k in range(3)]
        return {"items": [item("SHARED", 0.1)] + own}
    monkeypatch.setattr(taste, "shelf", shelf)
    pool, _ = await group.candidate_pool(store, None, [res(1), res(2), res(3)], "artist", 2, None, cap=3)
    assert len(pool) == 3 and pool[0]["entity_id"] == "SHARED"


async def test_runtime_never_excludes_music(store, monkeypatch):
    async def shelf(_s, _q, r, domain, limit):
        return {"items": [item("LONG", duration=500)]}
    monkeypatch.setattr(taste, "shelf", shelf)
    pool, excluded = await group.candidate_pool(store, None, [res(1)], "artist", 1, 30, 10)
    assert [c["entity_id"] for c in pool] == ["LONG"] and excluded == []


@pytest.mark.parametrize("raw, n", [("95", 95), (95, 95), (None, None), ("abc", None)])
def test_runtime_parsing(raw, n):
    assert group._minutes(raw) == n


# ---- per-resident rankings --------------------------------------------------------------------

async def test_each_resident_ranks_the_whole_shortlist_and_their_own_favourite_comes_first():
    def answer(p):
        return [{"entity_id": "A", "query": {"affinity": 0.7}}, {"entity_id": "B", "query": {"affinity": 0.6}}]
    q = StubQloo(insights=answer)
    pool = [{"entity_id": x} for x in ("A", "B", "S")]
    aff = await group.affinities(q, [res(1, seeds=["S"]), res(2)], pool, "movie")
    assert aff["r1"]["S"] == pytest.approx(0.701) and aff["r1"]["A"] == 0.7
    assert "S" not in aff["r2"]
    first = q.calls[0]
    assert first["filter.results.entities"] == ["A", "B", "S"] and first["take"] == 3
    assert first["signal.demographics.age"] == "55_and_older"
    assert "signal.interests.entities" not in q.calls[1]


async def test_artist_rankings_leave_the_age_signal_off():
    q = StubQloo()
    await group.affinities(q, [res(1, seeds=["S"])], [{"entity_id": "A"}], "artist")
    assert "signal.demographics.age" not in q.calls[0]


def test_one_candidate_is_everyone_s_top_choice():
    assert group.percentiles({"a": 0.1}, ["a"]) == {"a": 1.0}
    assert group.percentiles({"a": 0.1, "b": 0.9}, ["a", "b"]) == {"a": 0.0, "b": 1.0}


@pytest.mark.parametrize("cand, credit", [({"year": 1958}, 1.0), ({"year": 1951}, 0.76), ({"year": 1990}, 0.5),
                                          ({"year": None}, 0.5)])
def test_film_era_credit_never_drops_below_half(cand, credit):
    assert group.era_credit(res(1, birth=1940), cand, "movie") == credit


def test_artist_era_credit_reads_the_start_year_or_the_year():
    assert group.era_credit(res(1, birth=1940), {"start_year": 1950}, "artist") == 1.0
    assert group.era_credit(res(1, birth=1940), {"year": 1985}, "artist") == 0.5


def test_scores_name_the_least_served_resident_and_the_room_average():
    pool = [{"entity_id": "A", "name": "A", "year": 1958}, {"entity_id": "B", "name": "B", "year": 1958}]
    aff = {"r1": {"A": 0.9, "B": 0.1}, "r2": {"A": 0.2, "B": 0.8}}
    rows = group.score_candidates([res(1), res(2)], pool, aff)
    assert {r["name"]: r["least_served"] for r in rows} == {"A": "R2", "B": "R1"}
    assert all(r["mean_pct"] == 0.5 and r["min_pct"] == 0.0 for r in rows)
    assert rows[0]["per_resident"][0].keys() >= {"rank_pct", "era", "pct", "affinity"}


def test_a_film_outside_someone_s_youth_counts_half_for_them():
    pool = [{"entity_id": "OLD", "name": "OLD", "year": 1990}, {"entity_id": "NEW", "name": "NEW", "year": 1958}]
    aff = {"r1": {"OLD": 0.9, "NEW": 0.1}}
    rows = {r["name"]: r for r in group.score_candidates([res(1)], pool, aff)}
    assert rows["OLD"]["min_pct"] == 0.5 and rows["NEW"]["min_pct"] == 0.0


async def test_no_shortlist_means_no_pick(store, monkeypatch):
    async def shelf(*a, **k):
        return {"items": []}
    monkeypatch.setattr(taste, "shelf", shelf)
    out = await group.film_pick(store, None, [res(1)])
    assert out["pick"] is None and out["candidates"] == []
    assert (await group.music_hour(store, None, [res(1)]))["playlist"] == []


async def test_the_home_s_runtime_limit_applies_when_none_is_given(enc):
    out = await enc.lounge("movie")
    assert out["max_minutes"] == 110
    assert [a["rule"] for a in out["alternatives"]] == ["Highest average affinity", "Most popular film on the shortlist"]


# ---- music hour -------------------------------------------------------------------------------

async def test_music_hour_serves_each_resident_s_favourite_before_the_room_s(store, monkeypatch):
    residents = [res(1), res(2), res(3)]
    ids = ["A1", "A2", "A3", "POP1", "POP2"]
    pool = [{"entity_id": i, "name": i, "start_year": 1955, "songs": [f"{i} song"]} for i in ids]
    # Each resident has a private favourite; the two POP artists are liked by everyone but loved by nobody.
    aff = {"r1": {"A1": 0.99, "POP1": 0.8, "POP2": 0.7, "A2": 0.1, "A3": 0.1},
           "r2": {"A2": 0.99, "POP1": 0.8, "POP2": 0.7, "A1": 0.1, "A3": 0.1},
           "r3": {"A3": 0.99, "POP1": 0.8, "POP2": 0.7, "A1": 0.1, "A2": 0.1}}

    async def fake_pool(*a, **k):
        return pool, []

    async def fake_aff(*a, **k):
        return aff
    monkeypatch.setattr(group, "candidate_pool", fake_pool)
    monkeypatch.setattr(group, "affinities", fake_aff)
    out = await group.music_hour(store, None, residents, length=4)
    names = [x["name"] for x in out["playlist"]]
    assert set(names[:3]) == {"A1", "A2", "A3"} and names[3] == "POP1"
    assert all(c["pct"] == 1.0 for c in out["coverage"])
    assert out["playlist"][0]["song"].endswith("song")


async def test_music_hour_never_repeats_an_artist_and_respects_its_length(enc):
    out = await enc.lounge("artist")
    names = [x["name"] for x in out["playlist"]]
    assert len(names) == len(set(names)) <= 12


# ---- two films for the week -------------------------------------------------------------------

def row(name, fits):
    per = [{"id": rid, "name": rid, "pct": f} for rid, f in fits.items()]
    return {"entity_id": name, "name": name, "year": 1955, "per_resident": per, "min_pct": min(fits.values()),
            "least_served": min(fits, key=fits.get), "mean_pct": round(sum(fits.values()) / len(fits), 3)}


def test_one_film_cannot_make_a_pair():
    assert week.best_pair([row("A", {"r1": 1.0})]) is None
    assert week.best_pair([]) is None


def test_between_equal_floors_the_pair_with_the_higher_average_wins():
    a, b, c = row("A", {"r1": 1.0, "r2": 0.5}), row("B", {"r1": 0.5, "r2": 1.0}), row("C", {"r1": 0.5, "r2": 0.6})
    first, second, floor, mean = week.best_pair([a, c, b])
    assert {first["name"], second["name"]} == {"A", "B"} and floor == 1.0 and mean == 1.0


def test_pair_floor_names_who_is_still_least_served():
    assert week.pair_floor(row("A", {"r1": 0.9, "r2": 0.2}), row("B", {"r1": 0.1, "r2": 0.4})) == (0.4, "r2")


# ---- who sits with whom -----------------------------------------------------------------------

def tag(name, kind, score, a=None, b=None):
    q = {"score": score}
    if a:
        q["a.signal.interests.entities"] = [{"name": a}]
    if b:
        q["b.signal.interests.entities"] = [{"name": b}]
    return {"name": name, "subtype": kind, "query": q}


async def test_a_match_counts_distinct_shared_genres_and_themes_only():
    tags = [tag("Folk", "urn:tag:genre:music", 0.9, "Niemen", "Dylan"), tag("folk", "urn:tag:genre:music", 0.8),
            tag("Loyal fans", "urn:tag:audience:qloo", 0.99), tag("Nostalgia", "urn:tag:theme:qloo", 0.5),
            tag("", "urn:tag:genre:music", 0.7)]
    m = await week.match(StubQloo(compare=lambda a, b: {"tags": tags}), res(1, seeds=["S"]), res(9, seeds=["T"]))
    assert m["n"] == 2 and m["score"] == 1.4 and m["shared"] == ["Folk", "Nostalgia"]
    assert m["link"] == {"tag": "Folk", "resident": "Niemen", "carer": "Dylan"}


async def test_no_favourites_or_no_answer_means_nothing_shared():
    q = StubQloo(compare=lambda a, b: QlooUnavailable("down"))
    for r, c in ((res(1), res(9, seeds=["T"])), (res(1, seeds=["S"]), res(9, seeds=["T"]))):
        m = await week.match(q, r, c)
        assert (m["score"], m["n"], m["shared"], m["link"]) == (0.0, 0, [], None)


def test_carers_get_an_even_share_even_when_one_is_everyone_s_favourite():
    residents = [res(i) for i in range(5)]
    carers = [{"id": "c1", "first_name": "C1"}, {"id": "c2", "first_name": "C2"}]
    scores = {r["id"]: {"c1": {"score": 5.0}, "c2": {"score": 1.0}} for r in residents}
    out = week.assign(residents, carers, scores)
    assert sorted(out.values()) == ["c1", "c1", "c1", "c2", "c2"]


def test_the_resident_with_most_to_lose_chooses_first():
    residents = [res(1), res(2)]
    carers = [{"id": "c1", "first_name": "C1"}, {"id": "c2", "first_name": "C2"}]
    scores = {"r1": {"c1": {"score": 1.0}, "c2": {"score": 0.9}}, "r2": {"c1": {"score": 3.0}, "c2": {"score": 0.0}}}
    assert week.assign(residents, carers, scores) == {"r2": "c1", "r1": "c2"}


def test_the_usual_rota_deals_residents_alphabetically():
    residents = [{"id": "z", "first_name": "Zoe"}, {"id": "a", "first_name": "Al"}, {"id": "m", "first_name": "Mo"}]
    carers = [{"id": "c1"}, {"id": "c2"}]
    assert week.rota(residents, carers) == {"a": "c1", "m": "c2", "z": "c1"}


async def test_flagged_residents_get_the_first_one_to_ones_of_the_week(enc):
    w = await enc.week()
    first = w["one_to_ones"][0]
    assert first["resident"]["first_name"] == "Tomasz" and first["resident"]["flag"] and first["day"] == "Monday"
    days = [o["day"] for o in w["one_to_ones"]]
    assert days == sorted(days, key=week.DAYS.index)
    assert max(days.count(d) for d in week.DAYS) == 3


async def test_the_matrix_marks_exactly_one_carer_per_resident(enc):
    w = await enc.week()
    assert len(w["matrix"]) == len(w["one_to_ones"])
    assert all(sum(c["chosen"] for c in r["carers"]) == 1 for r in w["matrix"])
    assert [x["day"] for x in w["lounge"]] == ["Tuesday", "Thursday", "Wednesday"]


async def test_a_week_without_carers_still_plans_the_films(enc):
    residents = roster.people(enc.store, "resident", present_only=True)
    w = await week.plan_week(enc.store, enc.qloo, residents, [])
    assert w["films"]["pair"] and w["matrix"][0]["carers"] == []
    assert all(o["carer"]["id"] is None for o in w["one_to_ones"])


# ---- common ground ----------------------------------------------------------------------------

async def test_common_ground_needs_favourites_on_both_sides():
    out = await common.common_ground(StubQloo(), res(1, seeds=["S"]), res(9))
    assert out == {"shared": [], "bridges": []}


async def test_common_ground_keeps_genres_and_themes_and_finds_bridges(enc):
    out = await enc.common("r-tomasz", "c-priya")
    assert [s["name"] for s in out["shared"]] == ["Folk"]
    assert {b["type"] for b in out["bridges"]} == {"artist", "movie"}
    assert out["resident"] == "Tomasz" and out["carer"] == "Priya"


def test_the_bridge_is_the_item_both_sides_pull_toward_most_evenly():
    def ent(eid, sa, sb, pop=0.5, start=1955):
        return {"entity_id": eid, "name": eid, "popularity": pop, "properties": {"start_year": start},
                "query": {"explainability": {"signal.interests.entities": [{"entity_id": "A", "score": sa},
                                                                           {"entity_id": "B", "score": sb}]}}}
    ents = [ent("lopsided", 0.9, 0.0, pop=0.99), ent("even", 0.5, 0.5), ent("too-late", 0.5, 0.5, start=1990)]
    best = common._bridge(ents, ["A"], ["B"], birth_year=1937)
    assert best["entity_id"] == "even" and best["resident_share"] == 0.5
    assert common._bridge([], ["A"], ["B"], None) is None
