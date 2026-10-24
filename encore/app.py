"""HTTP API and the web app."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import family
from .agent import Agent
from .config import ROOT, load_config
from .learning import REACTIONS
from .qloo import PrivacyViolation, QlooUnavailable
from .service import Encore, NotFound

log = logging.getLogger("encore")
WEB = ROOT / "web" / "dist"
# The MCP server sets the root logger to INFO, which would make httpx log every outbound request.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class Present(BaseModel):
    present: bool


class NewFavourite(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    kind: str


class Confirm(BaseModel):
    entity_id: str = Field(pattern=r"^[A-Fa-f0-9-]{36}$")
    entity_name: str = Field(max_length=200)


class AvoidTag(BaseModel):
    tag_id: str = Field(pattern=r"^urn:tag:[a-z0-9_:\-]+$")
    label: str = Field(max_length=80)


class Lounge(BaseModel):
    domain: str = "movie"
    residents: Optional[list[str]] = None
    max_minutes: Optional[int] = Field(default=None, ge=30, le=240)


class SessionReq(BaseModel):
    resident: str
    carer: str


class Item(BaseModel):
    entity_id: str = Field(pattern=r"^[A-Fa-f0-9-]{36}$")
    name: str = Field(max_length=200)
    type: str = "artist"
    genre_tags: list[dict] = []


class Reaction(BaseModel):
    person_id: str
    item: Item
    reaction: str
    carer_id: Optional[str] = None
    session_id: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=300)


class NewPerson(BaseModel):
    relation: str = Field(max_length=20)
    birth_year: int = Field(ge=1920, le=1975)
    city: str = Field(min_length=2, max_length=60)
    country: str = Field(max_length=40)
    favourites: list[NewFavourite] = Field(min_length=1, max_length=3)


class Ask(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    history: list[dict] = []


def visitor_of(request: Request) -> str:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def owner_of(request: Request) -> Optional[str]:
    """The random token a visitor's browser keeps, so people they add stay theirs."""
    return family.valid_owner(request.headers.get("x-encore-visitor"))


