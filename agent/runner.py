"""Entry point — starts MCP server + API bridge in-process, then runs the LangGraph agent."""

import asyncio
import json
import os
import sys
import threading
import time

from dotenv import load_dotenv

import httpx
import uvicorn
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from simulation.state import get_model
from agent.shared import set_start_trigger, set_mission_complete
from .graph import build_graph, _log_to_model


# ── Windows error suppression ─────────────────────────────────────────

def _make_proactor_exception_handler():
    """Windows ProactorEventLoop handler — suppresses harmless connection-reset errors."""
    def handler(loop, context):
        msg = context.get("message", "")
        if "_ProactorBasePipeTransport" in msg:
            return
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError):
            return
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10054, 10053):
            return
        loop.default_exception_handler(context)
    return handler


def _run_uvicorn_with_suppression(server):
    """Run uvicorn server with Windows error suppression on its event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if sys.platform == "win32":
        loop.set_exception_handler(_make_proactor_exception_handler())
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()


# ── Server launchers ──────────────────────────────────────────────────

def start_mcp_server():
    """Run the FastMCP server as a daemon thread on :8000."""
    from mcp_server.server import mcp
    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=_run_uvicorn_with_suppression, args=(server,), daemon=True)
    thread.start()
    return server


def start_api_bridge():
    """Run the FastAPI bridge as a daemon thread on :8001."""
    from api.bridge import app
    config = uvicorn.Config(app, host="0.0.0.0", port=8001, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=_run_uvicorn_with_suppression, args=(server,), daemon=True)
    thread.start()
    return server


async def wait_for_server(url: str, name: str, max_retries: int = 5):
    """Wait for a server to become ready with exponential backoff."""
    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    print(f"  {name} ready on {url}")
                    return
            except httpx.ConnectError:
                pass
            delay = 2 ** attempt
            print(f"  Waiting for {name}... (retry {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)
    raise RuntimeError(f"{name} failed to start after {max_retries} retries")


# ── Mission log persistence ──────────────────────────────────────────

def save_mission_log(model):
    """Save agent_logs + final stats to logs/mission_log.json."""
    os.makedirs("logs", exist_ok=True)
    state = model.get_state()
    log_data = {
        "mission_steps": model.mission_step,
        "stats": state["stats"],
        "logs": model.agent_logs,
        "disaster_events": model.disaster_events,
    }
    path = os.path.join("logs", "mission_log.json")
    with open(path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)
    print(f"\nMission log saved to {path}")


# ── Main mission runner ──────────────────────────────────────────────

async def _execute_mission(tools):
    """Build agent graph and run the mission with the given MCP tools."""
    # 3. Build the LangGraph agent
    print("\n[3/4] Building agent graph...")
    graph = build_graph(tools)

    # Wait for dashboard "Start Mission" button
    start_event = threading.Event()
    set_start_trigger(start_event)
    print("\n[4/5] Waiting for Start Mission from dashboard (http://localhost:3000)...")
    await asyncio.to_thread(start_event.wait)

    # Log mission start
    model = get_model()
    _log_to_model("Mission initiated — LLM Commander online.", msg_type="system", is_critical=True)

    # 5. Run the mission
    print("\n[5/5] Starting mission...\n")
    print("-" * 60)

    initial_message = (
        "Begin search and rescue mission. "
        "Discover your fleet and plan your approach."
    )

    try:
        result = await graph.ainvoke(
            {"messages": [("human", initial_message)]},
            config={"recursion_limit": 200},
        )

        # Print final AI message
        final_msg = result["messages"][-1]
        if hasattr(final_msg, "content") and final_msg.content:
            print("\n" + "-" * 60)
            print("COMMANDER FINAL REPORT:")
            print(final_msg.content)

    except Exception as e:
        error_name = type(e).__name__
        print(f"\nMission ended: {error_name}: {e}")
        _log_to_model(f"Mission ended: {error_name}", msg_type="system", is_critical=True)

    # Mark mission complete
    set_mission_complete(True)

    # Save logs
    print("\n" + "=" * 60)
    model = get_model()
    state = model.get_state()
    stats = state["stats"]
    print(f"  Steps: {model.mission_step}")
    print(f"  Survivors found: {stats['found']}/{stats['total_survivors']}")
    print(f"  Survivors rescued: {stats['rescued']}/{stats['total_survivors']}")
    print(f"  Survivors alive: {stats['alive']}/{stats['total_survivors']}")
    print(f"  Active drones: {stats['active_drones']}/{stats['total_drones']}")
    print(f"  Grid coverage: {stats['coverage_pct']}%")
    print("=" * 60)

    save_mission_log(model)


async def run_mission():
    """Start servers, connect MCP, build agent graph, and run the mission."""
    print("=" * 60)
    print("  DRONE SWARM RESCUE — Mission Control")
    print("=" * 60)

    # Suppress Windows ProactorEventLoop cleanup errors
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_make_proactor_exception_handler())

    # 1. Start MCP server + API bridge in background threads
    print("\n[1/4] Starting servers...")
    start_mcp_server()
    start_api_bridge()

    # Wait for both to be ready
    await wait_for_server("http://localhost:8000/mcp", "MCP Server")
    await wait_for_server("http://localhost:8001/api/health", "API Bridge")

    # 2. Connect to MCP and load tools via persistent session
    print("\n[2/4] Connecting to MCP server...")
    mcp_client = MultiServerMCPClient(
        {
            "drone_swarm": {
                "url": "http://localhost:8000/mcp",
                "transport": "streamable_http",
            }
        }
    )

    async with mcp_client.session("drone_swarm") as session:
        tools = await load_mcp_tools(session)
        print(f"  Loaded {len(tools)} MCP tools")
        await _execute_mission(tools)


def main():
    """CLI entry point."""
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable is required.")
        print("Set it with: export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    print(f"Using LLM model: {os.environ.get('LLM_MODEL', 'gpt-5-mini')}")
    asyncio.run(run_mission())


if __name__ == "__main__":
    main()
