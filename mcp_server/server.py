"""FastMCP server — 19 @mcp.tool() definitions wrapping the drone swarm simulation."""

import os

from mcp.server.fastmcp import FastMCP
from simulation.state import get_model
from simulation.model import BASE_POS
from simulation.mesh_network import sync_drone, get_network_resilience as _get_network_resilience

mcp = FastMCP("DroneSwarm", host="0.0.0.0", port=8000)


# ── Helper ─────────────────────────────────────────────────────────────

def _get_drone(drone_id: str):
    """Look up a drone by ID, returning (drone, None) or (None, error_dict)."""
    model = get_model()
    drone = model.drones.get(drone_id)
    if drone is None:
        return None, {"error": f"Unknown drone_id '{drone_id}'. Valid IDs: {list(model.drones.keys())}"}
    return drone, None


# ── Core Tools (11) ────────────────────────────────────────────────────

@mcp.tool()
def discover_drones() -> list[dict]:
    """Return a list of all drones and their current state (position, battery, status, connectivity).
    Call this FIRST before issuing any drone commands — never hard-code drone IDs."""
    model = get_model()
    return [drone.to_dict() for drone in model.drones.values()]


@mcp.tool()
def move_to(drone_id: str, x: int, y: int) -> dict:
    """Move a drone one step toward the target grid position (x, y).
    Costs 2 battery. Fails if target is WATER, out of bounds, or drone is dead/relay."""
    drone, err = _get_drone(drone_id)
    if err:
        return err
    if not drone.connected:
        return {"error": f"Drone '{drone_id}' is disconnected (blackout). Cannot command — it is operating autonomously."}
    return drone.move_to(x, y)


@mcp.tool()
def thermal_scan(drone_id: str) -> dict:
    """Perform a thermal scan at the drone's current position (radius 1).
    Costs 3 battery. Discovers survivors, updates heatmap, deposits pheromones.
    Returns list of newly found survivors with severity and health."""
    drone, err = _get_drone(drone_id)
    if err:
        return err
    if not drone.connected:
        return {"error": f"Drone '{drone_id}' is disconnected (blackout). Cannot command — it is operating autonomously."}
    return drone.thermal_scan()


@mcp.tool()
def get_battery_status(drone_id: str = None) -> dict | list[dict]:
    """Get battery and status info for one drone (by ID) or all drones (if drone_id is None).
    Use this to check which drones have enough charge for a mission."""
    model = get_model()
    if drone_id is not None:
        drone, err = _get_drone(drone_id)
        if err:
            return err
        return {
            "drone_id": drone.drone_id,
            "battery": drone.battery,
            "status": drone.status,
            "position": list(drone.pos) if drone.pos else [0, 0],
        }
    return [
        {
            "drone_id": d.drone_id,
            "battery": d.battery,
            "status": d.status,
            "position": list(d.pos) if d.pos else [0, 0],
        }
        for d in model.drones.values()
    ]


@mcp.tool()
def get_priority_map() -> list[list[float]]:
    """Get the 12x12 priority map combining Bayesian heatmap with pheromone data.
    Higher values = higher priority to scan. Use this to decide where to send drones next.
    Indexed as priority_map[y][x]."""
    model = get_model()
    return model.get_priority_map()


@mcp.tool()
def simulate_mission(drone_id: str, target_x: int, target_y: int) -> dict:
    """Digital twin: predict the battery cost and feasibility of sending a drone to (target_x, target_y).
    Returns arrival_battery, post_scan_battery, return_feasibility, survivor_probability, and terrain.
    Use this for chain-of-thought planning BEFORE committing a drone to a move."""
    model = get_model()
    drone, err = _get_drone(drone_id)
    if err:
        return err
    return model.simulate_mission(drone_id, target_x, target_y)


@mcp.tool()
def sync_findings(drone_id: str) -> dict:
    """Flush a drone's buffered findings (collected while disconnected during blackout).
    Returns the list of scan results that were queued. Call this after connectivity is restored."""
    drone, err = _get_drone(drone_id)
    if err:
        return err
    findings = sync_drone(drone)
    return {
        "drone_id": drone_id,
        "synced_findings": findings,
        "count": len(findings),
    }


@mcp.tool()
def trigger_blackout(zone_x: int, zone_y: int, radius: int) -> dict:
    """Trigger a communication blackout centered at (zone_x, zone_y) with given radius.
    Drones inside the zone lose connectivity and switch to autonomous pheromone-guided behavior.
    Returns list of affected drone IDs."""
    model = get_model()
    return model.trigger_blackout(zone_x, zone_y, radius)


