"""The week's programme for the whole home.

Three decisions a coordinator makes every Monday, each computed from Qloo:

- **Two lounge films chosen together.** One film leaves someone least served. Two films chosen as a
  pair can give every resident one film near the top of their own ranking. Encore scores every pair
  on the shortlist by its least-served resident's better film, using the same per-resident Qloo
  rankings as the lounge pick, so no extra Qloo request is made.
- **Who sits with whom.** Qloo's Compare scores the tastes each resident shares with each carer.
  Encore assigns the one-to-ones so each carer has a fair share and the pairs with the most to talk
  about are kept, and shows what an alphabetical rota would give instead.
- **When.** Residents with a staff flag go first, then those the films serve least.
"""
from __future__ import annotations

import asyncio
import math
from itertools import combinations
from typing import Optional

from . import group, roster
from .qloo import Qloo, QlooUnavailable
from .store import Store

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def best_pair(rows: list[dict]) -> Optional[tuple[dict, dict, float, float]]:
    """The two films whose least-served resident's better film fits best; ties go to the higher average."""
    if len(rows) < 2:
        return None
    fits = [{x["id"]: x["pct"] for x in r["per_resident"]} for r in rows]
    best, key = None, None
    for i, j in combinations(range(len(rows)), 2):
        both = [max(fits[i][rid], fits[j][rid]) for rid in fits[i]]
        k = (round(min(both), 3), round(sum(both) / len(both), 3), -i - j)
        if key is None or k > key:
            best, key = (rows[i], rows[j], k[0], k[1]), k
    return best


def pair_floor(a: dict, b: dict) -> tuple[float, str]:
    fb = {x["id"]: x["pct"] for x in b["per_resident"]}
    both = [(max(x["pct"], fb[x["id"]]), x["name"]) for x in a["per_resident"]]
    low = min(both)
    return round(low[0], 3), low[1]


MATCH_KINDS = ("urn:tag:genre:music", "urn:tag:genre:media", "urn:tag:instrument:music", "urn:tag:theme:qloo")


def _names(xs: list) -> list[str]:
    return list(dict.fromkeys(x.get("name") for x in xs or [] if x.get("name")))


async def match(qloo: Qloo, resident: dict, carer: dict) -> dict:
    """How much a resident and a carer have to talk about. Qloo's Compare returns the tags both
    people's favourites carry, each with a score and the favourites on each side behind it. The match
    is the summed score of the distinct genres, instruments and themes they share."""
    a, b = roster.seed_ids(resident), roster.seed_ids(carer)
    empty = {"carer": carer["id"], "score": 0.0, "n": 0, "shared": [], "link": None}
    if not a or not b:
        return empty
    try:
        res = await qloo.compare(a, b, purpose="how much a resident and a carer share (weekly rota)")
    except QlooUnavailable:
        return empty
    seen: set[str] = set()
    items = []
    for t in sorted(res.get("tags") or [], key=lambda t: -float((t.get("query") or {}).get("score") or 0)):
        kind = str(t.get("subtype") or t.get("type") or "")
        name = (t.get("name") or "").strip()
        if not kind.startswith(MATCH_KINDS) or not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        q = t.get("query") or {}
        items.append({"name": name, "score": float(q.get("score") or 0),
                      "resident_side": _names(q.get("a.signal.interests.entities"))[:1],
                      "carer_side": _names(q.get("b.signal.interests.entities"))[:1]})
    link = next((i for i in items if i["resident_side"] and i["carer_side"]), None)
    return {"carer": carer["id"], "score": round(sum(i["score"] for i in items), 2), "n": len(items),
            "shared": [i["name"] for i in items[:4]],
            "link": link and {"tag": link["name"], "resident": link["resident_side"][0], "carer": link["carer_side"][0]}}


def assign(residents: list[dict], carers: list[dict], scores: dict[str, dict[str, dict]]) -> dict[str, str]:
    """Each carer takes at most ceil(n / carers) one-to-ones. Residents whose best carer matters most
    (largest gap to their second choice) choose first, so a strong pair is not lost to a weak one."""
    cap = math.ceil(len(residents) / max(len(carers), 1))
    load = {c["id"]: 0 for c in carers}

    def prefs(r: dict) -> list[str]:
        return sorted(load, key=lambda cid: (-scores[r["id"]][cid]["score"], cid))

    def regret(r: dict) -> float:
        s = sorted((scores[r["id"]][c]["score"] for c in load), reverse=True)
        return s[0] - (s[1] if len(s) > 1 else 0)

    out: dict[str, str] = {}
    for r in sorted(residents, key=lambda r: (-regret(r), r["first_name"])):
        cid = next(c for c in prefs(r) if load[c] < cap)
        out[r["id"]] = cid
        load[cid] += 1
    return out


def rota(residents: list[dict], carers: list[dict]) -> dict[str, str]:
    """The usual way: residents in alphabetical order, dealt to carers in turn."""
    ordered = sorted(residents, key=lambda r: r["first_name"])
    return {r["id"]: carers[i % len(carers)]["id"] for i, r in enumerate(ordered)}


