"""A synthetic stand-in for the Qloo API, used by the tests.

It implements the parameters Encore relies on (type, year ranges, results.entities, exclude
entities/tags, tags filter, explainability) over a generated catalogue, and records every request so
tests can assert what would have left the building. No Qloo data is stored in this repository.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from urllib.parse import parse_qsl, urlparse

import httpx

TYPES = ("artist", "movie", "tv_show", "book")


def _id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name)).upper()


def _h(*parts: str) -> float:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _catalogue() -> list[dict]:
    out = []
    countries = ["Poland", "Mexico", "United States", "Ireland", "Italy"]
    for t in TYPES:
        for k in range(60):
            year = 1920 + (k * 7) % 100
            name = f"{t.title()} {k:02d}"
            e = {"name": name, "entity_id": _id(name), "subtype": f"urn:entity:{t}", "popularity": round(_h(name), 3),
                 "properties": {"image": {"url": f"https://images.qloo.com/i/{_id(name)}-420x-auto.jpg"}},
                 "tags": [{"tag_id": f"urn:tag:genre:media:{'war' if k % 9 == 0 else 'drama'}", "name": "War" if k % 9 == 0 else "Drama",
                           "type": "urn:tag:genre:media"}],
                 "_country": countries[k % len(countries)]}
            p = e["properties"]
            if t == "artist":
                p["start_year"] = year
                p["notable_songs"] = [f"Song of {name}"]
                e["tags"] = [{"tag_id": "urn:tag:genre:music:oldies" if year < 1975 else "urn:tag:genre:music:pop",
                              "name": "Oldies", "type": "urn:tag:genre:music"},
                             {"tag_id": f"urn:tag:genre:music:{countries[k % 5].lower()}", "name": countries[k % 5],
                              "type": "urn:tag:genre:music"}]
            elif t == "book":
                p["publication_year"] = year
            else:
                p["release_year"] = year
                p["release_country"] = [e["_country"]]
                p["duration"] = 85 + (k * 5) % 60
            out.append(e)
    # Named entities the demo home's favourites resolve to.
    for name, t, year in [("Czesław Niemen", "artist", 1962), ("Irena Santor", "artist", 1950), ("The Cruise", "movie", 1970),
                          ("West Side Story", "movie", 2021), ("West Side Story", "movie", 1961), ("Frank Sinatra", "artist", 1935)]:
        e = {"name": name, "entity_id": _id(f"{name}{year}"), "subtype": f"urn:entity:{t}", "popularity": 0.95,
             "properties": {"start_year" if t == "artist" else "release_year": year, "notable_songs": [f"{name} hit"]},
             "tags": [], "_country": "Poland"}
        out.append(e)
    return out


class FakeQloo:
    def __init__(self) -> None:
        self.catalogue = _catalogue()
        self.requests: list[tuple[str, list[tuple[str, str]]]] = []
        self.fail_next: list[int] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        params = parse_qsl(url.query, keep_blank_values=True)
        self.requests.append((url.path, params))
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"error": "synthetic failure"})
        q = {}
        for k, v in params:
            q[k] = v
        if url.path == "/search":
            return httpx.Response(200, json={"results": self.search(q)})
        if url.path == "/v2/tags":
            term = q.get("filter.query", "").lower().replace(" ", "_")
            return httpx.Response(200, json={"results": {"tags": [
                {"id": f"urn:tag:genre:music:{term}", "name": term}, {"id": f"urn:tag:genre:place:restaurant:{term}", "name": term}]}})
        if url.path == "/v2/insights":
            return httpx.Response(200, json={"success": True, "results": self.insights(q)})
        if url.path == "/v2/analysis/compare":
            return httpx.Response(200, json={"results": {"tags": [
                {"tag_id": "urn:tag:genre:music:folk", "name": "Folk", "subtype": "urn:tag:genre:music", "query": {"score": 0.9}},
                {"tag_id": "urn:tag:audience:qloo:loyal", "name": "Loyal", "subtype": "urn:tag:audience:qloo", "query": {"score": 0.8}}]}})
        return httpx.Response(404, json={"error": "not found"})

    def _public(self, e: dict) -> dict:
        return {k: v for k, v in e.items() if not k.startswith("_")}

    def search(self, q: dict) -> list[dict]:
        term = q.get("query", "").lower()
        t = q.get("types", "").split(":")[-1]
        hits = [e for e in self.catalogue if term in e["name"].lower() and (not t or e["subtype"].endswith(t))]
        if not hits and term and term != "rejs":  # every other name the family types exists in this catalogue
            e = {"name": q["query"], "entity_id": _id(term + t), "subtype": f"urn:entity:{t or 'artist'}", "popularity": 0.9,
                 "properties": {"start_year" if t == "artist" else "release_year": 1950, "notable_songs": [f"{q['query']} hit"]},
                 "tags": [], "_country": "Mexico"}
            self.catalogue.append(e)
            hits = [e]
        return [self._public({**e, "types": [e["subtype"]]}) for e in hits][: int(q.get("take", 5))]

    def insights(self, q: dict) -> dict:
        t = q["filter.type"].split(":")[-1]
        if t == "place":
            return {"entities": [{"name": f"Place {i}", "entity_id": _id(f"place{i}"), "properties": {"address": "1 Main St",
                                  "specialty_dishes": [{"name": "Pierogi"}]}, "tags": [{"name": "Wheelchair accessible entrance"}],
                                  "query": {"distance": 4200 + i * 1000, "affinity": 0.9 - i / 10}} for i in range(3)]}
        ents = [e for e in self.catalogue if e["subtype"].endswith(t)]
        y = {"movie": "release_year", "tv_show": "release_year", "book": "publication_year"}.get(t)
        for f in ("filter.release_year", "filter.publication_year"):
            if f + ".min" in q and y:
                ents = [e for e in ents if e["properties"].get(y, 0) >= int(q[f + ".min"])]
            if f + ".max" in q and y:
                ents = [e for e in ents if e["properties"].get(y, 9999) <= int(q[f + ".max"])]
        if "filter.results.entities" in q:
            ids = q["filter.results.entities"].split(",")
            ents = [e for e in ents if e["entity_id"] in ids]
        if "filter.exclude.entities" in q:
            ex = set(q["filter.exclude.entities"].split(","))
            ents = [e for e in ents if e["entity_id"] not in ex]
        if "filter.exclude.tags" in q:
            ex = set(q["filter.exclude.tags"].split(","))
            ents = [e for e in ents if not ex & {tg["tag_id"] for tg in e["tags"]}]
        if "filter.tags" in q:
            want = set(q["filter.tags"].split(","))
            ents = [e for e in ents if want & {tg["tag_id"] for tg in e["tags"]}]
        if "filter.release_country" in q:
            ents = [e for e in ents if e["_country"] == q["filter.release_country"]]
        seeds = q.get("signal.interests.entities", "").split(",") if q.get("signal.interests.entities") else []
        if not seeds and "filter.results.entities" not in q and "filter.tags" not in q and "filter.release_country" not in q:
            return {"entities": []}
        scored = []
        for e in ents:
            aff = round(0.5 + 0.5 * _h(e["entity_id"], *seeds), 4)
            item = self._public(e)
            item["query"] = {"affinity": aff}
            if q.get("feature.explainability") == "true" and seeds:
                item["query"]["explainability"] = {"signal.interests.entities": [
                    {"entity_id": s, "score": round(1 / len(seeds), 3)} for s in seeds]}
            scored.append(item)
        scored.sort(key=lambda x: -x["query"]["affinity"])
        return {"entities": scored[: int(q.get("take", 20))]}

    def all_params_text(self) -> str:
        return json.dumps(self.requests, ensure_ascii=False).lower()
