from encore import group


def res(i, birth=1940):
    return {"id": f"r{i}", "first_name": f"R{i}", "birth_year": birth}


def test_percentiles_run_from_last_to_first():
    p = group.percentiles({"a": 0.9, "b": 0.5, "c": 0.7}, ["a", "b", "c"])
    assert p == {"b": 0.0, "c": 0.5, "a": 1.0}


def test_maximin_beats_the_crowd_favourite_for_the_least_served():
    # Film A: loved by two, last for the third. Film B: second for everyone.
    residents = [res(1), res(2), res(3)]
    pool = [{"entity_id": x, "name": x, "year": 1960} for x in ("A", "B", "C")]
    aff = {"r1": {"A": 0.99, "B": 0.6, "C": 0.1}, "r2": {"A": 0.99, "B": 0.6, "C": 0.1},
           "r3": {"A": 0.1, "B": 0.6, "C": 0.9}}
    rows = group.score_candidates(residents, pool, aff, "movie")
    assert rows[0]["name"] == "B"
    assert rows[0]["min_pct"] == 0.5
    crowd = max(rows, key=lambda r: r["mean_affinity"])
    assert crowd["name"] == "A" and crowd["min_pct"] == 0.0


def test_era_credit_halves_a_film_outside_the_window():
    r = res(1, birth=1936)
    assert group.era_credit(r, {"year": 1956}, "movie") == 1.0
    assert group.era_credit(r, {"year": 1990}, "movie") == 0.5


async def test_film_pick_honours_runtime_and_avoid_lists(enc):
    out = await enc.lounge("movie", max_minutes=100)
    assert out["pick"]
    for c in out["candidates"]:
        assert (c["duration"] or 0) <= 100
    assert all(len(c["per_resident"]) == len(out["residents"]) for c in out["candidates"])
    assert out["pick"]["min_pct"] == max(c["min_pct"] for c in out["candidates"])


async def test_music_hour_gives_everyone_an_artist(enc):
    out = await enc.lounge("artist")
    assert out["playlist"]
    assert {c["name"] for c in out["coverage"]} == set(out["residents"])
