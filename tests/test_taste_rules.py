"""The culture of a resident's youth: the age window, artist eras, the two lanes and how a shelf is built."""
import pytest

from encore import taste
from encore.qloo import QlooUnavailable
from encore.store import Store


class StubQloo:
    """Tags come from a fixed list; insights answers come from a function of the request."""

    def __init__(self, tag_ids=(), answer=None):
        self.tag_ids = list(tag_ids)
        self.answer = answer or (lambda params: [])
        self.calls: list[tuple[dict, str]] = []
        self.tag_calls: list[str] = []

    async def tags(self, term, purpose="", take=15):
        self.tag_calls.append(term)
        return [{"id": t} for t in self.tag_ids]

    async def insights(self, params, purpose):
        p = dict(params)
        self.calls.append((p, purpose))
        out = self.answer(p)
        if isinstance(out, Exception):
            raise out
        return out


def person(birth=1940, seeds=("S1", "S2"), country="Poland", music="polish", cuisine="polish", avoid=(), rules=()):
    favs = [{"id": i, "entity_id": s, "entity_name": f"Fav {s}", "label": f"fav {s}", "status": "resolved",
             "source": "family", "kind": "artist"} for i, s in enumerate(seeds)]
    return {"id": "r-x", "first_name": "X", "birth_year": birth, "country": country, "music_genre": music,
            "cuisine": cuisine, "favourites": favs, "avoid": [{"tag_id": t, "entity_id": None} for t in avoid],
            "house_rules": [[t, "rule"] for t in rules]}


def film(eid, year, aff=0.8, tags=(), because=()):
    return {"entity_id": eid, "name": f"Film {eid}", "popularity": 0.5,
            "properties": {"release_year": year, "duration": 95, "release_country": ["Poland"]},
            "tags": [{"tag_id": t, "name": t.split(":")[-1].title(), "type": "urn:tag:genre:media"} for t in tags],
            "query": {"affinity": aff, "explainability": {"signal.interests.entities": [
                {"entity_id": s, "score": sc} for s, sc in because]}}}


# ---- the age window ---------------------------------------------------------------------------

@pytest.mark.parametrize("age, w", [(-5, 0.0), (9, 0.0), (10, 0.7), (11, 0.76), (12, 0.82), (13, 0.88), (14, 0.94),
                                    (15, 1.0), (20, 1.0), (25, 1.0), (26, 0.94), (27, 0.88), (28, 0.82), (29, 0.76),
                                    (30, 0.7), (31, 0.0), (80, 0.0)])
def test_age_weight_table(age, w):
    assert taste.age_weight(age) == w


def test_the_window_is_ages_ten_to_thirty():
    assert taste.window(1940) == (1950, 1970)


@pytest.mark.parametrize("raw, year", [("1961-05-01", 1961), (1961, 1961), ("1961", 1961), (None, None),
                                       ("c. 1950", None), ("abcd", None)])
def test_years_are_read_from_dates_numbers_and_strings(raw, year):
    assert taste._year(raw) == year


# ---- artist eras ------------------------------------------------------------------------------

def test_an_artist_without_a_start_year_falls_back_to_twenty_after_birth():
    w, start, used = taste.artist_era({"date_of_birth": "1930-02-11"}, 1936)
    assert start == 1950 and w == 1.0 and used == 1951


def test_an_artist_who_stopped_early_gets_only_the_years_they_were_active():
    # Active 1950-1952, someone born 1940 was 10 to 12: the best of those years is age 12.
    assert taste.artist_era({"start_year": 1950, "end_year": 1952}, 1940) == (0.82, 1950, 1952)


def test_a_death_year_ends_the_active_years():
    assert taste.artist_era({"start_year": 1945, "year_of_death": 1949}, 1940) == (0.0, 1945, None)


def test_an_artist_with_no_dates_is_left_out():
    assert taste.artist_era({}, 1940) == (0.0, None, None)


@pytest.mark.parametrize("props, year", [({"release_year": 1959}, 1959), ({"publication_year": "1960"}, 1960),
                                         ({"release_date": "1958-03-01"}, 1958), ({}, None)])
