"""What a session teaches Encore.

A carer records one reaction per item. A song that lit someone up becomes a new signal for their
next Qloo query; a song that got no response rests for two weeks; anything that upset them goes on
their avoid list at once, and its genres are offered to staff as avoid tags to confirm.
"""
from __future__ import annotations

from typing import Optional

from . import roster
from .store import Store

REACTIONS = {
    "lit_up": "Lit up",
    "sang_along": "Sang or moved along",
    "no_response": "No response",
    "upset": "Seemed upset",
}
POSITIVE = {"lit_up", "sang_along"}


def log_reaction(store: Store, person_id: str, item: dict, reaction: str, carer_id: Optional[str] = None,
                 session_id: Optional[str] = None, note: Optional[str] = None) -> dict:
    if reaction not in REACTIONS:
        raise ValueError(f"unknown reaction {reaction}")
    p = roster.person(store, person_id)
    if not p:
        raise KeyError(person_id)
    store.x("INSERT INTO reactions(person_id,carer_id,session_id,entity_id,entity_name,entity_type,reaction,note) "
            "VALUES(?,?,?,?,?,?,?,?)", (person_id, carer_id, session_id, item["entity_id"], item["name"],
                                        item.get("type", "artist"), reaction, note))
    effect: dict = {"reaction": reaction, "label": REACTIONS[reaction], "item": item["name"]}
    if reaction in POSITIVE:
        known = {f["entity_id"] for f in p["favourites"]}
        if item["entity_id"] not in known:
            store.x("INSERT INTO favourites(person_id,label,kind,entity_id,entity_name,status,source) "
                    "VALUES(?,?,?,?,?,'resolved','session')",
                    (person_id, item["name"], item.get("type", "artist"), item["entity_id"], item["name"]))
            effect["change"] = f"{item['name']} is now a signal in {p['first_name']}'s Qloo queries"
        else:
            effect["change"] = f"{item['name']} was already a signal for {p['first_name']}"
    elif reaction == "no_response":
        effect["change"] = f"{item['name']} rests for 14 days"
    else:
        store.x("INSERT INTO avoid(person_id,entity_id,label,source) VALUES(?,?,?,'session')",
                (person_id, item["entity_id"], item["name"]))
        effect["change"] = f"{item['name']} is on {p['first_name']}'s avoid list"
        effect["suggest_tags"] = [g for g in (item.get("genre_tags") or [])][:3]
    return effect


def add_avoid_tag(store: Store, person_id: str, tag_id: str, label: str) -> None:
    store.x("INSERT INTO avoid(person_id,tag_id,label,source) VALUES(?,?,?,'staff')", (person_id, tag_id, label))


def history(store: Store, person_id: str, limit: int = 50) -> list[dict]:
    return store.q("SELECT r.*, c.first_name AS carer FROM reactions r LEFT JOIN people c ON c.id=r.carer_id "
                   "WHERE r.person_id=? ORDER BY r.id DESC LIMIT ?", (person_id, limit))


def diff(before: list[dict], after: list[dict]) -> dict:
    b = {x["entity_id"]: x for x in before}
    a = {x["entity_id"]: x for x in after}
    return {"in": [a[i] for i in a if i not in b], "out": [b[i] for i in b if i not in a]}
