"""A one-to-one reminiscence session, planned for one resident and the carer sitting with them.

Code chooses every item: a song the family named, a song from the resident's youth the care team has
not tried yet, a film, something the two people share and a taste of home. The model only writes
the words the carer will say, and a template writes them when the model is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from . import common, roster, taste
from .ai import AI, AIUnavailable
from .qloo import Qloo
from .store import Store

PROMPT_SYSTEM = """You help a care worker run a ten-minute one-to-one reminiscence session in a care home.
Write in plain, warm English that a 25-year-old carer can say out loud.
Rules:
- Use only the songs, films, places and shared tastes given. Never add facts about the resident, and never
  say where, when or with whom they did something; ask instead.
- Invite, never test: start prompts with "Tell me about", "What was it like", "Who did you" or similar.
  Never ask "Do you remember".
- One idea per prompt, at most 18 words.
- No health, medication or memory talk.
- If a greeting in the resident's first language is natural, give it with its meaning in brackets."""

PROMPT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "opener": {"type": "STRING", "description": "First sentence the carer says, introducing the first song."},
        "prompts": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Three conversation prompts."},
        "if_quiet": {"type": "STRING", "description": "What to do if the resident does not respond, in one sentence."},
        "greeting": {"type": "STRING", "description": "Optional greeting in the resident's first language, or empty."},
    },
    "required": ["opener", "prompts", "if_quiet", "greeting"],
}


def _song_line(item: Optional[dict]) -> Optional[str]:
    if not item:
        return None
    song = (item.get("songs") or [None])[0]
    return f"{song} by {item['name']}" if song else item["name"]


async def plan_session(store: Store, qloo: Qloo, ai: AI, resident: dict, carer: dict,
                       visitor: Optional[str] = None) -> dict:
    seeds_task = taste.seed_details(qloo, resident)
    art_task = taste.shelf(store, qloo, resident, "artist", limit=8)
    mov_task = taste.shelf(store, qloo, resident, "movie", limit=6)
    cg_task = common.common_ground(qloo, resident, carer)
    home = roster.home(store)
    food_task = taste.taste_of_home(qloo, resident, home.get("town", ""), int(home.get("radius_m") or 15000))
    seeds, arts, movs, cg, food = await asyncio.gather(seeds_task, art_task, mov_task, cg_task, food_task,
                                                       return_exceptions=True)
    warnings = [str(x) for x in (seeds, arts, movs, cg, food) if isinstance(x, Exception)]
    seeds = [] if isinstance(seeds, Exception) else seeds
    arts = {"items": []} if isinstance(arts, Exception) else arts
    movs = {"items": []} if isinstance(movs, Exception) else movs
    cg = {"shared": [], "bridges": []} if isinstance(cg, Exception) else cg
    food = {"places": []} if isinstance(food, Exception) else food

    tried = {r["entity_id"] for r in store.q("SELECT entity_id FROM reactions WHERE person_id=?", (resident["id"],))}
    family_song = next((s for s in seeds if s["kind"] == "artist" and s["songs"] and s["entity_id"]), None)
    discovery = next((i for i in arts["items"] if i.get("songs") and i["entity_id"] not in tried), None)
    films = [i for i in movs["items"] if i["entity_id"] not in tried][:4]
    film = max(films, key=lambda i: i.get("popularity") or 0) if films else None
    bridge = next((b for b in cg.get("bridges", []) if b["type"] == "artist"), None)
    place = next((p for p in food.get("places", []) if p.get("dishes")), None) or \
        next(iter(food.get("places", [])), None)

    steps = []
    if family_song:
        steps.append({"kind": "open", "title": "Open with a song the family named",
                      "item": {**family_song, "type": "artist", "name": family_song["name"]},
                      "song": family_song["songs"][0],
                      "why": f"{resident['first_name']}'s family listed {family_song['name']}."})
    if discovery:
        steps.append({"kind": "discover", "title": "Then a song from their youth nobody here has tried",
                      "item": discovery, "song": discovery["songs"][0],
                      "why": _why(discovery, resident)})
    if film:
        steps.append({"kind": "film", "title": "A film to talk about", "item": film, "why": _why(film, resident)})
    if bridge or cg.get("shared"):
        steps.append({"kind": "common", "title": f"Something {carer['first_name']} and {resident['first_name']} share",
                      "item": bridge and {**bridge, "type": "artist"}, "shared": cg.get("shared", [])[:4],
                      "song": (bridge or {}).get("songs", [None])[0] if bridge and bridge.get("songs") else None,
                      "why": "Qloo's explainability shows both people's favourites pulling toward this artist."
                      if bridge else "Tastes Qloo finds in both people's favourites."})
    if place:
        steps.append({"kind": "food", "title": "A taste of home", "place": place,
                      "why": f"{resident['demonym'] or ''} food within {place['distance_km']} km of {home.get('name')}."})

    words, source = await _words(ai, resident, carer, steps, visitor)
    plan = {"id": "s-" + uuid.uuid4().hex[:8], "resident": _who(resident), "carer": _who(carer), "steps": steps,
            "words": words, "words_source": source, "window": taste.window(resident["birth_year"]),
            "warnings": warnings}
    store.x("INSERT INTO sessions(id,kind,carer_id,person_ids,plan) VALUES(?,?,?,?,?)",
            (plan["id"], "one_to_one", carer["id"], f'["{resident["id"]}"]', json.dumps(plan)))
    return plan


