"""Choosing for the lounge.

A film for fourteen people is usually chosen by the loudest voice or by what is most popular. Encore
builds a shortlist from each resident's own era shelf, asks Qloo how every resident's tastes rank
every film on that shortlist (`filter.results.entities`), and picks the film whose least-served
resident ranks it highest. Ties go to the higher average. Two common alternatives are scored the same
way so staff can see what each choice costs the least-served resident.

Music hour is a playlist. Encore fills it so that every resident present hears at least one artist
from near the top of their own ranking, then adds the songs the room ranks highest overall.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from . import roster, taste
from .qloo import AGE_BUCKET, Qloo
from .store import Store


def _minutes(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def candidate_pool(store: Store, qloo: Qloo, residents: list[dict], domain: str, per_person: int,
                         max_minutes: Optional[int], cap: int) -> tuple[list[dict], list[dict]]:
    shelves = await asyncio.gather(*[taste.shelf(store, qloo, r, domain, limit=per_person * 3) for r in residents])
    blocked = {t for r in residents for t in roster.avoid_tags(r)} | {t for t, _ in roster.home(store).get("house_rules", [])}
    blocked_entities = {e for r in residents for e in roster.avoid_entities(r)}
    pool: dict[str, dict] = {}
    excluded: list[dict] = []
    for r, s in zip(residents, shelves):
        taken = 0
        for it in s["items"]:
            if taken >= per_person:
                break
            why = None
            if it["entity_id"] in blocked_entities:
                why = "on a resident's avoid list"
            elif blocked & set(it.get("tag_ids") or []):
                why = "carries a tag on a resident's avoid list"
            elif domain == "movie" and max_minutes and (_minutes(it.get("duration")) or 0) > max_minutes:
                why = f"longer than {max_minutes} minutes"
            if why:
                excluded.append({"name": it["name"], "year": it["year"], "why": why})
                continue
            taken += 1
            c = pool.setdefault(it["entity_id"], {**it, "nominated_by": []})
            c["nominated_by"].append(r["first_name"])
    ranked = sorted(pool.values(), key=lambda c: (-len(c["nominated_by"]), -c["score"]))[:cap]
    return ranked, excluded


async def affinities(qloo: Qloo, residents: list[dict], pool: list[dict], domain: str) -> dict[str, dict[str, float]]:
    ids = [c["entity_id"] for c in pool]

    async def one(r: dict) -> tuple[str, dict[str, float]]:
        params: list[tuple[str, object]] = [("filter.type", f"urn:entity:{domain}"), ("filter.results.entities", ids),
                                            ("take", len(ids))]
        seeds = roster.seed_ids(r)
        if seeds:
            params.append(("signal.interests.entities", seeds))
        if domain != "artist":
            params.append(("signal.demographics.age", AGE_BUCKET))
        res = await qloo.insights(params, purpose="rank the lounge shortlist for one resident")
        aff = {e["entity_id"]: float((e.get("query") or {}).get("affinity") or 0) for e in res}
        # Qloo leaves a signal entity out of its own results; something the family named ranks first.
        top = max(aff.values(), default=0.0) + 0.001
        for i in ids:
            if i in seeds:
                aff[i] = top
        return r["id"], aff

    return dict(await asyncio.gather(*[one(r) for r in residents]))


def percentiles(aff: dict[str, float], ids: list[str]) -> dict[str, float]:
    """Where each candidate sits in this resident's own ranking: 1.0 is their top choice, 0.0 their last."""
    order = sorted(ids, key=lambda i: aff.get(i, 0.0))
    n = len(order)
    return {i: (k / (n - 1) if n > 1 else 1.0) for k, i in enumerate(order)}


def era_credit(resident: dict, cand: dict, domain: str) -> float:
    """Full credit when the item comes from the resident's ages 15-25, half credit outside 10-30."""
    if domain == "artist":
        w = taste.artist_era({"start_year": cand.get("start_year") or cand.get("year")}, resident["birth_year"])[0]
    else:
        w = taste.age_weight(cand["year"] - resident["birth_year"]) if cand.get("year") else 0.0
    return max(w, 0.5)


