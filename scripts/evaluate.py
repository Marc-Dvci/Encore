"""Encore against the same model on its own, scored by code against Qloo.

For every resident, the model alone is given the birth year, hometown and family favourites and asked
for ten singers or bands and ten films from the resident's youth. Each answer is looked up in Qloo,
then both lists are scored the same way: found in Qloo, inside the ages 10-30 window, from the home
country, and how much residents' lists overlap. The lounge film is scored four ways on one shared
pool. Writes eval/results.json (aggregates only) for the "How it works" page.

Usage: python scripts/evaluate.py      (needs QLOO_API_KEY and GEMINI_API_KEY in .env)
"""
from __future__ import annotations

import asyncio
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from encore import group, roster, taste  # noqa: E402
from encore.config import ROOT, load_config  # noqa: E402
from encore.qloo import AGE_BUCKET  # noqa: E402
from encore.service import Encore  # noqa: E402

OUT = ROOT / "eval"

ASK = {
    "type": "OBJECT",
    "properties": {
        "singers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"name": {"type": "STRING"}, "active_from": {"type": "INTEGER"}}, "required": ["name", "active_from"]}},
        "films": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "year": {"type": "INTEGER"}}, "required": ["title", "year"]}},
    },
    "required": ["singers", "films"],
}
SYSTEM = "You help care-home activity staff plan reminiscence sessions. Answer with real, well-known names only."


def prompt(p: dict, favs: list[str]) -> str:
    return (f"A care-home resident was born in {p['birth_year']} and grew up in {p['city']}, {p['country']}. "
            f"Their family says they love: {', '.join(favs)}. List 10 singers or bands and 10 films from their youth "
            f"(ages 10 to 30) that they would most likely know and love. Do not repeat the family's favourites.")


async def resolve(enc: Encore, name: str, kind: str, year: int | None) -> str | None:
    enc.qloo.guard.allow([name])
    try:
        res = await enc.qloo.search(name, types=f"urn:entity:{kind}", take=5, purpose="evaluation: look up a model answer")
    except Exception:
        return None
    exact = [r for r in res if roster.norm(r["name"]) == roster.norm(name)]
    if not exact:
        return None
    if year and kind == "movie":
        exact.sort(key=lambda r: abs(((r.get("properties") or {}).get("release_year") or 0) - year))
    return exact[0]["entity_id"]


