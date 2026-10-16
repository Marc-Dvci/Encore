"""The week plan and the family form."""
from fastapi.testclient import TestClient

from encore import roster, week
from encore.app import create_app

OWNER = "visitor-token-0123456789"


def _row(name, fits):
    per = [{"id": rid, "name": rid, "pct": f} for rid, f in fits.items()]
    return {"entity_id": name, "name": name, "year": 1955, "per_resident": per, "min_pct": min(fits.values()),
            "least_served": min(fits, key=fits.get), "mean_pct": sum(fits.values()) / len(fits)}


def test_two_films_chosen_together_beat_the_two_best_films_taken_separately():
    a = _row("A", {"r1": 0.9, "r2": 0.9, "r3": 0.4})   # best single film
    b = _row("B", {"r1": 0.8, "r2": 0.8, "r3": 0.35})  # second best single film, same gap
    c = _row("C", {"r1": 0.1, "r2": 0.1, "r3": 1.0})   # poor alone, completes A
    rows = sorted([a, b, c], key=lambda r: (-r["min_pct"], -r["mean_pct"]))
    first, second, floor, _ = week.best_pair(rows)
    assert {first["name"], second["name"]} == {"A", "C"}
    assert floor == 0.9
    assert week.pair_floor(rows[0], rows[1])[0] == 0.4


def test_assignment_respects_each_carers_share_and_keeps_the_strong_pair():
    residents = [{"id": f"r{i}", "first_name": f"R{i}"} for i in range(4)]
    carers = [{"id": "c1", "first_name": "C1"}, {"id": "c2", "first_name": "C2"}]
    s = {"r0": {"c1": 5.0, "c2": 0.0}, "r1": {"c1": 1.0, "c2": 0.9}, "r2": {"c1": 1.0, "c2": 0.8}, "r3": {"c1": 1.0, "c2": 0.7}}
    scores = {r: {c: {"score": v} for c, v in d.items()} for r, d in s.items()}
    out = week.assign(residents, carers, scores)
    assert out["r0"] == "c1"
    assert sorted(out.values()).count("c1") == 2 and sorted(out.values()).count("c2") == 2


async def test_week_plan_covers_every_resident_present(enc):
    w = await enc.week()
    present = roster.people(enc.store, "resident", present_only=True)
    assert len(w["one_to_ones"]) == len(present)
    assert {o["day"] for o in w["one_to_ones"]} <= set(week.DAYS)
    assert w["films"]["pair"]["floor"] >= w["films"]["single"]["floor"]
    loads = [sum(1 for o in w["one_to_ones"] if o["carer"]["id"] == c["id"]) for c in w["carers"]]
    assert max(loads) <= w["pairing"]["cap"]


async def test_family_form_adds_a_person_only_its_visitor_sees(enc, fake):
    r = await enc.add_person(OWNER, "Grandma", 1948, "Lyon", "France", [("Édith Piaf", "artist"), ("Amélie", "movie")])
    pid = r["id"]
    assert pid.startswith("g-") and r["favourites"][0]["status"] == "resolved"
    assert pid in {x["id"] for x in enc.home(OWNER)["residents"]}
    assert pid not in {x["id"] for x in enc.home()["residents"]}
    assert pid not in {x["id"] for x in enc.home("someone-else-0123456789")["residents"]}
    prof = await enc.profile(pid)
    assert tuple(prof["era"]["window"]) == (1958, 1978)
    # Not in the shared lounge unless the visitor brings them.
    assert "Grandma" not in (await enc.lounge("movie"))["residents"]
    assert "Grandma" in (await enc.lounge("movie", extra=[pid]))["residents"]
    # The relation never leaves; only the family's words and structured values do.
    assert '"grandma"' not in fake.all_params_text()
    enc.remove_person(OWNER, pid)
    assert pid not in {x["id"] for x in enc.home(OWNER)["residents"]}


async def test_family_form_rejects_bad_input_and_limits_each_visitor(enc):
    import pytest
    with pytest.raises(ValueError):
        await enc.add_person(OWNER, "Tomasz W", 1940, "Kraków", "Poland", [("Czesław Niemen", "artist")])
    with pytest.raises(ValueError):
        await enc.add_person(OWNER, "Dad", 1940, "Atlantis", "Atlantis", [("Elvis", "artist")])
    for _ in range(4):
        await enc.add_person(OWNER, "Dad", 1950, "Memphis", "United States", [("Elvis Presley", "artist")])
    with pytest.raises(ValueError):
        await enc.add_person(OWNER, "Dad", 1950, "Memphis", "United States", [("Elvis Presley", "artist")])


async def test_family_form_over_http_needs_the_visitor_token(enc):
    with TestClient(create_app(enc, warm=False)) as c:
        body = {"relation": "Dad", "birth_year": 1952, "city": "Glasgow", "country": "United Kingdom",
                "favourites": [{"label": "Lulu", "kind": "artist"}]}
        assert c.post("/api/people", json=body).status_code == 400
        r = c.post("/api/people", json=body, headers={"x-encore-visitor": OWNER})
        assert r.status_code == 200
        pid = r.json()["id"]
        assert c.post(f"/api/people/{pid}/present", json={"present": True}).status_code == 400
        assert c.get("/api/week").status_code == 200
        assert c.delete(f"/api/people/{pid}", headers={"x-encore-visitor": OWNER}).json() == {"ok": True}
