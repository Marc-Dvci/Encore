"""Encore's operations, shared by the web API, the agent and the MCP server."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from . import common, family, group, learning, roster, session, taste, week
from .ai import AI
from .config import Config
from .qloo import Qloo, QlooUnavailable
from .store import Store

log = logging.getLogger("encore")


class NotFound(KeyError):
    pass


class Encore:
    def __init__(self, cfg: Config, store: Optional[Store] = None, qloo: Optional[Qloo] = None,
                 ai: Optional[AI] = None):
        self.cfg = cfg
        self.store = store or Store(cfg.db_path)
        self.qloo = qloo or Qloo(cfg, self.store)
        self.ai = ai or AI(cfg, self.store.kv_get, self.store.kv_set)
        self.warm_state = {"done": 0, "total": 0, "running": False}

    async def start(self, reset: bool = False) -> None:
        roster.load_home(self.store, self.cfg.home_file, reset=reset)
        roster.register_privacy(self.store, self.qloo.guard)
        try:
            await roster.resolve_pending(self.store, self.qloo)
        except QlooUnavailable as e:
            log.warning("favourites not resolved yet: %s", e)

    async def warm(self) -> None:
        """Fill the private cache for every resident so the first visitor waits for nothing."""
        residents = roster.people(self.store, "resident")
        self.warm_state = {"done": 0, "total": len(residents) + 3, "running": True}
        try:
            for r in residents:
                await taste.era_profile(self.store, self.qloo, r)
                self.warm_state["done"] += 1
            await self.lounge("movie")
            self.warm_state["done"] += 1
            await self.lounge("artist")
            self.warm_state["done"] += 1
            await self.week()
            self.warm_state["done"] += 1
        except QlooUnavailable as e:
            log.warning("warm-up stopped: %s", e)
        finally:
            self.warm_state["running"] = False

    # ---- reads ------------------------------------------------------------------------------

    def person(self, pid: str) -> dict:
        p = roster.person(self.store, pid)
        if not p:
            raise NotFound(pid)
        return p

    def home(self, owner: Optional[str] = None) -> dict:
        h = roster.home(self.store)
        residents = roster.people(self.store, "resident", owner=owner)
        return {**h, "residents": [self._card(r) for r in residents],
                "carers": [self._card(c) for c in roster.people(self.store, "carer")],
                "present": sum(1 for r in residents if r["present"]),
                "relations": list(family.RELATIONS), "countries": sorted(family.COUNTRIES)}

    def _card(self, p: dict) -> dict:
        pending = [f for f in p["favourites"] if f["status"] == "needs_input"]
        last = self.store.one("SELECT at, reaction, entity_name FROM reactions WHERE person_id=? ORDER BY id DESC LIMIT 1",
                              (p["id"],))
        return {"id": p["id"], "kind": p["kind"], "first_name": p["first_name"], "last_initial": p["last_initial"],
                "birth_year": p["birth_year"], "age": p["age"], "city": p["city"], "country": p["country"],
                "room": p["room"], "present": bool(p["present"]), "languages": p["languages"],
                "favourites": [f["entity_name"] or f["label"] for f in p["favourites"] if f["source"] == "family"],
                "needs_input": len(pending), "last_reaction": last, "staff_note": p.get("care_note") or None,
                "guest": bool(p.get("owner"))}

    async def profile(self, pid: str) -> dict:
        p = self.person(pid)
        h = roster.home(self.store)
        prof, seeds, food = await asyncio.gather(
            taste.era_profile(self.store, self.qloo, p),
            taste.seed_details(self.qloo, p),
            taste.taste_of_home(self.qloo, p, h.get("town", ""), int(h.get("radius_m") or 15000)),
            return_exceptions=True)
        pending = []
        for f in p["favourites"]:
            if f["status"] == "needs_input":
                r = await roster.resolve_favourite(self.qloo, f["label"], f["kind"], p["birth_year"])
                pending.append({**f, "candidates": r["candidates"]})
        return {"person": self._public(p), "favourites": p["favourites"], "avoid": p["avoid"],
                "house_rules": p["house_rules"],
                "family": [] if isinstance(seeds, Exception) else seeds,
                "era": None if isinstance(prof, Exception) else prof,
                "food": None if isinstance(food, Exception) else food,
                "pending": pending, "history": learning.history(self.store, pid),
                "errors": [str(x) for x in (prof, seeds, food) if isinstance(x, Exception)]}

    def _public(self, p: dict) -> dict:
        keep = ("id", "kind", "first_name", "last_initial", "birth_year", "age", "city", "country", "demonym",
                "languages", "room", "present", "family_note", "care_note")
        return {**{k: p.get(k) for k in keep}, "guest": bool(p.get("owner"))}

    async def lounge(self, domain: str = "movie", ids: Optional[list[str]] = None,
                     max_minutes: Optional[int] = None, extra: Optional[list[str]] = None) -> dict:
        residents = [self.person(i) for i in ids] if ids else roster.people(self.store, "resident", present_only=True)
        for i in extra or []:
            if i not in {r["id"] for r in residents}:
                residents.append(self.person(i))
        if not residents:
            return {"domain": domain, "pick": None, "candidates": [], "playlist": []}
        if domain == "artist":
            return await group.music_hour(self.store, self.qloo, residents)
        return await group.film_pick(self.store, self.qloo, residents, max_minutes)

    async def week(self) -> dict:
        return await week.plan_week(self.store, self.qloo, roster.people(self.store, "resident", present_only=True),
                                    roster.people(self.store, "carer"))

    async def common(self, rid: str, cid: str) -> dict:
        return await common.common_ground(self.qloo, self.person(rid), self.person(cid))

    async def plan(self, rid: str, cid: str, visitor: Optional[str] = None) -> dict:
        return await session.plan_session(self.store, self.qloo, self.ai, self.person(rid), self.person(cid), visitor)

    def session(self, sid: str) -> dict:
        p = session.load_plan(self.store, sid)
        if not p:
            raise NotFound(sid)
        p["reactions"] = self.store.q("SELECT * FROM reactions WHERE session_id=? ORDER BY id", (sid,))
        return p

    def record(self, pid: str) -> dict:
        """The activity record a surveyor asks for: interests, where they came from, and participation."""
        p = self.person(pid)
        sessions = [json.loads(r["plan"]) | {"at": r["at"]} for r in
                    self.store.q("SELECT plan, at FROM sessions WHERE person_ids LIKE ? ORDER BY at DESC", (f'%"{pid}"%',))]
        return {"person": self._public(p), "home": roster.home(self.store), "favourites": p["favourites"],
                "avoid": p["avoid"], "house_rules": p["house_rules"], "reactions": learning.history(self.store, pid, 200),
                "sessions": [{"id": s["id"], "at": s["at"], "carer": s["carer"]["first_name"],
                              "items": [st.get("item", {}).get("name") or st.get("place", {}).get("name")
                                        for st in s["steps"] if st.get("item") or st.get("place")]} for s in sessions]}

    def qloo_log(self, limit: int = 150) -> dict:
        rows = self.qloo.recent_log(limit)
        totals = self.store.one("SELECT COUNT(*) n, SUM(cached) c FROM qloo_log")
        paths = self.store.q("SELECT path, COUNT(*) n FROM qloo_log GROUP BY path ORDER BY n DESC")
        return {"rows": rows, "total": totals["n"], "cached": totals["c"] or 0, "paths": paths}

    # ---- writes (staff only) ----------------------------------------------------------------

    async def react(self, pid: str, item: dict, reaction: str, carer_id: Optional[str], session_id: Optional[str],
                    note: Optional[str] = None) -> dict:
        p = self.person(pid)
        before = (await taste.shelf(self.store, self.qloo, p, item.get("type", "artist"), limit=8))["items"]
        effect = learning.log_reaction(self.store, pid, item, reaction, carer_id, session_id, note)
        after = (await taste.shelf(self.store, self.qloo, self.person(pid), item.get("type", "artist"), limit=8))["items"]
        d = learning.diff(before, after)
        effect["shelf_in"] = [{"name": x["name"], "year": x["year"], "because": x["because"]} for x in d["in"]]
        effect["shelf_out"] = [{"name": x["name"], "year": x["year"]} for x in d["out"]]
        return effect

    def add_avoid_tag(self, pid: str, tag_id: str, label: str) -> None:
        self.person(pid)
        learning.add_avoid_tag(self.store, pid, tag_id, label)

    def remove_avoid(self, pid: str, avoid_id: int) -> None:
        self.store.x("DELETE FROM avoid WHERE id=? AND person_id=?", (avoid_id, pid))

    def set_present(self, pid: str, present: bool) -> None:
        if self.person(pid).get("owner"):
            raise ValueError("someone a visitor added joins the lounge from their own page, not for everyone")
        self.store.x("UPDATE people SET present=? WHERE id=?", (int(present), pid))

    def confirm_favourite(self, fav_id: int, entity_id: str, entity_name: str) -> None:
        self.store.x("UPDATE favourites SET status='resolved', entity_id=?, entity_name=? WHERE id=?",
                     (entity_id, entity_name, fav_id))

    async def add_favourite(self, pid: str, label: str, kind: str) -> dict:
        p = self.person(pid)
        if kind not in roster.KINDS:
            raise ValueError("kind must be one of " + ", ".join(roster.KINDS))
        label = label.strip()[:80]
        self.qloo.guard.allow([label])  # the family's own words are the one free text Qloo may receive
        r = await roster.resolve_favourite(self.qloo, label, kind, p["birth_year"])
        fid = self.store.x("INSERT INTO favourites(person_id,label,kind,entity_id,entity_name,status,source) "
                           "VALUES(?,?,?,?,?,?,'family')", (pid, label, kind, r.get("entity_id"), r.get("entity_name"),
                                                             r["status"]))
        return {"id": fid, **r}

    async def add_person(self, owner: str, relation: str, birth_year: int, city: str, country: str,
                         favourites: list[tuple[str, str]]) -> dict:
        return await family.add_person(self.store, self.qloo, owner, relation, birth_year, city, country, favourites)

    def remove_person(self, owner: str, pid: str) -> None:
        if not family.remove_person(self.store, owner, pid):
            raise NotFound(pid)

    def remove_favourite(self, pid: str, fav_id: int) -> None:
        self.store.x("DELETE FROM favourites WHERE id=? AND person_id=?", (fav_id, pid))

    async def reset(self) -> None:
        await self.start(reset=True)

    async def aclose(self) -> None:
        await self.qloo.aclose()
        await self.ai.aclose()