async def details(enc: Encore, ids: list[str], kind: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for chunk in [ids[i:i + 20] for i in range(0, len(ids), 20)]:
        if not chunk:
            continue
        res = await enc.qloo.insights([("filter.type", f"urn:entity:{kind}"), ("filter.results.entities", chunk),
                                       ("take", len(chunk))], purpose="evaluation: details")
        out.update({e["entity_id"]: e for e in res})
    return out


def in_window(e: dict, kind: str, birth: int) -> bool:
    props = e.get("properties") or {}
    if kind == "artist":
        return taste.artist_era(props, birth)[0] > 0
    y = taste.media_year(e)
    return bool(y) and taste.age_weight(y - birth) > 0


def home(e: dict, country: str) -> bool:
    rc = (e.get("properties") or {}).get("release_country") or []
    rc = rc if isinstance(rc, list) else [rc]
    return country in rc


def jaccard_mean(sets: list[set]) -> float:
    pairs = [(a, b) for a, b in itertools.combinations(sets, 2) if a or b]
    return sum(len(a & b) / len(a | b) for a, b in pairs) / max(1, len(pairs))


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({round(100 * n / d) if d else 0}%)"


async def main() -> None:
    cfg = load_config()
    enc = Encore(cfg)
    await enc.start()
    residents = roster.people(enc.store, "resident")
    tallies = {k: [0, 0] for k in ("enc_art_win", "enc_mov_win", "enc_mov_home", "llm_art_found", "llm_mov_found",
                                   "llm_art_win", "llm_mov_win", "llm_mov_home", "llm_year_off")}
    enc_sets = {"artist": [], "movie": []}
    llm_sets = {"artist": [], "movie": []}
    per_resident = []
    for p in residents:
        favs = [f["entity_name"] or f["label"] for f in p["favourites"] if f["source"] == "family"]
        prof = await taste.era_profile(enc.store, enc.qloo, p, limit=10)
        art = prof["shelves"]["artist"]["items"][:10]
        mov = prof["shelves"]["movie"]["items"][:10]
        # Encore's items carry Qloo's own years; the window holds by construction for films and is checked for artists.
        tallies["enc_art_win"][0] += sum(1 for i in art if i["era_weight"] > 0)
        tallies["enc_art_win"][1] += len(art)
        tallies["enc_mov_win"][0] += sum(1 for i in mov if i["era_weight"] > 0)
        tallies["enc_mov_win"][1] += len(mov)
        mdet = await details(enc, [i["entity_id"] for i in mov], "movie")
        tallies["enc_mov_home"][0] += sum(1 for i in mov if home(mdet.get(i["entity_id"], {}), p["country"]))
        tallies["enc_mov_home"][1] += len(mov)
        enc_sets["artist"].append({i["entity_id"] for i in art})
        enc_sets["movie"].append({i["entity_id"] for i in mov})

        ans = await enc.ai.json("eval_llm_only", SYSTEM, prompt(p, favs), ASK)
        singers = ans.get("singers", [])[:10]
        films = ans.get("films", [])[:10]
        s_ids = [await resolve(enc, s["name"], "artist", None) for s in singers]
        f_ids = [await resolve(enc, f["title"], "movie", f.get("year")) for f in films]
        sdet = await details(enc, [i for i in s_ids if i], "artist")
        fdet = await details(enc, [i for i in f_ids if i], "movie")
        tallies["llm_art_found"][0] += sum(1 for i in s_ids if i)
        tallies["llm_art_found"][1] += len(singers)
        tallies["llm_mov_found"][0] += sum(1 for i in f_ids if i)
        tallies["llm_mov_found"][1] += len(films)
        tallies["llm_art_win"][0] += sum(1 for i in s_ids if i and i in sdet and in_window(sdet[i], "artist", p["birth_year"]))
        tallies["llm_art_win"][1] += len(singers)
        tallies["llm_mov_win"][0] += sum(1 for i in f_ids if i and i in fdet and in_window(fdet[i], "movie", p["birth_year"]))
        tallies["llm_mov_win"][1] += len(films)
        tallies["llm_mov_home"][0] += sum(1 for i in f_ids if i and i in fdet and home(fdet[i], p["country"]))
        tallies["llm_mov_home"][1] += len(films)
        for f, i in zip(films, f_ids):
            if i and i in fdet and taste.media_year(fdet[i]):
                tallies["llm_year_off"][1] += 1
                tallies["llm_year_off"][0] += int(abs(taste.media_year(fdet[i]) - f["year"]) > 1)
        llm_sets["artist"].append({i or roster.norm(s["name"]) for s, i in zip(singers, s_ids)})
        llm_sets["movie"].append({i or roster.norm(f["title"]) for f, i in zip(films, f_ids)})
        per_resident.append({"resident": p["first_name"], "country": p["country"],
                             "encore_home_films": sum(1 for i in mov if home(mdet.get(i["entity_id"], {}), p["country"])),
                             "llm_home_films": sum(1 for i in f_ids if i and i in fdet and home(fdet[i], p["country"]))})
        print(p["first_name"], "done", flush=True)

    t = tallies
    rows = [
        {"metric": "Answers that exist in Qloo's catalogue", "encore": "100% (every item comes from Qloo)",
         "llm_only": f"singers {pct(*t['llm_art_found'])}, films {pct(*t['llm_mov_found'])}",
         "note": "Each model answer searched by exact name and type."},
        {"metric": "Singers active in the resident's ages 10 to 30", "encore": pct(*t["enc_art_win"]),
         "llm_only": pct(*t["llm_art_win"]), "note": "Qloo's start year and end year against the window; unfound answers count as misses."},
        {"metric": "Films released in the resident's ages 10 to 30", "encore": pct(*t["enc_mov_win"]),
         "llm_only": pct(*t["llm_mov_win"]), "note": "Qloo's release year against the window."},
        {"metric": "Films from the resident's home country", "encore": pct(*t["enc_mov_home"]),
         "llm_only": pct(*t["llm_mov_home"]), "note": "Qloo's release country; all 14 residents, including the 6 who grew up in the US."},
        {"metric": "Overlap between residents' film lists", "encore": f"{jaccard_mean(enc_sets['movie']):.3f}",
         "llm_only": f"{jaccard_mean(llm_sets['movie']):.3f}", "note": "Mean pairwise Jaccard over 91 pairs; lower means more personal."},
        {"metric": "Overlap between residents' singer lists", "encore": f"{jaccard_mean(enc_sets['artist']):.3f}",
         "llm_only": f"{jaccard_mean(llm_sets['artist']):.3f}", "note": "Same measure for singers and bands."},
        {"metric": "Model's stated film year off by more than a year", "encore": "n/a (years come from Qloo)",
         "llm_only": pct(*t["llm_year_off"]), "note": "Among model films found in Qloo."},
    ]

    # The lounge film, four ways, on one pool.
    pool, _ = await group.candidate_pool(enc.store, enc.qloo, residents, "movie", per_person=2,
                                         max_minutes=110, cap=20)
    summaries = "\n".join(f"- {r['first_name']}, born {r['birth_year']} in {r['city']}, {r['country']}; loves "
                          + ", ".join(f["entity_name"] or f["label"] for f in r["favourites"] if f["source"] == "family")
                          for r in residents)
    pick = await enc.ai.json("eval_llm_group", SYSTEM,
                             "Choose one film, no longer than 110 minutes, for this care-home lounge this afternoon, "
                             "so that every resident enjoys it:\n" + summaries,
                             {"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "year": {"type": "INTEGER"}},
                              "required": ["title", "year"]})
    llm_id = await resolve(enc, pick["title"], "movie", pick.get("year"))
    if llm_id and llm_id not in {c["entity_id"] for c in pool}:
        d = (await details(enc, [llm_id], "movie")).get(llm_id)
        if d:
            pool.append({"entity_id": llm_id, "name": d["name"], "year": taste.media_year(d), "image": None,
                         "duration": (d.get("properties") or {}).get("duration"), "genres": [],
                         "popularity": d.get("popularity") or 0, "nominated_by": ["model"]})
    aff = await group.affinities(enc.qloo, residents, pool, "movie")
    scored = group.score_candidates(residents, pool, aff, "movie")
    by = {r["entity_id"]: r for r in scored}

    def row(rule, r):
        return {"rule": rule, "film": r["name"], "year": r["year"], "min_fit": r["min_pct"],
                "least_served": r["least_served"], "mean_fit": r["mean_pct"]}

    group_rows = [row("Encore: best for the least-served", scored[0]),
                  row("Highest average affinity", max(scored, key=lambda r: r["mean_affinity"])),
                  row("Most popular on the shortlist", max(scored, key=lambda r: r.get("popularity") or 0))]
    if llm_id and llm_id in by:
        group_rows.append(row("The model alone", by[llm_id]))
    else:
        group_rows.append({"rule": "The model alone", "film": pick["title"] + " (not found in Qloo)", "year": pick.get("year"),
                           "min_fit": 0.0, "least_served": "n/a", "mean_fit": 0.0})

    # Why the music lanes drop the age signal and add the oldies tag.
    abl = {"Favourites + 55-and-older age signal": [0, 0], "Favourites only": [0, 0],
           "Favourites + oldies genre (Encore)": [0, 0]}
    for p in residents:
        seeds = roster.seed_ids(p)
        if not seeds:
            continue
        base = [("filter.type", "urn:entity:artist"), ("signal.interests.entities", seeds), ("take", 50)]
        for lane, extra in (("Favourites + 55-and-older age signal", [("signal.demographics.age", AGE_BUCKET)]),
                            ("Favourites only", []),
                            ("Favourites + oldies genre (Encore)", [("filter.tags", taste.ERA_MUSIC_TAG)])):
            res = await enc.qloo.insights(base + extra, purpose="evaluation: music lane ablation")
            abl[lane][0] += sum(1 for e in res if taste.artist_era(e.get("properties") or {}, p["birth_year"])[0] > 0)
            abl[lane][1] += len(res)

    OUT.mkdir(exist_ok=True)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": enc.ai.model, "residents": len(residents),
              "rows": rows, "group": group_rows, "per_resident": per_resident,
              "music_ablation": [{"lane": k, "in_window": v[0], "total": v[1]} for k, v in abl.items()],
              "llm_group_answer": pick}
    (OUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    await enc.aclose()


if __name__ == "__main__":
    asyncio.run(main())
