"""Someone a visitor adds: the family form.

A family member gives what they can say in a minute: who the person is to them, the year they were
born, where they grew up and up to three favourites. Encore asks for no name. The person is visible
only to the visitor who added them (a random token kept in their browser) and is removed at the
nightly reset.
"""
from __future__ import annotations

import re
import secrets
from typing import Optional

from . import roster
from .qloo import Qloo
from .store import Store

RELATIONS = ("Mum", "Dad", "Grandma", "Grandpa", "Aunt", "Uncle", "A friend", "Me")

# Country -> (demonym, cuisine term, music genre term, first language). The terms are looked up with
# Qloo's /v2/tags at query time; every one below returned a music or restaurant genre tag on 16 Oct 2026.
COUNTRIES: dict[str, tuple[str, Optional[str], Optional[str], Optional[str]]] = {
    "United States": ("American", "american", None, None),
    "Canada": ("Canadian", "canadian", "canadian", None),
    "Mexico": ("Mexican", "mexican", "mexican", "Spanish"),
    "Cuba": ("Cuban", "cuban", "cuban", "Spanish"),
    "Puerto Rico": ("Puerto Rican", "puerto rican", "puerto rican", "Spanish"),
    "Dominican Republic": ("Dominican", "dominican", "dominican", "Spanish"),
    "Haiti": ("Haitian", "haitian", "haitian", "Haitian Creole"),
    "Jamaica": ("Jamaican", "jamaican", "jamaican", None),
    "Colombia": ("Colombian", "colombian", "colombian", "Spanish"),
    "Venezuela": ("Venezuelan", "venezuelan", "venezuelan", "Spanish"),
    "Peru": ("Peruvian", "peruvian", "peruvian", "Spanish"),
    "Chile": ("Chilean", "chilean", "chilean", "Spanish"),
    "Argentina": ("Argentine", "argentinian", "argentine", "Spanish"),
    "Brazil": ("Brazilian", "brazilian", "brazilian", "Portuguese"),
    "United Kingdom": ("British", "british", "british", None),
    "Ireland": ("Irish", "irish", "irish", None),
    "France": ("French", "french", "french", "French"),
    "Germany": ("German", "german", "german", "German"),
    "Italy": ("Italian", "italian", "italian", "Italian"),
    "Spain": ("Spanish", "spanish", "spanish", "Spanish"),
    "Portugal": ("Portuguese", "portuguese", "portuguese", "Portuguese"),
    "Netherlands": ("Dutch", "dutch", "dutch", "Dutch"),
    "Sweden": ("Swedish", "swedish", "swedish", "Swedish"),
    "Norway": ("Norwegian", "norwegian", "norwegian", "Norwegian"),
    "Denmark": ("Danish", "danish", "danish", "Danish"),
    "Finland": ("Finnish", "finnish", "finnish", "Finnish"),
    "Poland": ("Polish", "polish", "polish", "Polish"),
    "Czech Republic": ("Czech", "czech", "czech", "Czech"),
    "Hungary": ("Hungarian", "hungarian", "hungarian", "Hungarian"),
    "Romania": ("Romanian", "romanian", "romanian", "Romanian"),
    "Serbia": ("Serbian", "serbian", "serbian", "Serbian"),
    "Croatia": ("Croatian", "croatian", "croatian", "Croatian"),
    "Greece": ("Greek", "greek", "greek", "Greek"),
    "Russia": ("Russian", "russian", "russian", "Russian"),
    "Ukraine": ("Ukrainian", "ukrainian", "ukrainian", "Ukrainian"),
    "Armenia": ("Armenian", "armenian", "armenian", "Armenian"),
    "Turkey": ("Turkish", "turkish", "turkish", "Turkish"),
    "Israel": ("Israeli", "israeli", "israeli", "Hebrew"),
    "Lebanon": ("Lebanese", "lebanese", "lebanese", "Arabic"),
    "Egypt": ("Egyptian", "egyptian", "egyptian", "Arabic"),
    "Iran": ("Iranian", "persian", "persian", "Persian"),
    "Ethiopia": ("Ethiopian", "ethiopian", "ethiopian", "Amharic"),
    "Nigeria": ("Nigerian", "nigerian", "nigerian", None),
    "South Africa": ("South African", "south african", "south african", None),
    "India": ("Indian", "indian", "indian", None),
    "Pakistan": ("Pakistani", "pakistani", None, "Urdu"),
    "China": ("Chinese", "chinese", "chinese", "Chinese"),
    "Japan": ("Japanese", "japanese", "japanese", "Japanese"),
    "South Korea": ("Korean", "korean", "korean", "Korean"),
    "Philippines": ("Filipino", "filipino", "filipino", "Tagalog"),
    "Vietnam": ("Vietnamese", "vietnamese", "vietnamese", "Vietnamese"),
    "Thailand": ("Thai", "thai", "thai", "Thai"),
    "Indonesia": ("Indonesian", "indonesian", "indonesian", "Indonesian"),
    "Australia": ("Australian", "australian", "australian", None),
}

