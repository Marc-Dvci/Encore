"""The care home's own records: residents, carers, family favourites and avoid lists."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Optional

from .qloo import PrivacyGuard, Qloo
from .store import Store

KINDS = ("artist", "movie", "tv_show", "book")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def load_home(store: Store, path: Path, reset: bool = False) -> dict:
    seed = json.loads(path.read_text(encoding="utf-8"))
    if reset:
        for t in ("people", "favourites", "avoid", "reactions", "sessions"):
            store.x(f"DELETE FROM {t}")
    store.kv_set("home", json.dumps(seed["home"]))
    if store.one("SELECT 1 FROM people LIMIT 1"):
        return seed["home"]
    for kind, rows in (("resident", seed["residents"]), ("carer", seed["carers"])):
        for p in rows:
            store.x("INSERT INTO people(id,kind,first_name,last_initial,birth_year,city,country,demonym,cuisine,music_genre,"
                    "languages,room,present,care_note,family_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (p["id"], kind, p["first_name"], p.get("last_initial"), p["birth_year"], p.get("city"),
                     p.get("country"), p.get("demonym"), p.get("cuisine"), p.get("music_genre"), p.get("languages"),
                     p.get("room"), p.get("care_note"),
                     p.get("family_note")))
            for label, fkind in p.get("favourites", []):
                store.x("INSERT INTO favourites(person_id,label,kind,status,source) VALUES(?,?,?,'pending','family')",
                        (p["id"], label, fkind))
            for tag_id, label in p.get("avoid", []):
                store.x("INSERT INTO avoid(person_id,tag_id,label,source) VALUES(?,?,?,'family')", (p["id"], tag_id, label))
    return seed["home"]


def home(store: Store) -> dict:
    return store.kv_json("home", {})


def register_privacy(store: Store, guard: PrivacyGuard) -> None:
    """Names and notes are protected; favourites, towns and tag terms are the only free text allowed out."""
    people = store.q("SELECT * FROM people")
    guard.protect(f"{p['first_name']} {p['last_initial'] or ''}".strip() for p in people)
    guard.protect(p["first_name"] for p in people)
    guard.protect(p[k] for p in people for k in ("care_note", "family_note"))
    guard.allow(f["label"] for f in store.q("SELECT label FROM favourites"))
    guard.allow(p["city"] for p in people)
    guard.allow(p[k] for p in people for k in ("demonym", "cuisine", "music_genre"))
    guard.allow([home(store).get("town")])


def person(store: Store, pid: str) -> Optional[dict]:
    p = store.one("SELECT * FROM people WHERE id=?", (pid,))
    if not p:
        return None
    p["favourites"] = store.q("SELECT * FROM favourites WHERE person_id=? ORDER BY id", (pid,))
    p["avoid"] = store.q("SELECT * FROM avoid WHERE person_id=? ORDER BY id", (pid,))
    p["age"] = 2026 - p["birth_year"]
    p["house_rules"] = home(store).get("house_rules", [])
    return p


def people(store: Store, kind: str, present_only: bool = False, owner: Optional[str] = None) -> list[dict]:
    """The home's own people. Someone a visitor added is listed only for that visitor."""
    sql = ("SELECT id FROM people WHERE kind=? AND (owner IS NULL OR owner=?)" + (" AND present=1" if present_only else "")
           + " ORDER BY owner IS NOT NULL, first_name")
    return [person(store, r["id"]) for r in store.q(sql, (kind, owner or ""))]


def seed_ids(p: dict, limit: int = 6) -> list[str]:
    """Resolved favourites first (family), then session sparks, most recent first."""
    fam = [f["entity_id"] for f in p["favourites"] if f["status"] == "resolved" and f["source"] == "family"]
    sparks = [f["entity_id"] for f in reversed(p["favourites"]) if f["status"] == "resolved" and f["source"] == "session"]
    out: list[str] = []
    for e in sparks[:3] + fam + sparks[3:]:
        if e and e not in out:
            out.append(e)
    return out[:limit]


def avoid_tags(p: dict) -> list[str]:
    return [a["tag_id"] for a in p["avoid"] if a["tag_id"]]


def avoid_entities(p: dict) -> list[str]:
    return [a["entity_id"] for a in p["avoid"] if a["entity_id"]]


async def resolve_favourite(qloo: Qloo, label: str, kind: str, birth_year: Optional[int] = None) -> dict:
    """Match the family's words to one Qloo entity, or return the candidates for staff to choose from."""
    res = await qloo.search(label, types=f"urn:entity:{kind}", take=6, purpose=f"resolve a family favourite ({kind})")
    cands = [{"entity_id": r["entity_id"], "name": r["name"], "popularity": r.get("popularity", 0),
              "year": (r.get("properties") or {}).get("release_year") or (r.get("properties") or {}).get("start_year"),
              "image": ((r.get("properties") or {}).get("image") or {}).get("url"),
              "description": (r.get("properties") or {}).get("short_description")} for r in res]
    if not cands:
        return {"status": "unresolved", "candidates": []}
    exact = [c for c in cands if norm(c["name"]) == norm(label)]
    if len(exact) > 1 and birth_year and all(c["year"] for c in exact):
        # Same title, several releases: keep the one this person could have known when young.
        era = [c for c in exact if c["year"] <= birth_year + 45]
        if len(era) == 1:
            return {"status": "resolved", "entity_id": era[0]["entity_id"], "entity_name": era[0]["name"],
                    "candidates": cands, "reason": f"the {era[0]['year']} release, closest to their youth"}
    if len(exact) == 1 or (exact and exact[0]["popularity"] - (exact[1]["popularity"] if len(exact) > 1 else 0) > 0.05):
        return {"status": "resolved", "entity_id": exact[0]["entity_id"], "entity_name": exact[0]["name"], "candidates": cands}
    if not exact and cands[0]["popularity"] > 0.9 and (len(cands) == 1 or cands[0]["popularity"] - cands[1]["popularity"] > 0.15):
        return {"status": "resolved", "entity_id": cands[0]["entity_id"], "entity_name": cands[0]["name"], "candidates": cands}
    return {"status": "needs_input", "candidates": cands}


async def resolve_pending(store: Store, qloo: Qloo) -> dict:
    counts = {"resolved": 0, "needs_input": 0, "unresolved": 0}
    for f in store.q("SELECT f.*, p.birth_year FROM favourites f JOIN people p ON p.id=f.person_id "
                     "WHERE f.status='pending'"):
        r = await resolve_favourite(qloo, f["label"], f["kind"], f["birth_year"])
        counts[r["status"]] += 1
        store.x("UPDATE favourites SET status=?, entity_id=?, entity_name=? WHERE id=?",
                (r["status"], r.get("entity_id"), r.get("entity_name"), f["id"]))
    return counts