def test_media_years(props, year):
    assert taste.media_year({"properties": props}) == year


@pytest.mark.parametrize("birth, tags", [(1930, [("filter.tags", taste.ERA_MUSIC_TAG)]),
                                         (1954, [("filter.tags", taste.ERA_MUSIC_TAG)]), (1955, []), (1962, [])])
def test_the_oldies_tag_is_used_only_for_births_before_1955(birth, tags):
    assert taste.era_music_tags(birth) == tags


# ---- genre tags -------------------------------------------------------------------------------

async def test_an_exact_genre_slug_is_preferred():
    q = StubQloo(["urn:tag:genre:music:polish_jazz", "urn:tag:genre:music:polish"])
    assert await taste.music_tag(q, "Polish") == "urn:tag:genre:music:polish"


async def test_a_two_word_genre_falls_back_to_its_first_word():
    q = StubQloo(["urn:tag:genre:place:restaurant:soul", "urn:tag:genre:music:filipino"])
    assert await taste.music_tag(q, "filipino pop") == "urn:tag:genre:music:filipino"


async def test_a_genre_qloo_does_not_know_gives_nothing():
    assert await taste.cuisine_tag(StubQloo(["urn:tag:genre:music:polish"]), "polish") is None


async def test_no_term_asks_nothing():
    q = StubQloo()
    assert await taste.music_tag(q, None) is None and q.tag_calls == []


# ---- lanes ------------------------------------------------------------------------------------

async def test_films_get_a_home_lane_and_a_family_lane_with_the_youth_window():
    lanes = await taste.lanes_for(StubQloo(), person(avoid=["urn:tag:genre:media:war"],
                                                     rules=["urn:tag:genre:media:horror"]), "movie")
    assert [lane.name for lane in lanes] == ["home", "family favourites"]
    home, fam = (dict(lane.params) for lane in lanes)
    assert home["filter.release_country"] == "Poland" and "filter.release_country" not in fam
    for p in (home, fam):
        assert p["filter.release_year.min"] == 1950 and p["filter.release_year.max"] == 1970
        assert p["signal.demographics.age"] == "55_and_older"
        assert p["signal.interests.entities"] == ["S1", "S2"]
        assert p["filter.exclude.tags"] == ["urn:tag:genre:media:war", "urn:tag:genre:media:horror"]


async def test_television_reaches_five_years_further_back():
    fam = dict((await taste.lanes_for(StubQloo(), person(), "tv_show"))[-1].params)
    assert fam["filter.release_year.min"] == 1945 and fam["filter.release_year.max"] == 1970


async def test_books_use_publication_years_and_have_no_home_lane():
    lanes = await taste.lanes_for(StubQloo(), person(avoid=["urn:tag:x"]), "book")
    assert [lane.name for lane in lanes] == ["family favourites"]
    p = dict(lanes[0].params)
    assert p["filter.publication_year.min"] == 1950 and "filter.exclude.tags" not in p


async def test_artists_skip_the_age_signal_and_use_the_home_genre():
    lanes = await taste.lanes_for(StubQloo(["urn:tag:genre:music:polish"]), person(birth=1937), "artist")
    home, fam = (lane.params for lane in lanes)
    assert ("filter.tags", "urn:tag:genre:music:polish") in home
    assert ("filter.tags", taste.ERA_MUSIC_TAG) in fam
    assert not any(k == "signal.demographics.age" for k, _ in home + fam)


async def test_artists_born_after_1954_get_no_oldies_tag():
    fam = (await taste.lanes_for(StubQloo(), person(birth=1962, music=None), "artist"))[0]
    assert not any(v == taste.ERA_MUSIC_TAG for _, v in fam.params)


async def test_without_favourites_films_still_get_the_home_lane_but_artists_get_nothing():
    q = StubQloo(["urn:tag:genre:music:polish"])
    films = await taste.lanes_for(q, person(seeds=()), "movie")
    assert [lane.name for lane in films] == ["home"]
    assert "signal.interests.entities" not in dict(films[0].params)
    assert await taste.lanes_for(q, person(seeds=()), "artist") == []