MAX_PER_VISITOR = 4
MAX_GUESTS = 300
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_CITY = re.compile(r"^[^\x00-\x1f<>{}\[\]\\]{2,60}$")


def valid_owner(token: Optional[str]) -> Optional[str]:
    return token if token and _TOKEN.match(token) else None


async def add_person(store: Store, qloo: Qloo, owner: str, relation: str, birth_year: int, city: str, country: str,
                     favourites: list[tuple[str, str]]) -> dict:
    if relation not in RELATIONS:
        raise ValueError("relation must be one of " + ", ".join(RELATIONS))
    if country not in COUNTRIES:
        raise ValueError("pick a country from the list")
    if not 1920 <= birth_year <= 1975:
        raise ValueError("birth year must be between 1920 and 1975")
    city = city.strip()
    if not _CITY.match(city):
        raise ValueError("hometown should be a town or city name")
    favs = [(label.strip()[:80], kind) for label, kind in favourites if label and label.strip()][:3]
    if not favs:
        raise ValueError("add at least one favourite")
    if any(kind not in roster.KINDS for _, kind in favs):
        raise ValueError("each favourite must be a singer, film, TV show or book")
    mine = store.one("SELECT COUNT(*) n FROM people WHERE owner=?", (owner,))["n"]
    if mine >= MAX_PER_VISITOR:
        raise ValueError(f"you can add up to {MAX_PER_VISITOR} people; remove one first")
    if store.one("SELECT COUNT(*) n FROM people WHERE owner IS NOT NULL")["n"] >= MAX_GUESTS:
        raise ValueError("the demo is full for today; it resets at 08:00 UTC")

    demonym, cuisine, music, lang = COUNTRIES[country]
    pid = "g-" + secrets.token_hex(6)
    languages = ", ".join(x for x in (lang, "English") if x)
    store.x("INSERT INTO people(id,kind,first_name,last_initial,birth_year,city,country,demonym,cuisine,music_genre,"
            "languages,room,present,care_note,family_note,owner) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
            (pid, "resident", relation, None, birth_year, city, country, demonym, cuisine, music, languages, None,
             None, "Added by family through the family form.", owner))
    # The family's own words and the town are the free text Qloo may receive; the relation never leaves.
    qloo.guard.allow([label for label, _ in favs] + [city, demonym, cuisine, music])
    resolved = []
    for label, kind in favs:
        r = await roster.resolve_favourite(qloo, label, kind, birth_year)
        store.x("INSERT INTO favourites(person_id,label,kind,entity_id,entity_name,status,source) "
                "VALUES(?,?,?,?,?,?,'family')", (pid, label, kind, r.get("entity_id"), r.get("entity_name"), r["status"]))
        resolved.append({"label": label, "kind": kind, "status": r["status"], "entity_name": r.get("entity_name")})
    return {"id": pid, "favourites": resolved}


def remove_person(store: Store, owner: str, pid: str) -> bool:
    row = store.one("SELECT id FROM people WHERE id=? AND owner=?", (pid, owner))
    if not row:
        return False
    for t in ("favourites", "avoid", "reactions"):
        store.x(f"DELETE FROM {t} WHERE person_id=?", (pid,))
    store.x("DELETE FROM sessions WHERE person_ids LIKE ?", (f'%"{pid}"%',))
    store.x("DELETE FROM people WHERE id=?", (pid,))
    return True