def score_candidates(residents: list[dict], pool: list[dict], aff: dict[str, dict[str, float]],
                     domain: str = "movie") -> list[dict]:
    """fit = where the item sits in the resident's own Qloo ranking x era credit."""
    ids = [c["entity_id"] for c in pool]
    pct = {r["id"]: percentiles(aff.get(r["id"], {}), ids) for r in residents}
    rows = []
    for c in pool:
        cid = c["entity_id"]
        per = []
        for r in residents:
            era = era_credit(r, c, domain)
            per.append({"id": r["id"], "name": r["first_name"], "rank_pct": round(pct[r["id"]][cid], 3),
                        "era": era, "pct": round(pct[r["id"]][cid] * era, 3),
                        "affinity": round(aff.get(r["id"], {}).get(cid, 0.0), 4)})
        worst = min(per, key=lambda x: x["pct"])
        rows.append({**{k: c.get(k) for k in ("entity_id", "name", "year", "image", "duration", "genres", "popularity",
                                              "nominated_by", "songs", "description", "country")},
                     "per_resident": per, "min_pct": worst["pct"], "least_served": worst["name"],
                     "mean_pct": round(sum(x["pct"] for x in per) / len(per), 3),
                     "mean_affinity": round(sum(x["affinity"] for x in per) / len(per), 4)})
    rows.sort(key=lambda r: (-r["min_pct"], -r["mean_pct"]))
    return rows


async def film_pick(store: Store, qloo: Qloo, residents: list[dict], max_minutes: Optional[int] = None) -> dict:
    max_minutes = max_minutes or roster.home(store).get("max_film_minutes") or 110
    pool, excluded = await candidate_pool(store, qloo, residents, "movie", per_person=2, max_minutes=max_minutes, cap=20)
    if not pool:
        return {"domain": "movie", "pick": None, "candidates": [], "excluded": excluded}
    aff = await affinities(qloo, residents, pool, "movie")
    rows = score_candidates(residents, pool, aff, "movie")
    pick = rows[0]
    crowd = max(rows, key=lambda r: (r["mean_affinity"], r["mean_pct"]))
    popular = max(rows, key=lambda r: r.get("popularity") or 0)
    return {"domain": "movie", "residents": [r["first_name"] for r in residents], "max_minutes": max_minutes,
            "pick": pick, "candidates": rows, "excluded": excluded,
            "alternatives": [{"rule": "Highest average affinity", **_alt(crowd)},
                             {"rule": "Most popular film on the shortlist", **_alt(popular)}],
            "rule": "Best fit for the least-served resident, then best average fit. Fit is the film's place in "
                    "that resident's own Qloo ranking, with half credit when it falls outside their ages 10 to 30"}


def _alt(r: dict) -> dict:
    return {"name": r["name"], "year": r["year"], "min_pct": r["min_pct"], "least_served": r["least_served"],
            "mean_pct": r["mean_pct"]}


async def music_hour(store: Store, qloo: Qloo, residents: list[dict], length: int = 12) -> dict:
    pool, excluded = await candidate_pool(store, qloo, residents, "artist", per_person=3, max_minutes=None, cap=36)
    if not pool:
        return {"domain": "artist", "playlist": [], "coverage": []}
    aff = await affinities(qloo, residents, pool, "artist")
    scored = score_candidates(residents, pool, aff, "artist")
    rows = {r["entity_id"]: r for r in scored}
    ids = list(rows)
    pct = {r["id"]: {row["entity_id"]: next(x["pct"] for x in row["per_resident"] if x["id"] == r["id"])
                     for row in scored} for r in residents}
    playlist: list[str] = []
    served: dict[str, float] = {r["id"]: 0.0 for r in residents}
    # First pass: the least-served resident gets their best remaining artist, until everyone has one
    # in their own top quarter or the playlist is full.
    while len(playlist) < length:
        need = [r for r in residents if served[r["id"]] < 0.6]
        if not need:
            break
        r = min(need, key=lambda r: (served[r["id"]], r["first_name"]))
        best = max((i for i in ids if i not in playlist), key=lambda i: pct[r["id"]][i], default=None)
        if best is None:
            break
        playlist.append(best)
        for x in residents:
            served[x["id"]] = max(served[x["id"]], pct[x["id"]][best])
        if served[r["id"]] < 0.6:  # nothing left that fits this resident better
            served[r["id"]] = 0.6
    for i in sorted(ids, key=lambda i: -rows[i]["mean_pct"]):
        if len(playlist) >= length:
            break
        if i not in playlist:
            playlist.append(i)
    coverage = []
    for r in residents:
        best = max(playlist, key=lambda i: pct[r["id"]][i])
        coverage.append({"name": r["first_name"], "best": rows[best]["name"], "pct": round(pct[r["id"]][best], 3)})
    return {"domain": "artist", "residents": [r["first_name"] for r in residents],
            "playlist": [{**rows[i], "song": (rows[i].get("songs") or [None])[0]} for i in playlist],
            "coverage": coverage, "excluded": excluded,
            "rule": "Every resident hears an artist that fits them well (fit 0.6 or more where one exists), "
                    "least-served first, then the room's favourites"}