async def test_without_a_country_there_is_only_the_family_lane():
    lanes = await taste.lanes_for(StubQloo(), person(country=None), "movie")
    assert [lane.name for lane in lanes] == ["family favourites"]


# ---- shelves ----------------------------------------------------------------------------------

async def test_a_shelf_weights_by_age_drops_the_out_of_era_and_names_the_favourite_behind_each_film(tmp_path):
    def answer(p):
        return [film("A", 1958, 0.9, because=[("S1", 0.7), ("S2", 0.1)]),  # age 18: full weight
                film("B", 1951, 0.95),                                     # age 11: 0.76
                film("C", 1975, 0.99),                                     # age 35: out of the window
                film("S1", 1960, 0.99)]                                    # a seed itself: never on the shelf
    s = await taste.shelf(Store(tmp_path / "s.db"), StubQloo(answer=answer), person(country=None), "movie")
    assert [i["entity_id"] for i in s["items"]] == ["A", "B"]
    a, b = s["items"]
    assert a["because"] == ["Fav S1"] and a["age_then"] == 18 and a["era_weight"] == 1.0
    assert b["score"] == pytest.approx(0.95 * 0.76, abs=1e-4)
    assert s["outside_era"] == 1 and s["window"] == (1950, 1970) and s["considered"] == 4


async def test_one_lane_failing_leaves_the_other_lane_on_the_shelf(tmp_path):
    def answer(p):
        if "filter.release_country" in p:
            return QlooUnavailable("home lane down")
        return [film("A", 1958)]
    s = await taste.shelf(Store(tmp_path / "s.db"), StubQloo(answer=answer), person(), "movie")
    assert [i["entity_id"] for i in s["items"]] == ["A"]
    assert s["errors"] == ["home lane down"]


async def test_a_film_both_lanes_found_appears_once_with_both_lanes(tmp_path):
    s = await taste.shelf(Store(tmp_path / "s.db"), StubQloo(answer=lambda p: [film("A", 1958)]), person(), "movie")
    assert len(s["items"]) == 1 and s["items"][0]["lanes"] == ["home", "family favourites"]


async def test_avoided_items_and_items_resting_after_no_response_stay_off(tmp_path):
    store = Store(tmp_path / "s.db")
    store.x("INSERT INTO reactions(person_id, entity_id, entity_name, entity_type, reaction) "
            "VALUES('r-x', 'B', 'Film B', 'movie', 'no_response')")
    store.x("INSERT INTO reactions(person_id, entity_id, entity_name, entity_type, reaction, at) "
            "VALUES('r-x', 'C', 'Film C', 'movie', 'no_response', datetime('now', '-20 days'))")
    p = person(country=None)
    p["avoid"].append({"tag_id": None, "entity_id": "A"})
    answer = [film("A", 1958), film("B", 1958), film("C", 1958)]
    s = await taste.shelf(store, StubQloo(answer=lambda _: answer), p, "movie")
    assert [i["entity_id"] for i in s["items"]] == ["C"]
    assert taste.cooled_down(store, "r-x") == ["B"]


def test_interleave_handles_uneven_and_empty_lanes():
    a = [{"entity_id": x} for x in "ab"]
    assert taste.interleave([]) == []
    assert taste.interleave([[], a]) == a
    assert [i["entity_id"] for i in taste.interleave([a, [{"entity_id": "c"}], []])] == ["a", "c", "b"]


