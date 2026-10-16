"""What leaves the building: only structured values and registered free text reach Qloo."""
import json

import pytest

from encore import roster
from encore.agent import Agent
from encore.qloo import PrivacyGuard, PrivacyViolation


def test_guard_refuses_unregistered_free_text():
    g = PrivacyGuard()
    g.allow(["Frank Sinatra"])
    g.check([("query", "Frank Sinatra")])
    with pytest.raises(PrivacyViolation):
        g.check([("query", "Tomasz W")])


def test_guard_refuses_a_protected_name_inside_a_structured_value():
    g = PrivacyGuard()
    g.protect(["Tomasz"])
    g.check([("filter.release_country", "Poland")])
    with pytest.raises(PrivacyViolation):
        g.check([("filter.tags", "urn:tag:genre:music:tomasz")])


def test_guard_refuses_free_text_in_structured_fields():
    g = PrivacyGuard()
    with pytest.raises(PrivacyViolation):
        g.check([("signal.interests.entities", "hearing aid; few words this week!")])


async def test_no_name_or_note_reaches_qloo_across_every_flow(enc, fake):
    """Drive every feature, then read every request the fake Qloo received."""
    for r in roster.people(enc.store, "resident"):
        await enc.profile(r["id"])
    await enc.lounge("movie")
    await enc.lounge("artist")
    plan = await enc.plan("r-tomasz", "c-priya")
    step = next(s for s in plan["steps"] if s.get("item"))
    await enc.react("r-tomasz", {**step["item"], "type": step["item"].get("type", "artist")}, "lit_up", "c-priya", plan["id"])
    await Agent(enc).ask("Plan a session for Tomasz with Priya")
    sent = fake.all_params_text()
    assert len(fake.requests) > 50
    people = enc.store.q("SELECT first_name, care_note, family_note FROM people")
    for p in people:
        assert f'"{p["first_name"].lower()}"' not in sent
        for note in (p["care_note"], p["family_note"]):
            if note:
                assert note.lower()[:30] not in sent
    keys = {k for _, params in fake.requests for k, _ in params}
    assert keys <= {"query", "types", "take", "filter.type", "filter.query", "signal.interests.entities", "filter.tags",
                    "filter.release_country", "filter.release_year.min", "filter.release_year.max",
                    "filter.publication_year.min", "filter.publication_year.max", "filter.exclude.tags",
                    "filter.results.entities", "signal.demographics.age", "feature.explainability",
                    "filter.location.query", "filter.location.radius", "a.signal.interests.entities",
                    "b.signal.interests.entities"}


async def test_api_key_travels_only_in_the_header(enc, fake):
    await enc.profile("r-rosa")
    assert "test-key" not in json.dumps(fake.requests)
    assert "test-key" not in json.dumps(enc.qloo.recent_log())
