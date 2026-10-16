"""The culture of a resident's youth, from Qloo.

Reminiscence work leans on the "reminiscence bump": people recall far more from ages 10 to 30
than from any other period, with a peak in the late teens and early twenties. Encore asks Qloo for
films, TV and books released in that window, and for artists who were active in it, seeded by the
family's favourites and, in a second lane, by the resident's home country. Code then weights each
result by the age the resident was at the time and merges the lanes.

Qloo's affinity is relative and describes audiences. Encore uses it to order a shelf, never as a
statement about what one person will feel.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Optional

from . import roster
from .qloo import AGE_BUCKET, Qloo, QlooUnavailable
from .store import Store

DOMAINS = {
    "artist": {"label": "Songs and singers", "take": 50},
    "movie": {"label": "Films", "take": 25},
    "tv_show": {"label": "Television", "take": 15},
    "book": {"label": "Books", "take": 10},
}
YEAR_FILTER = {"movie": "filter.release_year", "tv_show": "filter.release_year", "book": "filter.publication_year"}
READABLE_TAGS = ("urn:tag:genre:", "urn:tag:theme:qloo", "urn:tag:style:qloo", "urn:tag:instrument:", "urn:tag:keyword:media")


def window(birth_year: int) -> tuple[int, int]:
    return birth_year + 10, birth_year + 30


def age_weight(age: int) -> float:
    """1.0 across ages 15-25, easing to 0.7 at 10 and at 30, zero outside 10-30."""
    if 15 <= age <= 25:
        return 1.0
    if 10 <= age < 15:
        return round(0.7 + 0.06 * (age - 10), 3)
    if 25 < age <= 30:
        return round(1.0 - 0.06 * (age - 25), 3)
    return 0.0


def _year(v) -> Optional[int]:
    if v is None:
        return None
    m = re.match(r"^(\d{4})", str(v))
    return int(m.group(1)) if m else None


def artist_era(props: dict, birth_year: int) -> tuple[float, Optional[int], Optional[int]]:
    """Weight of an artist for this person: the best age_weight over the years the artist was active
    inside the person's ages 10-30. Returns (weight, start_year, year_used)."""
    start = _year(props.get("start_year"))
    if start is None and props.get("date_of_birth"):
        start = (_year(props["date_of_birth"]) or 0) + 20 or None
    if start is None:
        return 0.0, None, None
    end = _year(props.get("end_year")) or _year(props.get("year_of_death")) or 2100
    lo, hi = window(birth_year)
    best, used = 0.0, None
    for y in range(max(start, lo), min(end, hi) + 1):
        w = age_weight(y - birth_year)
        if w > best:
            best, used = w, y
    return best, start, used


def media_year(item: dict) -> Optional[int]:
    p = item.get("properties") or {}
    return _year(p.get("release_year")) or _year(p.get("publication_year")) or _year(p.get("release_date"))


@dataclass
class Lane:
    name: str
    params: list[tuple[str, object]]


async def music_tag(qloo: Qloo, term: Optional[str]) -> Optional[str]:
    return await _genre_tag(qloo, term, "urn:tag:genre:music:")


async def cuisine_tag(qloo: Qloo, term: Optional[str]) -> Optional[str]:
    return await _genre_tag(qloo, term, "urn:tag:genre:place:restaurant:")


async def _genre_tag(qloo: Qloo, term: Optional[str], prefix: str) -> Optional[str]:
    if not term:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")
    tags = await qloo.tags(term, purpose="find a genre tag")
    ids = [t.get("id") or t.get("tag_id") for t in tags]
    if prefix + slug in ids:
        return prefix + slug
    return next((i for i in ids if i and i.startswith(prefix + slug.split("_")[0])), None)


def _seed_names(p: dict) -> dict[str, str]:
    return {f["entity_id"]: (f["entity_name"] or f["label"]) for f in p["favourites"] if f["entity_id"]}


def cooled_down(store: Store, pid: str) -> list[str]:
    rows = store.q("SELECT DISTINCT entity_id FROM reactions WHERE person_id=? AND reaction='no_response' "
                   "AND at > datetime('now','-14 days')", (pid,))
    return [r["entity_id"] for r in rows]


ERA_MUSIC_TAG = "urn:tag:genre:music:oldies"


