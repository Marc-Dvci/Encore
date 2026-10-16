"""Common ground between a resident and the carer sitting with them.

Priya is 26 and grew up in Kochi; Tomasz is 89 and grew up in Kraków. Qloo's Compare finds the tastes
their favourites share, and a bridge pick finds an artist and a film from his youth that Qloo's
explainability shows both of their favourites pulling toward.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from . import roster, taste
from .qloo import Qloo

SHARED_KINDS = ("urn:tag:genre:music", "urn:tag:genre:media", "urn:tag:theme:qloo", "urn:tag:style:qloo")


async def common_ground(qloo: Qloo, resident: dict, carer: dict) -> dict:
    a, b = roster.seed_ids(resident), roster.seed_ids(carer)
    if not a or not b:
        return {"shared": [], "bridges": []}
    lo, hi = taste.window(resident["birth_year"])
    cmp_task = qloo.compare(a, b, purpose="tastes a resident and a carer share")
    art_task = qloo.insights([("filter.type", "urn:entity:artist"), ("signal.interests.entities", a + b),
                              *taste.era_music_tags(resident["birth_year"]), ("feature.explainability", True), ("take", 30)],
                             purpose="a song from their youth that both people's tastes point to")
    mov_task = qloo.insights([("filter.type", "urn:entity:movie"), ("signal.interests.entities", a + b),
                              ("filter.release_year.min", lo), ("filter.release_year.max", hi),
                              ("feature.explainability", True), ("take", 30)],
                             purpose="a film from their youth that both people's tastes point to")
    cmp, arts, movs = await asyncio.gather(cmp_task, art_task, mov_task, return_exceptions=True)
    shared = []
    if isinstance(cmp, dict):
        for t in cmp.get("tags") or []:
            kind = t.get("subtype") or t.get("type") or ""
            if kind.startswith(SHARED_KINDS):
                shared.append({"name": t["name"], "kind": kind.split(":")[2] if kind.count(":") >= 2 else kind,
                               "score": round(float((t.get("query") or {}).get("score") or 0), 3)})
    bridges = []
    for dom, res in (("artist", arts), ("movie", movs)):
        if isinstance(res, Exception):
            continue
        best = _bridge(res, a, b, resident["birth_year"] if dom == "artist" else None)
        if best:
            bridges.append({"type": dom, **best})
    return {"shared": shared[:6], "bridges": bridges, "resident": resident["first_name"], "carer": carer["first_name"]}


def _bridge(ents: list[dict], a: list[str], b: list[str], birth_year: Optional[int]) -> Optional[dict]:
    best, best_key = None, None
    for e in ents:
        if birth_year is not None and taste.artist_era(e.get("properties") or {}, birth_year)[0] <= 0:
            continue
        ex = {x["entity_id"]: x.get("score", 0) for x in
              ((e.get("query") or {}).get("explainability") or {}).get("signal.interests.entities") or []}
        sa, sb = sum(ex.get(i, 0) for i in a), sum(ex.get(i, 0) for i in b)
        key = (round(min(sa, sb) * 10) / 10, float(e.get("popularity") or 0))
        if best_key is None or key > best_key:
            p = e.get("properties") or {}
            best_key = key
            best = {"entity_id": e["entity_id"], "name": e.get("name"),
                    "year": taste.media_year(e) or p.get("start_year"), "image": (p.get("image") or {}).get("url"),
                    "songs": (p.get("notable_songs") or [])[:3], "resident_share": round(sa / (sa + sb), 2) if sa + sb else 0,
                    "description": p.get("short_description")}
    return best