def from_this_machine(request: Request) -> bool:
    """The nightly timer calls the app directly; every request through Caddy carries X-Forwarded-For."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1") and "x-forwarded-for" not in request.headers


def create_app(enc: Optional[Encore] = None, warm: bool = True) -> FastAPI:
    enc = enc or Encore(load_config())
    agent = Agent(enc)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await enc.start()
        task = asyncio.create_task(enc.warm()) if warm and enc.qloo.live else None
        mcp = getattr(app.state, "mcp", None)
        async with (mcp.session_manager.run() if mcp is not None else contextlib.nullcontext()):
            yield
        if task:
            task.cancel()
        await enc.aclose()

    app = FastAPI(title="Encore", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.enc = enc

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return resp

    @app.exception_handler(NotFound)
    async def not_found(_: Request, e: NotFound):
        return JSONResponse({"error": f"not found: {e.args[0] if e.args else ''}"}, status_code=404)

    @app.exception_handler(QlooUnavailable)
    async def qloo_down(_: Request, e: QlooUnavailable):
        return JSONResponse({"error": "Qloo is not answering right now and nothing is cached for this request.",
                             "detail": str(e)}, status_code=503)

    @app.exception_handler(PrivacyViolation)
    async def privacy(_: Request, e: PrivacyViolation):
        return JSONResponse({"error": "Encore refused to send this to Qloo.", "detail": str(e)}, status_code=422)

    @app.exception_handler(ValueError)
    async def bad(_: Request, e: ValueError):
        return JSONResponse({"error": str(e)}, status_code=400)

    def check_owner(request: Request, *pids: Optional[str]) -> None:
        """Someone a visitor added answers only to that visitor's token; the fictional residents stay open."""
        for pid in pids:
            if pid:
                owner = enc.person(pid).get("owner")
                if owner and owner != owner_of(request):
                    raise NotFound(pid)

    # ---- reads ---------------------------------------------------------------------------

    @app.get("/api/status")
    async def status():
        return {"qloo": "live" if enc.qloo.live else "cache only", "model": enc.ai.model,
                "model_live": enc.ai.why_not_live(None) is None, "model_calls_today": enc.ai.calls_today(),
                "warm": enc.warm_state, "reactions": REACTIONS}

    @app.get("/api/home")
    async def home(request: Request):
        return enc.home(owner_of(request))

    @app.get("/api/people/{pid}/profile")
    async def profile(pid: str, request: Request):
        check_owner(request, pid)
        return await enc.profile(pid)

    @app.get("/api/lounge")
    async def lounge_get(request: Request, domain: str = "movie", max_minutes: Optional[int] = None,
                         add: Optional[str] = None):
        check_owner(request, add)
        return await enc.lounge(domain, None, max_minutes, [add] if add else None)

    @app.get("/api/week")
    async def week_plan():
        return await enc.week()

    @app.post("/api/lounge")
    async def lounge_post(body: Lounge, request: Request):
        check_owner(request, *(body.residents or []))
        return await enc.lounge(body.domain, body.residents, body.max_minutes)

    @app.get("/api/common")
    async def common(resident: str, carer: str, request: Request):
        check_owner(request, resident, carer)
        return await enc.common(resident, carer)

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str, request: Request):
        s = enc.session(sid)
        check_owner(request, s["resident"]["id"])
        return s

    @app.get("/api/sessions")
    async def list_sessions(request: Request):
        others = {r["id"] for r in enc.store.q("SELECT id FROM people WHERE owner IS NOT NULL AND owner IS NOT ?",
                                               (owner_of(request),))}
        rows = enc.store.q("SELECT id, at, carer_id, person_ids, plan FROM sessions ORDER BY at DESC LIMIT 30")
        out = []
        for r in rows:
            p = json.loads(r["plan"])
            if p["resident"]["id"] in others:
                continue
            n = enc.store.one("SELECT COUNT(*) n FROM reactions WHERE session_id=?", (r["id"],))["n"]
            out.append({"id": r["id"], "at": r["at"], "resident": p["resident"]["first_name"],
                        "resident_id": p["resident"]["id"], "carer": p["carer"]["first_name"], "reactions": n})
        return out

    @app.get("/api/record/{pid}")
    async def record(pid: str, request: Request):
        check_owner(request, pid)
        return enc.record(pid)

    @app.get("/api/qloo/log")
    async def qloo_log(limit: int = 150):
        return enc.qloo_log(min(limit, 500))

    @app.get("/api/eval")
    async def evaluation():
        f = ROOT / "eval" / "results.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"available": False}

    # ---- writes --------------------------------------------------------------------------

    @app.post("/api/sessions")
    async def new_session(body: SessionReq, request: Request):
        check_owner(request, body.resident, body.carer)
        return await enc.plan(body.resident, body.carer, visitor_of(request))

    @app.post("/api/reactions")
    async def react(body: Reaction, request: Request):
        check_owner(request, body.person_id)
        return await enc.react(body.person_id, body.item.model_dump(), body.reaction, body.carer_id, body.session_id,
                               body.note)

    @app.post("/api/people")
    async def add_person(body: NewPerson, request: Request):
        owner = owner_of(request)
        if not owner:
            raise HTTPException(400, "Missing visitor token.")
        return await enc.add_person(owner, body.relation, body.birth_year, body.city, body.country,
                                    [(f.label, f.kind) for f in body.favourites])

    @app.delete("/api/people/{pid}")
    async def remove_person(pid: str, request: Request):
        owner = owner_of(request)
        if not owner:
            raise HTTPException(400, "Missing visitor token.")
        enc.remove_person(owner, pid)
        return {"ok": True}

    @app.post("/api/people/{pid}/present")
    async def present(pid: str, body: Present):
        enc.set_present(pid, body.present)
        return {"ok": True}

    @app.post("/api/people/{pid}/favourites")
    async def add_fav(pid: str, body: NewFavourite, request: Request):
        check_owner(request, pid)
        return await enc.add_favourite(pid, body.label, body.kind)

    @app.delete("/api/people/{pid}/favourites/{fid}")
    async def del_fav(pid: str, fid: int, request: Request):
        check_owner(request, pid)
        enc.remove_favourite(pid, fid)
        return {"ok": True}

    @app.post("/api/favourites/{fid}/confirm")
    async def confirm(fid: int, body: Confirm, request: Request):
        fav = enc.store.one("SELECT person_id FROM favourites WHERE id=?", (fid,))
        if not fav:
            raise NotFound(fid)
        check_owner(request, fav["person_id"])
        enc.confirm_favourite(fid, body.entity_id, body.entity_name)
        return {"ok": True}

    @app.post("/api/people/{pid}/avoid")
    async def avoid(pid: str, body: AvoidTag, request: Request):
        check_owner(request, pid)
        enc.add_avoid_tag(pid, body.tag_id, body.label)
        return {"ok": True}

    @app.delete("/api/people/{pid}/avoid/{aid}")
    async def del_avoid(pid: str, aid: int, request: Request):
        check_owner(request, pid)
        enc.remove_avoid(pid, aid)
        return {"ok": True}

    @app.post("/api/agent")
    async def ask(body: Ask, request: Request):
        hist = [{"role": "model" if m.get("role") == "model" else "user", "text": str(m.get("text", ""))[:1500]}
                for m in body.history[-6:]]
        return await agent.ask(body.message, hist, visitor_of(request))

    last_reset = {"t": 0.0}

    @app.post("/api/demo/reset")
    async def reset(request: Request):
        if not from_this_machine(request):
            raise HTTPException(403, "The demo resets itself every night at 08:00 UTC.")
        if time.time() - last_reset["t"] < 20:
            raise HTTPException(429, "The demo was reset a moment ago.")
        last_reset["t"] = time.time()
        await enc.reset()
        return {"ok": True}

    img_dir = enc.cfg.data_dir / "img"
    img_dir.mkdir(exist_ok=True)

    @app.get("/img/{name}", include_in_schema=False)
    async def image(name: str):
        """Qloo's images need the API key, so the server fetches them and keeps a private copy."""
        import re
        from fastapi.responses import Response
        if not re.fullmatch(r"[A-Fa-f0-9-]{36}-420x-auto\.jpg", name):
            raise HTTPException(404)
        f = img_dir / name
        headers = {"Cache-Control": "public, max-age=604800"}
        if f.exists():
            return FileResponse(f, media_type="image/jpeg", headers=headers)
        if not enc.qloo.live:
            raise HTTPException(404)
        r = await enc.qloo._http.get(f"https://images.qloo.com/i/{name}", headers={"X-Api-Key": enc.cfg.qloo_api_key})
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            raise HTTPException(404)
        f.write_bytes(r.content)
        return Response(r.content, media_type="image/jpeg", headers=headers)

    from .mcp_server import mount_mcp
    mount_mcp(app, agent)

    # ---- web app -------------------------------------------------------------------------

    if WEB.exists():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (WEB / path).resolve()
            if path and f.is_file() and WEB.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    return app