def _who(p: dict) -> dict:
    return {"id": p["id"], "first_name": p["first_name"], "birth_year": p["birth_year"], "city": p["city"],
            "country": p["country"], "languages": p["languages"], "age": 2026 - p["birth_year"]}


def _why(item: dict, resident: dict) -> str:
    parts = []
    if item.get("age_then") is not None:
        parts.append(f"{resident['first_name']} was {item['age_then']} in {item['year'] if item['type'] != 'artist' else resident['birth_year'] + item['age_then']}")
    if "home" in item.get("lanes", []):
        parts.append(f"from {resident['country']}")
    if item.get("because"):
        parts.append("Qloo links it to " + " and ".join(item["because"]))
    return "; ".join(parts) + "." if parts else ""


async def _words(ai: AI, resident: dict, carer: dict, steps: list[dict], visitor: Optional[str]) -> tuple[dict, str]:
    facts = [f"Resident: {resident['first_name']}, born {resident['birth_year']} in {resident['city']}, "
             f"{resident['country']}. Languages: {resident['languages']}.",
             f"Carer: {carer['first_name']}, born {carer['birth_year']} in {carer['city']}, {carer['country']}."]
    for s in steps:
        if s["kind"] in ("open", "discover"):
            facts.append(f"{s['title']}: '{s['song']}' by {s['item']['name']}.")
        elif s["kind"] == "film":
            facts.append(f"Film: {s['item']['name']} ({s['item']['year']}).")
        elif s["kind"] == "common":
            shared = ", ".join(x["name"] for x in s.get("shared", []))
            facts.append(f"Shared tastes: {shared}." + (f" Shared artist: {s['item']['name']}." if s.get("item") else ""))
        elif s["kind"] == "food":
            dish = ", ".join(s["place"].get("dishes") or [])
            facts.append(f"Food from home: {s['place']['name']}" + (f", known for {dish}." if dish else "."))
    try:
        out = await ai.json("session_words", PROMPT_SYSTEM, "\n".join(facts), PROMPT_SCHEMA, visitor)
        out["prompts"] = [p for p in out.get("prompts", []) if p][:3]
        return out, "model"
    except AIUnavailable:
        return _template(resident, carer, steps), "template"


def _template(resident: dict, carer: dict, steps: list[dict]) -> dict:
    first = next((s for s in steps if s["kind"] in ("open", "discover")), None)
    film = next((s for s in steps if s["kind"] == "film"), None)
    food = next((s for s in steps if s["kind"] == "food"), None)
    prompts = []
    if first:
        prompts.append(f"Tell me about where you would hear {first['item']['name']}.")
    if film:
        prompts.append(f"What was it like going to the pictures in {resident['city']}?")
    if food and food["place"].get("dishes"):
        prompts.append(f"Who made the best {food['place']['dishes'][0].lower()} when you were young?")
    else:
        prompts.append(f"Tell me about Sunday dinner in {resident['city']}.")
    return {"opener": f"I found a song I think you might know, {resident['first_name']}." if first else
            f"I'd love to hear about {resident['city']}, {resident['first_name']}.",
            "prompts": prompts[:3],
            "if_quiet": "Let the song play, hum along, and sit with them; silence is fine.", "greeting": ""}


def load_plan(store: Store, sid: str) -> Optional[dict]:
    r = store.one("SELECT plan FROM sessions WHERE id=?", (sid,))
    return json.loads(r["plan"]) if r else None
