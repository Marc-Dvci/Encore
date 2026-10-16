from encore import roster, taste


def test_age_weight_peaks_between_15_and_25():
    assert taste.age_weight(20) == 1.0
    assert taste.age_weight(15) == 1.0 and taste.age_weight(25) == 1.0
    assert taste.age_weight(10) == 0.7 and taste.age_weight(30) == 0.7
    assert taste.age_weight(9) == 0.0 and taste.age_weight(31) == 0.0


def test_artist_era_uses_the_best_active_year_in_the_window():
    # Active from 1914 to 1971: covers the whole youth of someone born 1936.
    w, start, used = taste.artist_era({"start_year": 1914, "end_year": 1971}, 1936)
    assert (w, start) == (1.0, 1914) and 1951 <= used <= 1961
    # Started in 1978: too late for someone whose youth ended in 1966.
    assert taste.artist_era({"start_year": 1978}, 1936)[0] == 0.0
    # Started at 28: partial credit.
    assert 0 < taste.artist_era({"start_year": 1964}, 1936)[0] < 1


def test_interleave_alternates_lanes_without_duplicates():
    a = [{"entity_id": x} for x in "abc"]
    b = [{"entity_id": x} for x in "bxy"]
    assert [i["entity_id"] for i in taste.interleave([a, b])] == ["a", "b", "x", "c", "y"]


async def test_shelf_respects_the_window_and_the_avoid_list(enc):
    p = enc.person("r-tomasz")
    s = await taste.shelf(enc.store, enc.qloo, p, "movie", limit=30)
    lo, hi = taste.window(p["birth_year"])
    assert s["items"], "expected films"
    assert all(lo <= i["year"] <= hi for i in s["items"])
    assert not any("urn:tag:genre:media:war" in i["tag_ids"] for i in s["items"])


async def test_artist_shelf_drops_artists_outside_the_window(enc):
    p = enc.person("r-tomasz")
    s = await taste.shelf(enc.store, enc.qloo, p, "artist", limit=50)
    assert s["outside_era"] >= 0
    for i in s["items"]:
        assert i["start_year"] <= taste.window(p["birth_year"])[1]


async def test_same_title_resolves_to_the_release_of_their_youth(enc):
    r = await roster.resolve_favourite(enc.qloo, "West Side Story", "movie", 1941)
    assert r["status"] == "resolved" and "1961" in r["reason"]


async def test_unmatched_favourite_goes_to_staff(enc):
    rejs = next(f for f in enc.person("r-tomasz")["favourites"] if f["label"] == "Rejs")
    assert rejs["status"] in ("needs_input", "unresolved")