def test_an_artist_item_carries_songs_start_year_and_spotify():
    e = {"entity_id": "E", "name": "Niemen", "properties": {"start_year": 1962, "notable_songs": list("abcde")},
         "external": {"spotify": {"id": "sp1"}},
         "tags": [{"tag_id": "urn:tag:genre:music:rock", "name": "Rock", "type": "urn:tag:genre:music"},
                  {"tag_id": "urn:tag:genre:music:rock2", "name": "Rock", "type": "urn:tag:genre:music"},
                  {"tag_id": "urn:tag:audience:x", "name": "Fans", "type": "urn:tag:audience"}]}
    it = taste._item(e, "artist", 1962, 1960, 1937, 0.5, 1.0, 0.5, [], [])
    assert it["songs"] == ["a", "b", "c", "d"] and it["start_year"] == 1962 and it["spotify_id"] == "sp1"
    assert it["genres"] == ["Rock"] and len(it["genre_tags"]) == 2 and it["age_then"] == 23
    assert "urn:tag:audience:x" in it["tag_ids"]


def test_a_film_item_carries_runtime_and_country():
    it = taste._item(film("F", 1958), "movie", 1958, 1958, 1940, 0.8, 1.0, 0.8, [], [])
    assert it["duration"] == 95 and it["country"] == ["Poland"] and "songs" not in it


def test_readable_tags_keep_genres_and_themes_only():
    tags = [{"tag_id": "urn:tag:genre:media:drama", "name": "Drama"}, {"tag_id": "urn:tag:audience:x", "name": "A"},
            {"id": "urn:tag:theme:qloo:love", "name": "Love", "subtype": "urn:tag:theme:qloo"},
            {"tag_id": "urn:tag:genre:media:x"}]
    assert [t["name"] for t in taste.readable_tags(tags)] == ["Drama", "Love"]
    assert len(taste.readable_tags([{"tag_id": "urn:tag:genre:x", "name": str(i)} for i in range(20)], limit=3)) == 3


# ---- family favourites and food ---------------------------------------------------------------

async def test_family_details_list_every_family_favourite_even_unmatched_ones():
    p = person()
    p["favourites"].append({"id": 9, "entity_id": None, "entity_name": None, "label": "Rejs", "status": "unresolved",
                            "source": "family", "kind": "movie"})
    p["favourites"].append({"id": 10, "entity_id": "Z", "entity_name": "Spark", "label": "Spark", "status": "resolved",
                            "source": "session", "kind": "artist"})

    def answer(params):
        return [{"entity_id": "S1", "properties": {"start_year": 1962, "notable_songs": ["Dziwny"]}}]
    out = await taste.seed_details(StubQloo(answer=answer), p)
    assert [x["name"] for x in out] == ["Fav S1", "Fav S2", "Rejs"]
    assert out[0]["songs"] == ["Dziwny"] and out[0]["year"] == 1962
    assert out[2]["status"] == "unresolved"


async def test_family_details_survive_qloo_being_down():
    out = await taste.seed_details(StubQloo(answer=lambda p: QlooUnavailable("down")), person())
    assert [x["name"] for x in out] == ["Fav S1", "Fav S2"] and out[0]["songs"] == []


async def test_no_cuisine_means_no_food_search():
    q = StubQloo()
    assert await taste.taste_of_home(q, person(cuisine=None), "Evanston", 15000) == {"tag": None, "places": []}
    assert q.calls == []


async def test_food_near_the_home_reads_dishes_distance_and_access():
    def answer(p):
        return [{"entity_id": "P", "name": "Pierogi Place",
                 "properties": {"address": "1 Main", "specialty_dishes": [{"name": "Pierogi"}, "Bigos", {"name": None}]},
                 "tags": [{"name": "Wheelchair accessible entrance"}], "query": {"distance": 4260, "affinity": 0.91234}}]
    q = StubQloo(["urn:tag:genre:place:restaurant:polish"], answer)
    out = await taste.taste_of_home(q, person(), "Evanston", 15000)
    place = out["places"][0]
    assert out["tag"] == "urn:tag:genre:place:restaurant:polish"
    assert place["dishes"] == ["Pierogi", "Bigos"] and place["distance_km"] == 4.3 and place["wheelchair"]
    p, _ = q.calls[0]
    assert p["filter.location.query"] == "Evanston" and p["filter.location.radius"] == 15000
    assert p["signal.interests.entities"] == ["S1", "S2"]
