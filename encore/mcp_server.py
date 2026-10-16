"""Encore's tools over MCP, so any assistant can plan with the same evidence the web app uses.

The tools are the agent's read-only tools: an assistant can look, rank and plan, and only staff
record reactions or change avoid lists. Mounted at /mcp on the web server (Streamable HTTP), or run
on stdio with `python -m encore.mcp_server`.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

from .agent import Agent

INSTRUCTIONS = ("Encore plans reminiscence activities in a care home from the culture of each resident's youth, "
                "using Qloo's taste graph. Start with list_people, then use first names in the other tools.")


def build_mcp(agent: Agent) -> MCPServer:
    server = MCPServer(name="encore", title="Encore", instructions=INSTRUCTIONS)

    async def run(name: str, args: dict) -> dict[str, Any]:
        result, _card = await agent.call(name, args, visitor="mcp")
        return result

    @server.tool(description="Residents and carers at the home, with birth year, hometown and who is in the lounge today.")
    async def list_people() -> dict[str, Any]:
        return await run("list_people", {})

    @server.tool(description="The culture of one resident's youth (ages 10 to 30) from Qloo: songs, films, TV, family favourites, avoid list.")
    async def resident_profile(resident: str) -> dict[str, Any]:
        return await run("resident_profile", {"resident": resident})

    @server.tool(description="Pick the lounge film: best fit for the least-served resident present, alternatives scored the same way.")
    async def lounge_film(max_minutes: Optional[int] = None, residents: Optional[list[str]] = None) -> dict[str, Any]:
        return await run("lounge_film", {"max_minutes": max_minutes, "residents": residents or []})

    @server.tool(description="A music-hour playlist where every resident present hears an artist from their youth that fits them.")
    async def music_hour(residents: Optional[list[str]] = None) -> dict[str, Any]:
        return await run("music_hour", {"residents": residents or []})

    @server.tool(description="Plan a ten-minute one-to-one session for a resident and a carer, with the words to say.")
    async def plan_one_to_one(resident: str, carer: str) -> dict[str, Any]:
        return await run("plan_one_to_one", {"resident": resident, "carer": carer})

    @server.tool(description="Tastes a resident and a carer share, and an artist and film from the resident's youth both point to.")
    async def common_ground(resident: str, carer: str) -> dict[str, Any]:
        return await run("common_ground", {"resident": resident, "carer": carer})

    @server.tool(description="The week's programme: two lounge films chosen together, a music hour, and carers matched to residents by shared tastes.")
    async def week_plan() -> dict[str, Any]:
        return await run("week_plan", {})

    return server


def mount_mcp(app: FastAPI, agent: Agent) -> MCPServer:
    server = build_mcp(agent)
    inner = server.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                       host="0.0.0.0")
    app.mount("/mcp", inner)
    app.state.mcp = server
    return server


def main() -> None:
    from .config import load_config
    from .service import Encore

    enc = Encore(load_config())
    asyncio.run(enc.start())
    build_mcp(Agent(enc)).run()


if __name__ == "__main__":
    main()
