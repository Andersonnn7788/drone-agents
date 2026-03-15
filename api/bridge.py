"""FastAPI Bridge — SSE streaming + REST endpoints for the Next.js dashboard."""

import asyncio
import json
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from simulation.state import get_model, reset_model

app = FastAPI(title="Drone Swarm API Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared state ───────────────────────────────────────────────────────

model_lock = threading.Lock()
mission_running = False
_background_task: asyncio.Task | None = None


# ── Request models ─────────────────────────────────────────────────────

class StepRequest(BaseModel):
    steps: int = 1


class BlackoutRequest(BaseModel):
    zone_x: int
    zone_y: int
    radius: int


class ResetRequest(BaseModel):
    seed: int = 42


# ── SSE streaming ──────────────────────────────────────────────────────

async def _sse_generator():
    """Yield SSE events when simulation state changes."""
    last_step = -1
    last_log_count = 0
    last_disaster_count = 0

    # Send initial state immediately
    model = get_model()
    last_step = model.mission_step
    last_log_count = len(model.agent_logs)
    last_disaster_count = len(model.disaster_events)
    yield f"event: state\ndata: {json.dumps(model.get_state())}\n\n"

    while True:
        await asyncio.sleep(0.5)
        model = get_model()

        # Check for new simulation steps
        if model.mission_step != last_step:
            last_step = model.mission_step
            yield f"event: state\ndata: {json.dumps(model.get_state())}\n\n"

        # Check for new agent log entries
        current_log_count = len(model.agent_logs)
        if current_log_count > last_log_count:
            new_logs = model.agent_logs[last_log_count:]
            last_log_count = current_log_count
            yield f"event: logs\ndata: {json.dumps(new_logs)}\n\n"

        # Check for new disaster events
        current_disaster_count = len(model.disaster_events)
        if current_disaster_count > last_disaster_count:
            new_events = model.disaster_events[last_disaster_count:]
            last_disaster_count = current_disaster_count
            for event in new_events:
                event_type = "blackout" if event.get("type") == "blackout" else "disaster"
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"


@app.get("/api/stream")
async def stream():
    """SSE endpoint — streams state, logs, disaster, and blackout events."""
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── REST GET endpoints ─────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    """Full simulation state snapshot."""
    return get_model().get_state()


@app.get("/api/logs")
async def get_logs():
    """All agent reasoning log entries."""
    return get_model().agent_logs


@app.get("/api/history")
async def get_history():
    """All state snapshots for mission replay timeline."""
    model = get_model()
    return {
        "total_steps": model.mission_step,
        "snapshots": [
            {"step": i, "state": snapshot}
            for i, snapshot in enumerate(model.state_history)
        ],
    }


@app.get("/api/mesh")
async def get_mesh():
    """Current mesh network topology."""
    return get_model().mesh_topology


@app.get("/api/health")
async def health():
    """Health check with mission status."""
    model = get_model()
    return {
        "status": "ok",
        "mission_step": model.mission_step,
        "mission_running": mission_running,
    }


# ── POST action endpoints ─────────────────────────────────────────────

@app.post("/api/step")
async def step(req: StepRequest):
    """Advance simulation by N steps."""
    model = get_model()
    with model_lock:
        for _ in range(req.steps):
            model.step()
    state = model.get_state()
    return {
        "steps_advanced": req.steps,
        "mission_step": state["mission_step"],
        "stats": state["stats"],
    }


@app.post("/api/blackout")
async def blackout(req: BlackoutRequest):
    """Trigger a communication blackout zone."""
    model = get_model()
    with model_lock:
        event = model.trigger_blackout(req.zone_x, req.zone_y, req.radius)
    return event


@app.post("/api/start")
async def start_mission():
    """Start auto-stepping the simulation (placeholder until LangGraph agent)."""
    global mission_running, _background_task

    if mission_running:
        return {"status": "already_running", "mission_step": get_model().mission_step}

    mission_running = True
    _background_task = asyncio.create_task(_auto_step_loop())
    return {"status": "started", "mission_step": get_model().mission_step}


@app.post("/api/reset")
async def reset(req: ResetRequest):
    """Reset simulation to a fresh state."""
    global mission_running, _background_task

    mission_running = False
    if _background_task and not _background_task.done():
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass
    _background_task = None

    with model_lock:
        model = reset_model(req.seed)
    return {
        "status": "reset",
        "seed": req.seed,
        "mission_step": model.mission_step,
    }


# ── Background auto-step loop ─────────────────────────────────────────

async def _auto_step_loop():
    """Placeholder: auto-advance simulation until mission ends or 50 steps."""
    global mission_running
    try:
        while mission_running:
            model = get_model()
            if model.mission_step >= 50:
                break
            with model_lock:
                model.step()
            await asyncio.sleep(2.0)
    finally:
        mission_running = False
