"""FastAPI Bridge — SSE streaming + REST endpoints for the Next.js dashboard."""

import asyncio
import json
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from simulation.state import get_model, reset_model
from agent.shared import get_start_trigger, is_mission_complete
from agent.memory import load_lessons

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
    global mission_running
    last_step = -1
    last_log_count = 0
    last_disaster_count = 0
    last_drone_hash = ""
    last_survivor_hash = ""
    last_warning_count = 0

    # Send initial state immediately
    model = get_model()
    last_step = model.mission_step
    last_disaster_count = len(model.disaster_events)
    last_drone_hash = str([(d.drone_id, d.pos) for d in model.drones.values()])
    yield f"event: state\ndata: {json.dumps(model.get_state())}\n\n"

    # Send any existing logs so clients connecting mid-mission don't miss them
    if model.agent_logs:
        yield f"event: logs\ndata: {json.dumps(model.agent_logs)}\n\n"
    last_log_count = len(model.agent_logs)

    while True:
        await asyncio.sleep(0.10)
        model = get_model()

        # Check for drone position changes (move_to before advance_simulation)
        drone_hash = str([(d.drone_id, d.pos) for d in model.drones.values()])
        drone_moved = drone_hash != last_drone_hash
        if drone_moved:
            last_drone_hash = drone_hash

        # Check for survivor state changes (found/rescued/alive from MCP tools)
        survivor_hash = str([(s.unique_id, s.found, s.rescued, s.alive, round(s.health, 1)) for s in model.survivors])
        survivor_changed = survivor_hash != last_survivor_hash
        if survivor_changed:
            last_survivor_hash = survivor_hash

        # Check for new simulation steps or state changes
        if model.mission_step != last_step or drone_moved or survivor_changed:
            last_step = model.mission_step
            yield f"event: state\ndata: {json.dumps(model.get_state())}\n\n"

        # Check for new agent log entries
        current_log_count = len(model.agent_logs)
        if current_log_count > last_log_count:
            new_logs = model.agent_logs[last_log_count:]
            last_log_count = current_log_count
            yield f"event: logs\ndata: {json.dumps(new_logs)}\n\n"

        # Check for new warning events
        current_warning_count = len(model.warning_events)
        if current_warning_count > last_warning_count:
            new_warnings = model.warning_events[last_warning_count:]
            last_warning_count = current_warning_count
            for warning in new_warnings:
                # Strip internal pending_id before sending
                w = {k: v for k, v in warning.items() if k != "pending_id"}
                yield f"event: warning\ndata: {json.dumps(w)}\n\n"

        # Check for new disaster events
        current_disaster_count = len(model.disaster_events)
        if current_disaster_count > last_disaster_count:
            new_events = model.disaster_events[last_disaster_count:]
            last_disaster_count = current_disaster_count
            for event in new_events:
                event_type = "blackout" if event.get("type") in ("blackout", "blackout_cleared") else "disaster"
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

        # Check for mission completion
        if mission_running and is_mission_complete():
            mission_running = False
            state = model.get_state()
            completion_data = {
                "mission_step": model.mission_step,
                "stats": state["stats"],
                "disaster_event_count": len(model.disaster_events),
                "status": "completed",
                "score": model.compute_score(),
            }
            yield f"event: mission_complete\ndata: {json.dumps(completion_data)}\n\n"
            break


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


@app.get("/api/score")
async def get_score():
    """Current mission score breakdown."""
    return get_model().compute_score()


@app.get("/api/lessons")
async def get_lessons():
    """Lessons learned from past missions."""
    return load_lessons()


@app.get("/api/health")
async def health():
    """Health check with mission status."""
    global mission_running
    if mission_running and is_mission_complete():
        mission_running = False
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
    """Signal the LangGraph agent runner to begin the mission."""
    global mission_running

    if mission_running:
        return {"status": "already_running", "mission_step": get_model().mission_step}

    event = get_start_trigger()
    if event is None:
        return {"status": "error", "message": "Agent runner not ready yet"}

    mission_running = True
    event.set()
    return {"status": "started", "mission_step": get_model().mission_step}


@app.post("/api/reset")
async def reset(req: ResetRequest):
    """Reset simulation to a fresh state."""
    global mission_running
    mission_running = False

    with model_lock:
        model = reset_model(req.seed)
    return {
        "status": "reset",
        "seed": req.seed,
        "mission_step": model.mission_step,
    }