async def lanes_for(qloo: Qloo, p: dict, domain: str) -> list[Lane]:
    """Two lanes per domain: the family's favourites, and home (country of release, or the home
    country's music genre). Artists have no release-year filter in Qloo, so the music lanes add the
    oldies genre and code checks each artist's active years. The 55-and-older age signal is left off
    for artists: it describes today's over-55 audience, whose youth was decades later than a
    resident born in the 1930s, and it pushed every artist outside the window in testing."""
    seeds = roster.seed_ids(p)
    lo, hi = window(p["birth_year"])
    base: list[tuple[str, object]] = [("filter.type", f"urn:entity:{domain}"), ("take", DOMAINS[domain]["take"]),
                                      ("feature.explainability", True)]
    if domain != "artist":
        base.append(("signal.demographics.age", AGE_BUCKET))
    if domain in YEAR_FILTER:
        f = YEAR_FILTER[domain]
        base += [(f + ".min", lo - (5 if domain == "tv_show" else 0)), (f + ".max", hi)]
    excluded = roster.avoid_tags(p) + [t for t, _ in p.get("house_rules", [])]
    if domain in ("movie", "tv_show") and excluded:
        base.append(("filter.exclude.tags", list(dict.fromkeys(excluded))))
    sig = [("signal.interests.entities", seeds)] if seeds else []
    lanes: list[Lane] = []
    if seeds:
        lanes.append(Lane("family favourites", base + sig + ([("filter.tags", ERA_MUSIC_TAG)] if domain == "artist" else [])))
    home: list[tuple[str, object]] = []
    if domain in ("movie", "tv_show") and p.get("country"):
        home = [("filter.release_country", p["country"])]
    elif domain == "artist" and p.get("music_genre"):
        tag = await music_tag(qloo, p["music_genre"])
        if tag:
            home = [("filter.tags", tag)]
    if home and (seeds or domain != "artist"):
        lanes.insert(0, Lane("home", base + home + sig))
    return lanes


def interleave(per_lane: list[list[dict]]) -> list[dict]:
    """Round-robin across lanes so a shelf is never all Hollywood for someone who grew up in Kraków."""
    out, seen = [], set()
    for i in range(max((len(x) for x in per_lane), default=0)):
        for lane in per_lane:
            if i < len(lane) and lane[i]["entity_id"] not in seen:
                seen.add(lane[i]["entity_id"])
                out.append(lane[i])
    return out


async def shelf(store: Store, qloo: Qloo, p: dict, domain: str, limit: int = 12) -> dict:
    """One domain of the resident's era profile, scored and explained."""
    b = p["birth_year"]
    seeds = set(roster.seed_ids(p))
    names = _seed_names(p)
    skip = seeds | set(roster.avoid_entities(p)) | set(cooled_down(store, p["id"]))
    lanes = await lanes_for(qloo, p, domain)
    results = await asyncio.gather(*[qloo.insights(l.params, purpose=f"{DOMAINS[domain]['label'].lower()} of their youth "
                                                  f"({l.name} lane)") for l in lanes], return_exceptions=True)
    per_lane: list[list[dict]] = []
    lanes_of: dict[str, list[str]] = {}
    dropped_era = 0
    errors = [str(r) for r in results if isinstance(r, Exception)]
    for lane, res in zip(lanes, results):
        bucket: list[dict] = []
        if not isinstance(res, Exception):
            for e in res:
                eid = e.get("entity_id")
                if not eid or eid in skip:
                    continue
                props = e.get("properties") or {}
                if domain == "artist":
                    w, year, year_used = artist_era(props, b)
                else:
                    year = media_year(e)
                    w = age_weight(year - b) if year else 0.0
                    year_used = year
                if w <= 0:
                    dropped_era += 1
                    continue
                aff = float((e.get("query") or {}).get("affinity") or 0)
                expl = ((e.get("query") or {}).get("explainability") or {}).get("signal.interests.entities") or []
                because = [names[x["entity_id"]] for x in sorted(expl, key=lambda x: -x.get("score", 0))
                           if x.get("entity_id") in names and x.get("score", 0) > 0.2][:2]
                lanes_of.setdefault(eid, []).append(lane.name)
                bucket.append(_item(e, domain, year, year_used, b, aff, w, aff * w, [], because))
        bucket.sort(key=lambda x: -x["score"])
        per_lane.append(bucket)
    items = interleave(per_lane)
    for it in items:
        it["lanes"] = lanes_of.get(it["entity_id"], [])
    return {"domain": domain, "label": DOMAINS[domain]["label"], "window": window(b), "items": items[:limit],
            "considered": sum(len(r) for r in results if not isinstance(r, Exception)), "outside_era": dropped_era,
            "lanes": [l.name for l in lanes], "errors": errors}