@mcp.tool()
def recall_drone(drone_id: str) -> dict:
    """Order a drone to return to base station at (6,5) for recharging.
    The drone will pathfind back autonomously each simulation step."""
    drone, err = _get_drone(drone_id)
    if err:
        return err
    if not drone.connected:
        return {"error": f"Drone '{drone_id}' is disconnected (blackout). Cannot command — it is operating autonomously."}
    return drone.return_to_base()


@mcp.tool()
def get_mission_summary() -> dict:
    """Get a narrative-friendly summary of the current mission state.
    Includes drone statuses, survivor stats, coverage, disaster events, and key metrics.
    Use this to form your chain-of-thought reasoning about what to do next."""
    model = get_model()
    state = model.get_state()
    stats = state["stats"]

    # Build narrative-friendly fields
    drone_summaries = []
    for d in state["drones"].values():
        drone_summaries.append(
            f"{d['drone_id']}: battery={d['battery']}%, status={d['status']}, "
            f"pos=({d['position'][0]},{d['position'][1]}), connected={d['connected']}"
        )

    survivor_summaries = []
    for s in state["survivors"]:
        survivor_summaries.append(
            f"Survivor #{s['survivor_id']}: {s['severity']}, health={s['health']}, "
            f"pos=({s['position'][0]},{s['position'][1]}), "
            f"{'RESCUED' if s['rescued'] else ('DEAD' if not s['alive'] else 'alive')}"
        )

    return {
        "mission_step": state["mission_step"],
        "stats": stats,
        "drone_summaries": drone_summaries,
        "survivor_summaries": survivor_summaries,
        "disaster_event_count": len(state["disaster_events"]),
        "recent_disasters": state["disaster_events"][-3:] if state["disaster_events"] else [],
        "blackout_zones": state["blackout_zones"],
        "narrative": (
            f"Step {state['mission_step']}: {stats['active_drones']}/{stats['total_drones']} drones active, "
            f"{stats['found']} survivors found, {stats['rescued']} rescued, "
            f"{stats['alive']}/{stats['total_survivors']} alive, "
            f"{stats['coverage_pct']}% grid scanned, "
            f"{len(state['disaster_events'])} disaster events."
        ),
    }


@mcp.tool()
def advance_simulation(steps: int = 1) -> dict:
    """Advance the simulation by N steps. Each step: drains battery, decays pheromones,
    drains survivor health, runs drone autonomy, checks for aftershocks/floods,
    and recomputes mesh topology. Returns the new state summary after stepping."""
    model = get_model()
    for _ in range(steps):
        model.step()
    state = model.get_state()
    return {
        "steps_advanced": steps,
        "new_mission_step": state["mission_step"],
        "stats": state["stats"],
        "recent_disasters": state["disaster_events"][-3:] if state["disaster_events"] else [],
    }


@mcp.tool()
def rescue_survivor(drone_id: str, survivor_id: int) -> dict:
    """Rescue a survivor at the drone's current position.
    The drone must be on the same cell as the survivor. The survivor must be
    found (scanned), alive, and not already rescued. Marks the survivor as rescued
    so their health stops draining. Call this AFTER moving to a found survivor's cell."""
    model = get_model()
    drone, err = _get_drone(drone_id)
    if err:
        return err

    # Find the survivor
    target = None
    for s in model.survivors:
        if s.unique_id == survivor_id:
            target = s
            break
    if target is None:
        return {"error": f"Unknown survivor_id {survivor_id}. Check discovered survivors first."}

    if not drone.connected:
        return {"error": f"Drone '{drone_id}' is disconnected (blackout). Cannot command — it is operating autonomously."}
    return drone.rescue_survivor(target)


# ── Innovation Tools (6) ──────────────────────────────────────────────

@mcp.tool()
def get_pheromone_map() -> dict:
    """Get all 3 pheromone layers as 12x12 grids.
    - scanned (repulsive): areas already scanned, avoid re-scanning
    - survivor_nearby (attractive): probable survivor locations, converge here
    - danger (strongly repulsive): aftershock/flood zones, stay away
    All pheromones decay by 0.9x per step. Indexed as layer[y][x]."""
    model = get_model()
    return {
        "scanned": model.pheromone_scanned.tolist(),
        "survivor_nearby": model.pheromone_survivor_nearby.tolist(),
        "danger": model.pheromone_danger.tolist(),
    }


@mcp.tool()
def get_disaster_events() -> list[dict]:
    """Get the full list of disaster events that have occurred during the mission.
    Events include aftershocks (OPEN→DEBRIS), rising water (floods cells), and blackouts.
    Use this to understand the evolving threat landscape."""
    model = get_model()
    return model.disaster_events


