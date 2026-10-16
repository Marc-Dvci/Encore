"""Ask Encore: the activities coordinator's agent.

Gemini plans with Encore's tools and writes the reply. Every tool is read-only: the agent can look,
rank and plan, and only staff can record a reaction or change an avoid list. Each tool call is kept
in a trace with the Qloo requests it made, so the coordinator sees where every answer came from.
When the model is unavailable, a keyword router runs the matching tool and a template replies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import roster
from .ai import AIUnavailable
from .qloo import QlooUnavailable, start_trace
from .service import Encore, NotFound

SYSTEM = """You are Encore, the assistant to {coordinator}, activities coordinator at {home} in {town}.
Today is {today}. You plan reminiscence activities for residents using the tools.
Rules:
- Every pick, rank and number must come from a tool result. Never invent songs, films or facts about residents.
- Refer to residents by first name. Never mention care notes or health.
- Qloo affinity describes audiences; never present it as a probability about one person.
- You cannot record reactions or change avoid lists; tell staff where to do it (the session screen).
- Answer in at most 120 words, plain sentences, then a short list if useful."""

TOOLS: list[dict] = [
    {"name": "list_people", "description": "Residents and carers at the home, with birth year, hometown and whether each resident is in the lounge today.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "resident_profile", "description": "The culture of one resident's youth (ages 10 to 30) from Qloo: top songs, films and TV, family favourites and avoid list.",
     "parameters": {"type": "OBJECT", "properties": {"resident": {"type": "STRING", "description": "First name or id"}}, "required": ["resident"]}},
    {"name": "lounge_film", "description": "Pick the lounge film for the residents present (or the named ones): best fit for the least-served resident, with alternatives scored the same way.",
     "parameters": {"type": "OBJECT", "properties": {"max_minutes": {"type": "INTEGER"},
                                                     "residents": {"type": "ARRAY", "items": {"type": "STRING"}}}}},
    {"name": "music_hour", "description": "Build a music-hour playlist where every resident present hears an artist from their youth that fits them.",
     "parameters": {"type": "OBJECT", "properties": {"residents": {"type": "ARRAY", "items": {"type": "STRING"}}}}},
    {"name": "plan_one_to_one", "description": "Plan a ten-minute one-to-one session for a resident and a carer: songs, a film, common ground, a taste of home, and words to say.",
     "parameters": {"type": "OBJECT", "properties": {"resident": {"type": "STRING"}, "carer": {"type": "STRING"}}, "required": ["resident", "carer"]}},
    {"name": "common_ground", "description": "Tastes a resident and a carer share according to Qloo, and an artist and film from the resident's youth both point to.",
     "parameters": {"type": "OBJECT", "properties": {"resident": {"type": "STRING"}, "carer": {"type": "STRING"}}, "required": ["resident", "carer"]}},
    {"name": "week_plan", "description": "The week's programme for the residents present: two lounge films chosen together so every resident gets one that fits, a music hour, and who sits with whom for each one-to-one (carers matched by shared tastes from Qloo Compare).",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "recent_reactions", "description": "What staff recorded in recent sessions for one resident.",
     "parameters": {"type": "OBJECT", "properties": {"resident": {"type": "STRING"}}, "required": ["resident"]}},
]


class Agent:
    def __init__(self, enc: Encore):
        self.enc = enc

    def _find(self, name: Optional[str], kind: Optional[str] = None) -> dict:
        if not name:
            raise NotFound("nobody named")
        n = roster.norm(name)
        for p in self.enc.store.q("SELECT id, first_name, kind FROM people WHERE owner IS NULL"):
            if (n in (roster.norm(p["id"]), roster.norm(p["first_name"]))) and (not kind or p["kind"] == kind):
                return self.enc.person(p["id"])
        raise NotFound(f"no {kind or 'person'} called {name}")

    async def call(self, name: str, args: dict, visitor: Optional[str]) -> tuple[dict, dict]:
        """Returns (compact result for the model, full result for the screen)."""
        e = self.enc
        if name == "list_people":
            h = e.home()
            out = {"residents": [{"name": r["first_name"], "born": r["birth_year"], "from": f"{r['city']}, {r['country']}",
                                  "in_lounge": r["present"]} for r in h["residents"]],
                   "carers": [{"name": c["first_name"], "born": c["birth_year"], "from": f"{c['city']}, {c['country']}"}
                              for c in h["carers"]]}
            return out, {"kind": "people", **out}
        if name == "resident_profile":
            p = self._find(args.get("resident"), "resident")
            prof = await e.profile(p["id"])
            era = prof["era"] or {"shelves": {}}
            out = {"name": p["first_name"], "youth": era.get("window"),
                   "family_favourites": [f["name"] for f in prof["family"]],
                   "avoid": [a["label"] for a in prof["avoid"]],
                   **{d: [f"{i['name']} ({i['year']})" for i in s["items"][:5]] for d, s in era["shelves"].items()}}
            return out, {"kind": "profile", "id": p["id"], **out}
        if name in ("lounge_film", "music_hour"):
            ids = [self._find(r, "resident")["id"] for r in args.get("residents") or []] or None
            res = await e.lounge("movie" if name == "lounge_film" else "artist", ids, args.get("max_minutes"))
            if name == "lounge_film":
                pk = res.get("pick") or {}
                out = {"pick": pk.get("name"), "year": pk.get("year"), "minutes": pk.get("duration"),
                       "least_served": pk.get("least_served"), "least_served_fit": pk.get("min_pct"),
                       "average_fit": pk.get("mean_pct"), "alternatives": res.get("alternatives"),
                       "rule": res.get("rule"), "residents": res.get("residents")}
            else:
                out = {"playlist": [f"{x['song']} by {x['name']}" if x.get("song") else x["name"] for x in res["playlist"]],
                       "coverage": res["coverage"], "rule": res.get("rule")}
            return out, {"kind": name, **res}
        if name == "plan_one_to_one":
            r = self._find(args.get("resident"), "resident")
            c = self._find(args.get("carer"), "carer")
            plan = await e.plan(r["id"], c["id"], visitor)
            out = {"session_id": plan["id"], "steps": [{"step": s["title"], "item": (s.get("item") or s.get("place") or {}).get("name"),
                                                        "song": s.get("song"), "why": s["why"]} for s in plan["steps"]],
                   "words": plan["words"]}
            return out, {"kind": "plan", **plan}
        if name == "common_ground":
            r = self._find(args.get("resident"), "resident")
            c = self._find(args.get("carer"), "carer")
            cg = await e.common(r["id"], c["id"])
            out = {"shared": [s["name"] for s in cg["shared"]], "bridges": [f"{b['name']} ({b['type']}, {b['year']})" for b in cg["bridges"]]}
            return out, {"kind": "common", **cg}
        if name == "week_plan":
            w = await e.week()
            pr = w["films"].get("pair") or {}
            out = {"films": [f"{f['name']} ({f['year']})" for f in pr.get("films", [])],
                   "least_served_with_two_films": pr.get("floor"),
                   "least_served_with_one_film": (w["films"].get("single") or {}).get("floor"),
                   "one_to_ones": [f"{o['day']}: {o['resident']['first_name']} with {o['carer']['first_name']}"
                                   + (f" (share {', '.join(o['shared'][:2])})" if o["shared"] else "") for o in w["one_to_ones"]],
                   "shared_taste_total": w["pairing"]["chosen_total"], "alphabetical_rota_total": w["pairing"]["rota_total"]}
            return out, {"kind": "week", **w}
        if name == "recent_reactions":
            r = self._find(args.get("resident"), "resident")
            rows = e.store.q("SELECT at, entity_name, reaction FROM reactions WHERE person_id=? ORDER BY id DESC LIMIT 12", (r["id"],))
            return {"reactions": rows}, {"kind": "reactions", "rows": rows}
        raise NotFound(f"unknown tool {name}")

    async def ask(self, message: str, history: Optional[list[dict]] = None, visitor: Optional[str] = None) -> dict:
        h = roster.home(self.enc.store)
        system = SYSTEM.format(coordinator=h.get("coordinator"), home=h.get("name"), town=h.get("town"),
                               today=h.get("lounge_time", "today"))
        contents: list[dict] = [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in (history or [])[-6:]]
        contents.append({"role": "user", "parts": [{"text": message[:800]}]})
        trace: list[dict] = []
        cards: list[dict] = []
        try:
            for _ in range(6):
                turn = await self.enc.ai.turn(system, contents, TOOLS, visitor)
                parts = turn.get("parts") or []
                calls = [p["functionCall"] for p in parts if "functionCall" in p]
                if not calls:
                    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                    return {"answer": text, "trace": trace, "cards": cards, "source": "model"}
                contents.append({"role": "model", "parts": parts})
                responses = []
                for c in calls:
                    result, card = await self._run(c["name"], c.get("args") or {}, visitor, trace)
                    if card:
                        cards.append(card)
                    responses.append({"functionResponse": {"name": c["name"], "response": {"result": result}}})
                contents.append({"role": "user", "parts": responses})
            return {"answer": "I ran out of steps; the results so far are below.", "trace": trace, "cards": cards,
                    "source": "model"}
        except AIUnavailable as why:
            return await self._fallback(message, visitor, trace, cards, str(why))

    async def _run(self, name: str, args: dict, visitor: Optional[str], trace: list[dict]) -> tuple[Any, Optional[dict]]:
        qtrace = start_trace()
        try:
            result, card = await self.call(name, args, visitor)
            trace.append({"tool": name, "args": args, "ok": True, "qloo": qtrace})
            return result, card
        except (NotFound, QlooUnavailable, ValueError) as e:
            trace.append({"tool": name, "args": args, "ok": False, "error": str(e), "qloo": qtrace})
            return {"error": str(e)}, None

    async def _fallback(self, message: str, visitor: Optional[str], trace: list[dict], cards: list[dict],
                        why: str) -> dict:
        m = message.lower()
        names = [p["first_name"] for p in self.enc.store.q("SELECT first_name FROM people WHERE owner IS NULL")]
        mentioned = [n for n in names if re.search(r"\b" + re.escape(n.lower()) + r"\b", m)]
        carers = {p["first_name"] for p in self.enc.store.q("SELECT first_name FROM people WHERE kind='carer'")}
        res_names = [n for n in mentioned if n not in carers]
        car_names = [n for n in mentioned if n in carers]
        if res_names and car_names and re.search(r"plan|session|one.to.one|sit with", m):
            name, args = "plan_one_to_one", {"resident": res_names[0], "carer": car_names[0]}
        elif res_names and car_names:
            name, args = "common_ground", {"resident": res_names[0], "carer": car_names[0]}
        elif re.search(r"week|rota|monday|schedule", m):
            name, args = "week_plan", {}
        elif re.search(r"music|song|playlist|sing", m):
            name, args = "music_hour", {}
        elif re.search(r"film|movie|lounge|watch", m):
            name, args = "lounge_film", {}
        elif res_names:
            name, args = "resident_profile", {"resident": res_names[0]}
        else:
            name, args = "list_people", {}
        result, card = await self._run(name, args, visitor, trace)
        if card:
            cards.append(card)
        return {"answer": _template_answer(name, result), "trace": trace, "cards": cards, "source": "template",
                "note": f"Model unavailable ({why}); Encore ran the matching tool directly."}


def _template_answer(name: str, r: dict) -> str:
    if "error" in r:
        return f"I couldn't do that: {r['error']}."
    if name == "lounge_film" and r.get("pick"):
        return (f"{r['pick']} ({r['year']}, {r['minutes']} min). Its least-served resident is {r['least_served']} "
                f"with a fit of {r['least_served_fit']:.2f}, against an average of {r['average_fit']:.2f}.")
    if name == "week_plan":
        return (f"This week: {' and '.join(r['films'])}. With both, the least-served resident's better film fits at "
                f"{r['least_served_with_two_films']}, against {r['least_served_with_one_film']} with one film. "
                + "; ".join(r["one_to_ones"][:5]) + ".")
    if name == "music_hour":
        return "Music hour: " + "; ".join(r["playlist"][:8]) + "."
    if name == "plan_one_to_one":
        return "Session plan: " + "; ".join(f"{s['step']}: {s['item']}" for s in r["steps"]) + "."
    if name == "common_ground":
        return "They share " + ", ".join(r["shared"][:4]) + ". Try " + ", ".join(r["bridges"]) + "."
    if name == "resident_profile":
        return f"{r['name']}'s youth ran {r['youth'][0]} to {r['youth'][1]}. Songs: " + ", ".join(r.get("artist", [])[:4]) + "."
    return json.dumps(r, ensure_ascii=False)[:600]