def _item(e: dict, domain: str, year, year_used, birth: int, aff: float, w: float, score: float,
          lanes: list[str], because: list[str]) -> dict:
    p = e.get("properties") or {}
    ext = e.get("external") or {}
    genre_tags = [{"tag_id": t.get("tag_id") or t.get("id"), "name": t["name"]} for t in (e.get("tags") or [])
                  if str(t.get("type", "")).startswith("urn:tag:genre") and t.get("name")][:4]
    genres = list(dict.fromkeys(g["name"] for g in genre_tags))[:3]
    out = {
        "entity_id": e["entity_id"], "name": e.get("name"), "type": domain, "year": year,
        "age_then": (year_used - birth) if year_used else None, "image": (p.get("image") or {}).get("url"),
        "affinity": round(aff, 4), "era_weight": w, "score": round(score, 4), "lanes": lanes, "because": because,
        "genres": genres, "genre_tags": genre_tags, "popularity": round(float(e.get("popularity") or 0), 4),
        "description": p.get("short_description") or (p.get("short_descriptions") or [None])[0] if isinstance(p.get("short_descriptions"), list) else p.get("short_description"),
        "tag_ids": [t.get("tag_id") or t.get("id") for t in (e.get("tags") or [])][:40],
    }
    if domain == "artist":
        out["start_year"] = _year(p.get("start_year"))
        out["songs"] = (p.get("notable_songs") or [])[:4]
        sp = (ext.get("spotify") or {})
        out["spotify_id"] = sp.get("id") if isinstance(sp, dict) else None
    if domain == "movie":
        out["duration"] = p.get("duration")
        out["country"] = p.get("release_country")
        out["content_rating"] = p.get("content_rating")
    if domain == "tv_show":
        out["country"] = p.get("release_country")
    return out


async def era_profile(store: Store, qloo: Qloo, p: dict, limit: int = 10) -> dict:
    shelves = await asyncio.gather(*[shelf(store, qloo, p, d, limit) for d in DOMAINS])
    return {"person_id": p["id"], "window": window(p["birth_year"]), "shelves": {s["domain"]: s for s in shelves}}


async def seed_details(qloo: Qloo, p: dict) -> list[dict]:
    """The family's own favourites with Qloo's full details (songs, year, image). Insights with
    `filter.results.entities` returns the complete entity record, one call per kind."""
    fams = [f for f in p["favourites"] if f["source"] == "family"]
    by_kind: dict[str, list[str]] = {}
    for f in fams:
        if f["entity_id"]:
            by_kind.setdefault(f["kind"], []).append(f["entity_id"])

    async def fetch(kind: str, ids: list[str]) -> list[dict]:
        try:
            return await qloo.insights([("filter.type", f"urn:entity:{kind}"), ("filter.results.entities", ids),
                                        ("take", len(ids))], purpose="details of the family's favourites")
        except QlooUnavailable:
            return []

    found = await asyncio.gather(*[fetch(k, v) for k, v in by_kind.items()])
    ents = {e.get("entity_id"): e for batch in found for e in batch}
    out = []
    for f in fams:
        props = (ents.get(f["entity_id"]) or {}).get("properties") or {}
        out.append({"id": f["id"], "label": f["label"], "kind": f["kind"], "status": f["status"],
                    "source": f["source"], "entity_id": f["entity_id"], "name": f["entity_name"] or f["label"],
                    "year": _year(props.get("release_year")) or _year(props.get("start_year")),
                    "image": (props.get("image") or {}).get("url"), "songs": (props.get("notable_songs") or [])[:4],
                    "description": props.get("short_description") or props.get("description")})
    return out


async def taste_of_home(qloo: Qloo, p: dict, town: str, radius_m: int) -> dict:
    """Restaurants near the home that serve the food of the resident's youth, ordered by Qloo for
    people who share the resident's tastes."""
    tag = await cuisine_tag(qloo, p.get("cuisine"))
    if not tag:
        return {"tag": None, "places": []}
    params: list[tuple[str, object]] = [("filter.type", "urn:entity:place"), ("filter.location.query", town),
                                        ("filter.location.radius", radius_m), ("filter.tags", tag), ("take", 6)]
    seeds = roster.seed_ids(p)
    if seeds:
        params.append(("signal.interests.entities", seeds))
    res = await qloo.insights(params, purpose="food of their youth near the home")
    places = []
    for e in res:
        pr = e.get("properties") or {}
        dishes = [d.get("name") if isinstance(d, dict) else d for d in (pr.get("specialty_dishes") or [])][:4]
        tags = [t.get("name", "") for t in (e.get("tags") or [])]
        places.append({"entity_id": e["entity_id"], "name": e.get("name"), "address": pr.get("address"),
                       "distance_km": round(((e.get("query") or {}).get("distance") or 0) / 1000, 1),
                       "dishes": [d for d in dishes if d], "price_level": pr.get("price_level"),
                       "wheelchair": any("wheelchair" in t.lower() for t in tags),
                       "affinity": round(float((e.get("query") or {}).get("affinity") or 0), 4),
                       "image": (pr.get("image") or {}).get("url"), "phone": pr.get("phone")})
    return {"tag": tag, "places": places}


def readable_tags(tags: list[dict], limit: int = 8) -> list[dict]:
    out = []
    for t in tags:
        tid = t.get("tag_id") or t.get("id") or ""
        if tid.startswith(READABLE_TAGS) and t.get("name"):
            out.append({"tag_id": tid, "name": t["name"], "type": t.get("subtype") or t.get("type")})
    return out[:limit]