@mcp.tool()
def assess_survivor(survivor_id: int) -> dict:
    """Assess a specific survivor's condition and return a triage recommendation.
    Triage levels: IMMEDIATE (critical+health<30%), URGENT (critical+30-60%),
    MEDIUM-HIGH (moderate+health<40%), LOW (stable).
    Use this to prioritize rescue operations."""
    model = get_model()

    survivor = None
    for s in model.survivors:
        if s.unique_id == survivor_id:
            survivor = s
            break

    if survivor is None:
        return {"error": f"Unknown survivor_id {survivor_id}. Check discovered survivors first."}

    if not survivor.found:
        return {"error": f"Survivor #{survivor_id} has not been found yet. Scan the area first."}

    # Triage logic
    health = survivor.health
    severity = survivor.severity

    if not survivor.alive:
        triage = "DECEASED"
    elif survivor.rescued:
        triage = "RESCUED"
    elif severity == "CRITICAL" and health < 0.3:
        triage = "IMMEDIATE"
    elif severity == "CRITICAL" and health < 0.6:
        triage = "URGENT"
    elif severity == "MODERATE" and health < 0.4:
        triage = "MEDIUM-HIGH"
    elif severity == "CRITICAL":
        triage = "URGENT"
    elif severity == "MODERATE":
        triage = "MEDIUM"
    else:
        triage = "LOW"

    # Estimate steps until death
    drain_rate = {"CRITICAL": 0.05, "MODERATE": 0.02, "STABLE": 0.01}.get(severity, 0.01)
    steps_remaining = int(health / drain_rate) if drain_rate > 0 and survivor.alive else None

    return {
        "survivor_id": survivor_id,
        "position": list(survivor.pos) if survivor.pos else None,
        "severity": severity,
        "health": round(health, 2),
        "alive": survivor.alive,
        "found": survivor.found,
        "rescued": survivor.rescued,
        "triage": triage,
        "estimated_steps_until_death": steps_remaining,
        "recommendation": (
            f"Triage level: {triage}. "
            f"{'Already rescued.' if survivor.rescued else ''}"
            f"{'Already deceased.' if not survivor.alive else ''}"
            f"{'Approx ' + str(steps_remaining) + ' steps until death.' if steps_remaining and survivor.alive and not survivor.rescued else ''}"
        ),
    }


@mcp.tool()
def deploy_as_relay(drone_id: str) -> dict:
    """Convert a drone into a stationary relay node with extended comm range (6 cells).
    The drone stops moving and scanning, but extends mesh network coverage.
    Useful for maintaining connectivity in blackout zones or bridging coverage gaps.
    WARNING: This is irreversible — the drone can no longer move or scan."""
    drone, err = _get_drone(drone_id)
    if err:
        return err
    if not drone.connected:
        return {"error": f"Drone '{drone_id}' is disconnected (blackout). Cannot command — it is operating autonomously."}
    return drone.deploy_as_relay()


@mcp.tool()
def get_network_resilience() -> dict:
    """Analyze the mesh network's resilience and suggest improvements.
    Returns connectivity_ratio, critical_nodes (whose loss disconnects others),
    coverage_gaps (grid cells not reachable by any drone), and relay_suggestions.
    Use this to decide whether to deploy relay nodes or reposition drones."""
    model = get_model()
    return _get_network_resilience(model.drones, base_pos=BASE_POS)


@mcp.tool()
def coordinate_swarm(assignments: dict = None) -> dict:
    """Divide the grid into sectors and assign drones for efficient coverage.
    If assignments provided: {drone_id: [x, y, width, height]} for manual sector assignment.
    If no assignments: auto-divide the 12x12 grid into quadrants among active drones.
    Drones will prefer scanning within their assigned sector during autonomous navigation."""
    model = get_model()
    return model.coordinate_swarm(assignments)


# ── Performance / Adaptive Learning Tools ─────────────────────────────

@mcp.tool()
def get_performance_score() -> dict:
    """Get the current mission performance score and breakdown.
    Use this to evaluate how effective your strategy is mid-mission.
    Returns total score, letter grade, rescue points, speed bonus, coverage bonus,
    death penalty, efficiency bonus, and mission progress percentage.
    Call this at least once mid-mission to assess and adapt your strategy."""
    model = get_model()
    score = model.compute_score()
    max_steps = int(os.environ.get("MAX_MISSION_STEPS", "50"))
    progress = round(model.mission_step / max_steps * 100, 1)
    return {
        **score,
        "mission_step": model.mission_step,
        "max_steps": max_steps,
        "mission_progress_pct": progress,
        "steps_remaining": max_steps - model.mission_step,
        "performance_grade": score["grade"],
    }


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