async def plan_week(store: Store, qloo: Qloo, residents: list[dict], carers: list[dict]) -> dict:
    film, music = await asyncio.gather(group.film_pick(store, qloo, residents), group.music_hour(store, qloo, residents))
    rows = film.get("candidates") or []
    films: dict = {"single": None, "pair": None, "separately": None}
    week_fit: dict[str, float] = {}
    if rows:
        single = rows[0]
        films["single"] = {"name": single["name"], "year": single["year"], "image": single.get("image"),
                           "floor": single["min_pct"], "least_served": single["least_served"]}
        pair = best_pair(rows)
        if pair:
            a, b, floor, mean = pair
            low = pair_floor(a, b)
            fb = {x["id"]: x["pct"] for x in b["per_resident"]}
            week_fit = {x["id"]: max(x["pct"], fb[x["id"]]) for x in a["per_resident"]}
            first, second = sorted((a, b), key=lambda r: -r["mean_pct"])
            films["pair"] = {"films": [_film(first), _film(second)], "floor": floor, "mean": mean,
                             "least_served": low[1],
                             "per_resident": [{"id": x["id"], "name": x["name"], "tuesday": x["pct"],
                                               "thursday": next(y["pct"] for y in second["per_resident"] if y["id"] == x["id"])}
                                              for x in first["per_resident"]]}
            sep = pair_floor(rows[0], rows[1])
            films["separately"] = {"films": [rows[0]["name"], rows[1]["name"]], "floor": sep[0], "least_served": sep[1]}

    pairs = [(r, c) for r in residents for c in carers]
    found = await asyncio.gather(*[match(qloo, r, c) for r, c in pairs])
    scores: dict[str, dict[str, dict]] = {}
    for (r, c), m in zip(pairs, found):
        scores.setdefault(r["id"], {})[c["id"]] = m
    chosen = assign(residents, carers, scores) if carers else {}
    usual = rota(residents, carers) if carers else {}

    def total(a: dict[str, str]) -> float:
        return round(sum(scores[rid][cid]["score"] for rid, cid in a.items()), 3)

    def count(a: dict[str, str]) -> int:
        return sum(scores[rid][cid]["n"] for rid, cid in a.items())

    order = sorted(residents, key=lambda r: (not r.get("care_note"), week_fit.get(r["id"], 1.0), r["first_name"]))
    per_day = math.ceil(len(order) / len(DAYS)) if order else 0
    names = {c["id"]: c["first_name"] for c in carers}
    one_to_ones = []
    for i, r in enumerate(order):
        cid = chosen.get(r["id"])
        m = scores.get(r["id"], {}).get(cid, {}) if cid else {}
        one_to_ones.append({"day": DAYS[min(i // per_day, len(DAYS) - 1)] if per_day else DAYS[0],
                            "resident": {"id": r["id"], "first_name": r["first_name"], "city": r["city"],
                                         "flag": bool(r.get("care_note"))},
                            "carer": {"id": cid, "first_name": names.get(cid)}, "shared": m.get("shared", []),
                            "link": m.get("link"),
                            "score": m.get("score", 0.0), "n": m.get("n", 0),
                            "rota_carer": names.get(usual.get(r["id"])),
                            "week_fit": round(week_fit.get(r["id"], 0.0), 3) if week_fit else None})
    matrix = [{"resident": r["first_name"], "id": r["id"],
               "carers": [{"carer": c["first_name"], "id": c["id"], "score": scores[r["id"]][c["id"]]["score"],
                           "n": scores[r["id"]][c["id"]]["n"],
                           "chosen": chosen.get(r["id"]) == c["id"]} for c in carers]} for r in residents]
    lounge = []
    if films["pair"]:
        f1, f2 = films["pair"]["films"]
        lounge = [{"day": "Tuesday", "kind": "film", **f1}, {"day": "Thursday", "kind": "film", **f2}]
    if music.get("playlist"):
        lounge.append({"day": "Wednesday", "kind": "music", "name": "Music hour",
                       "artists": [x["name"] for x in music["playlist"][:6]],
                       "covered": sum(1 for c in music.get("coverage", []) if c["pct"] >= 0.6),
                       "of": len(music.get("coverage", []))})
    return {"residents": len(residents), "carers": [{"id": c["id"], "first_name": c["first_name"]} for c in carers],
            "films": films, "lounge": lounge, "one_to_ones": one_to_ones, "matrix": matrix,
            "pairing": {"chosen_total": total(chosen), "rota_total": total(usual),
                        "chosen_shared": count(chosen), "rota_shared": count(usual),
                        "cap": math.ceil(len(residents) / max(len(carers), 1)),
                        "rule": "Each carer takes at most an even share. Residents with the clearest best match choose first."},
            "rule": "Films: the pair whose least-served resident's better film fits best. Fit is the film's place in "
                    "that resident's own Qloo ranking, with half credit outside their ages 10 to 30."}


def _film(r: dict) -> dict:
    return {"entity_id": r["entity_id"], "name": r["name"], "year": r["year"], "image": r.get("image"),
            "duration": r.get("duration"), "genres": r.get("genres") or [], "min_pct": r["min_pct"],
            "mean_pct": r["mean_pct"], "least_served": r["least_served"]}
