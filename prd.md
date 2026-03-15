# PRD: First Responder of the Future — Decentralised Swarm Intelligence

## Project Overview

Build a **self-healing rescue drone swarm simulation** where an autonomous AI Command Agent orchestrates a fleet of drones to find survivors in a disaster zone — with zero cloud connectivity. All communication between the Agent (LLM) and Drones (simulation) flows through **Model Context Protocol (MCP)**.

What makes this system genuinely decentralised: drones are **not puppets**. The LLM Commander sets high-level strategy, but every drone carries local autonomy rules — continuing to scan, avoid danger, and follow pheromone gradients even when communication is severed. The simulation is alive: survivors deteriorate, aftershocks reshape terrain, and rising water forces real-time triage decisions that showcase the LLM's reasoning depth.

**Hackathon Track:** Agentic AI (Decentralised Swarm Intelligence)
**SDG Alignment:** SDG 9 (Industry, Innovation, Infrastructure) + SDG 3 (Good Health & Well-being)

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Simulation Engine | **Mesa 3** (Python) | 2D grid world, drone agents, survivor placement, PropertyLayers for heatmap + pheromones |
| MCP Server | **FastMCP** (from `mcp` Python SDK) | Exposes drone tools over Streamable HTTP at `http://localhost:8000/mcp` |
| Agent Brain | **LangChain + LangGraph** + `langchain-mcp-adapters` | LLM-powered Command Agent with chain-of-thought reasoning |
| LLM Provider | **OpenAI GPT-5 mini** (`gpt-5-mini`) via `langchain-openai` |
| Frontend Dashboard | **Next.js 14+ (App Router)** + React + TypeScript + Tailwind CSS | Real-time visualization via SSE streaming |
| API Bridge | **FastAPI** | SSE streaming endpoint + REST endpoints for frontend |

### Python Dependencies

```
pip install "mcp[cli]" mesa langchain-mcp-adapters langgraph langchain-openai langchain fastapi uvicorn numpy
```

### Node Dependencies (frontend)

```
npx create-next-app@latest dashboard --typescript --tailwind --app --eslint
```

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Next.js Dashboard                              │
│  Grid Map | Heatmap | Drone Status | Reasoning Log | Timeline Slider  │
│  🔊 Voice Narration (SpeechSynthesis) | SSE-Powered Real-Time Updates │
└─────────────────────────────┬─────────────────────────────────────────┘
                              │ SSE stream (GET /api/stream)
                              │ REST (GET /api/state, /api/logs, /api/history)
                              ▼
┌───────────────────────────────────────────────────────────────────────┐
│                         FastAPI Bridge                                │
│      SSE StreamingResponse | State snapshots | Mission history        │
└─────────────────────────────┬─────────────────────────────────────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼                             ▼
┌──────────────────────┐         ┌──────────────────────────────────┐
│   LangGraph Agent    │◄───────►│      MCP Server (FastMCP)        │
│   (Command Agent)    │  MCP    │  17 Tools: discover, move, scan, │
│   Strategic Reasoning│  HTTP   │  battery, heatmap, simulate,     │
│   + Triage Decisions │         │  pheromones, triage, swarm,      │
│                      │         │  relay, resilience, disaster...  │
└──────────────────────┘         └──────────────┬───────────────────┘
                                                │ direct Python calls
                                                ▼
                              ┌──────────────────────────────────────┐
                              │       Mesa Simulation Engine          │
                              │                                      │
                              │  ┌─ Grid World (12x12)               │
                              │  ├─ DroneAgents (local autonomy)     │
                              │  │   ├─ Follow pheromone gradients   │
                              │  │   ├─ Auto-return on low battery   │
                              │  │   └─ Continue scanning in blackout│
                              │  ├─ SurvivorAgents (health decay)    │
                              │  ├─ PropertyLayers                   │
                              │  │   ├─ Bayesian heatmap             │
                              │  │   ├─ "scanned" pheromone          │
                              │  │   ├─ "survivor_nearby" pheromone  │
                              │  │   └─ "danger" pheromone            │
                              │  ├─ Dynamic Disasters                │
                              │  │   ├─ Aftershock terrain changes   │
                              │  │   └─ Rising water expansion       │
                              │  └─ Mesh Network + Blackouts         │
                              └──────────────────────────────────────┘

Two-Tier Intelligence Flow:
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│   TIER 1: LLM Commander (Strategic)                                  │
│   ┌──────────────────────────────────────────────────────┐          │
│   │  • Sets high-level strategy (sector assignments)      │          │
│   │  • Triage reasoning (who to save first)               │          │
│   │  • Digital twin planning (simulate before commit)     │          │
│   │  • Reads pheromone map for strategic decisions         │          │
│   │  • Coordinates swarm-level patterns                   │          │
│   └──────────────────────┬───────────────────────────────┘          │
│                          │ MCP tool calls                            │
│                          ▼                                           │
│   TIER 2: Drone Local Autonomy (Tactical)                           │
│   ┌──────────────────────────────────────────────────────┐          │
│   │  • During blackout: continue scanning assigned sector │          │
│   │  • Auto-return when battery < 15%                     │          │
│   │  • Deposit & follow pheromone gradients               │          │
│   │  • Avoid danger pheromone zones                       │          │
│   │  • Attempt mesh relay to reconnect                    │          │
│   │  • Buffer findings for later sync                     │          │
│   └──────────────────────────────────────────────────────┘          │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
project-root/
├── README.md
├── prd.md
├── requirements.txt
│
├── simulation/
│   ├── __init__.py
│   ├── model.py              # Mesa DisasterModel (grid, survivors, heatmap, pheromones, disasters)
│   ├── agents.py             # DroneAgent (with local autonomy), SurvivorAgent (health decay)
│   └── mesh_network.py       # Communication range + blackout logic
│
├── mcp_server/
│   ├── __init__.py
│   └── server.py             # FastMCP server with all 17 @mcp.tool() definitions
│
├── agent/
│   ├── __init__.py
│   ├── graph.py              # LangGraph StateGraph definition
│   ├── prompts.py            # System prompt for Command Agent (with triage rules)
│   └── runner.py             # Entry point: connects to MCP, runs agent loop
│
├── api/
│   ├── __init__.py
│   └── bridge.py             # FastAPI app: SSE streaming + REST endpoints + mission history
│
├── dashboard/                # Next.js app (created via create-next-app)
│   ├── app/
│   │   ├── page.tsx          # Main dashboard page
│   │   └── layout.tsx
│   ├── components/
│   │   ├── GridMap.tsx        # 2D grid with drone positions + heatmap + scan pulse animations
│   │   ├── DronePanel.tsx     # Battery gauges, status per drone, health bars for found survivors
│   │   ├── MeshGraph.tsx      # Network topology visualization
│   │   ├── ReasoningLog.tsx   # Scrolling agent chain-of-thought log + voice narration
│   │   ├── ControlPanel.tsx   # Trigger blackout, start/pause, step, voice toggle
│   │   └── TimelineSlider.tsx # Mission replay scrubber (rewind to any step)
│   ├── lib/
│   │   └── api.ts            # SSE client (EventSource) + REST fetch helpers
│   ├── package.json
│   └── tailwind.config.ts
│
├── scripts/
│   ├── run_all.sh            # Starts MCP server, agent, API bridge, and frontend
│   └── demo.py               # Scripted demo sequence for presentation
│
└── logs/
    └── mission_log.json      # Persisted agent reasoning + tool calls
```

---

## Simulation Engine (Mesa)

### File: `simulation/model.py`

**Class: `DisasterModel(mesa.Model)`**

- **Grid:** `mesa.spaces.MultiGrid(width=12, height=12, torus=False)`
- **Survivors:** 8–12 randomly placed, hidden from drones until scanned. Each survivor has `found`, `rescued`, `health`, and `severity` properties.
- **Drones:** 4–5 `DroneAgent` instances, start at base position `(0, 0)`.
- **Terrain types:** Store as a separate grid — `BUILDING`, `ROAD`, `OPEN`, `WATER`, `DEBRIS`. Water and Debris cells are impassable (Debris can be created by aftershocks).

#### Bayesian Heatmap (PropertyLayer)
A `numpy` 12x12 array representing Bayesian prior probability of survivor presence at each cell. Initialize with:
- Cells near "buildings" (predefined coordinates): prior = 0.7
- Cells near "roads" (predefined row/column): prior = 0.5
- Open terrain: prior = 0.3

#### Pheromone Layers (Innovation 2: Stigmergy)

Three additional `PropertyLayer` instances for bio-inspired swarm coordination:

| Pheromone Layer | Behavior | Deposited By | Effect on Drones |
|---|---|---|---|
| `scanned` | Repulsive — drones avoid re-scanning | DroneAgent after scanning a cell | Local autonomy steers away from high values |
| `survivor_nearby` | Attractive — draws drones toward likely finds | DroneAgent when survivor detected | Autonomous drones gravitate toward high values |
| `danger` | Repulsive — drones avoid hazardous areas | Model when aftershock/water event occurs | Autonomous drones steer away; agent reads for strategy |

**All pheromones decay by 0.9x per step** (so a pheromone of 1.0 becomes 0.35 after 10 steps — stale information fades).

Pheromone deposit rules:
- On successful scan (no survivor): deposit `scanned = 1.0` on scanned cells
- On survivor detection: deposit `survivor_nearby = 1.0` on survivor cell, `0.5` on adjacent cells
- On aftershock/rising water: deposit `danger = 1.0` on affected cells

#### Dynamic Disaster Progression (Innovation 3)

**Step logic:** Each `model.step()`:
1. Drains 1 battery from all active drones
2. Decays all pheromone layers by 0.9x
3. Drains survivor health based on severity level
4. Every ~10 steps: **Aftershock event** — 2-3 random `OPEN` cells become `DEBRIS` (impassable). If a drone is on an affected cell, it takes 5 battery damage and must relocate.
5. Every ~15 steps: **Rising water** — all `WATER` cells expand by 1 cell in a random direction. If water reaches a survivor, they are lost immediately.
6. Record state snapshot for mission replay history

**Disaster event log:** The model maintains a `disaster_events: list[dict]` recording all aftershocks and water expansions with step number, affected cells, and consequences (e.g., "Survivor at (7,3) lost to rising water").

---

### File: `simulation/agents.py`

**Class: `DroneAgent(mesa.Agent)`**

Properties:
- `drone_id: str` — unique identifier (e.g., "drone_alpha", "drone_bravo")
- `position: tuple[int, int]` — current (x, y) on grid
- `battery: int` — starts at 100, drains 1 per step, 2 per move, 3 per scan
- `status: str` — one of `"active"`, `"returning"`, `"charging"`, `"offline"`, `"relay"`
- `connected: bool` — whether drone can communicate with command
- `comm_range: int` — default 4 cells; drones within range of each other can relay
- `findings_buffer: list[dict]` — stores scan results when disconnected
- `scan_radius: int` — default 1 (scans current cell + adjacent)
- `assigned_sector: tuple[int, int, int, int] | None` — (x_min, y_min, x_max, y_max) assigned by commander
- `is_relay: bool` — whether drone has been sacrificed as a communication relay (stationary)

Methods:
- `move_to(x, y)` — update position, drain battery by 2
- `thermal_scan()` — check for survivors in scan_radius, return results, drain battery by 3
- `return_to_base()` — set status to "returning", pathfind to (0,0)
- `charge()` — if at base, increment battery by 10 per step until 100
- `deploy_as_relay()` — set `is_relay = True`, `status = "relay"`, drone becomes stationary comm node

#### Local Autonomy Methods (Innovation 1: Two-Tier Intelligence)

These methods execute automatically during `model.step()` when the drone is **disconnected** (blackout) or has no pending commander orders:

- `autonomous_step()` — master autonomy method called each step when disconnected:
  1. **Low battery check:** If battery < 15%, auto-return to base regardless of other rules
  2. **Sector scanning:** If `assigned_sector` is set, continue systematic scan of unscanned cells within sector
  3. **Pheromone-guided movement:** Move toward highest `survivor_nearby` pheromone, away from `scanned` and `danger` pheromones. Decision formula: `score(cell) = survivor_nearby[cell] - 0.5 * scanned[cell] - 2.0 * danger[cell]`
  4. **Mesh relay attempt:** If disconnected, move toward nearest connected drone (if known from last topology update) to attempt relay reconnection
  5. **Buffer findings:** All scan results go to `findings_buffer` for later sync

- `deposit_pheromones()` — called after every scan or movement:
  - After scan: deposit `scanned` pheromone on scanned cells
  - After finding survivor: deposit `survivor_nearby` pheromone

- `read_local_pheromones() -> dict` — returns pheromone values for cells within scan_radius (used by `autonomous_step`)

**Class: `SurvivorAgent(mesa.Agent)` (Innovation 3 & 4: Dynamic + Triage)**

Properties:
- `position: tuple[int, int]`
- `found: bool` — initially False
- `rescued: bool` — initially False
- `health: float` — starts at 1.0, drains per step based on severity
- `severity: str` — one of `"CRITICAL"`, `"MODERATE"`, `"STABLE"`
- `alive: bool` — True until health reaches 0.0

Severity drain rates (per step):
| Severity | Drain/Step | Steps Until Death | Urgency |
|---|---|---|---|
| CRITICAL | 0.05 | ~20 steps | Must rescue within minutes |
| MODERATE | 0.02 | ~50 steps | Can wait, but not forever |
| STABLE | 0.01 | ~100 steps | Low priority |

Step logic:
```python
def step(self):
    if not self.alive:
        return
    drain = {"CRITICAL": 0.05, "MODERATE": 0.02, "STABLE": 0.01}[self.severity]
    self.health = max(0.0, self.health - drain)
    if self.health <= 0.0:
        self.alive = False
        # Log: "Survivor at (x,y) has died — severity was {severity}"
```

When a survivor dies, it's a **permanent failure** — the mission score drops. This creates real stakes and forces the agent to reason about triage.

---

### File: `simulation/mesh_network.py`

**Functions:**
- `compute_mesh_topology(drones: list[DroneAgent]) -> dict[str, list[str]]` — returns adjacency list of which drones can communicate (within `comm_range` of each other). Relay drones (`is_relay=True`) count as nodes with extended range (6 cells instead of 4).
- `apply_blackout(model, zone_center: tuple, radius: int)` — sets `connected = False` for all drones within radius of zone_center
- `check_relay_path(drone: DroneAgent, base: tuple, all_drones: list) -> bool` — BFS/DFS to check if drone has a relay path back to base through other connected drones
- `sync_drone(drone: DroneAgent) -> list[dict]` — flush findings_buffer when connection is restored
- `get_network_resilience(drones: list[DroneAgent]) -> dict` — returns network analysis: connectivity ratio, critical nodes (single points of failure), coverage gaps (grid areas with no comm coverage), recommended relay positions

---

## MCP Server

### File: `mcp_server/server.py`

Use `FastMCP` from the official `mcp` Python SDK. The server holds a reference to the `DisasterModel` instance.

**Transport:** Streamable HTTP (`mcp.run(transport="streamable-http")`)
**Default URL:** `http://localhost:8000/mcp`

### Tools to Implement (17 Total)

Each tool is a decorated function using `@mcp.tool()`:

#### Core Tools (required by case study)

1. **`discover_drones() -> dict`**
   - Returns list of all active drones with: id, position, battery, status, connected, is_relay, assigned_sector
   - The agent must NOT have hard-coded drone IDs — it discovers them via this tool
   - This is the first tool the agent must call in every mission

2. **`move_to(drone_id: str, x: int, y: int) -> dict`**
   - Moves specified drone to target coordinates
   - Returns: new position, battery after move, status
   - Validates: target is within grid bounds, not a WATER or DEBRIS cell, drone has sufficient battery
   - Error if drone_id not found, drone is offline, or drone is in relay mode

3. **`thermal_scan(drone_id: str) -> dict`**
   - Scans current position + adjacent cells for heat signatures
   - Returns: list of detected survivors (position, signal_strength, severity, health), cells_scanned, battery_remaining
   - Updates Bayesian heatmap: positive hit increases adjacent cell probabilities, negative decreases
   - Deposits pheromones: `scanned` on all scanned cells, `survivor_nearby` if survivor found
   - If drone is disconnected, results go to findings_buffer instead of immediate return

4. **`get_battery_status(drone_id: str) -> dict`**
   - Returns: battery_level, estimated_moves_remaining, status, position, can_return_to_base (bool)

#### Strategic Tools

5. **`get_priority_map() -> dict`**
   - Returns the full 12x12 Bayesian probability heatmap as a 2D array
   - Also returns: top 5 highest-probability unscanned cells as recommended targets
   - The agent uses this to make intelligent search decisions

6. **`simulate_mission(drone_id: str, target_x: int, target_y: int) -> dict`**
   - **Digital twin / Monte Carlo planning**
   - Predicts WITHOUT moving the real drone: battery cost to reach target, estimated time (steps), probability of finding survivors at target (from heatmap), risk assessment (will drone have enough battery to return to base?)
   - Returns: predicted_battery_at_arrival, can_return_to_base (bool), survivor_probability, recommended (bool)

7. **`sync_findings(drone_id: str) -> dict`**
   - Flushes the findings_buffer of a reconnected drone
   - Returns: list of buffered scan results with timestamps
   - Updates the heatmap with the buffered data
   - Only works if drone.connected is True

8. **`trigger_blackout(zone_x: int, zone_y: int, radius: int) -> dict`**
   - Simulates communication failure in a zone
   - Sets affected drones to connected=False
   - Returns: list of affected drone IDs, zone bounds
   - Used for demo purposes and to test self-healing

9. **`recall_drone(drone_id: str) -> dict`**
   - Commands drone to return to base (0,0) for charging
   - Sets status to "returning"
   - Returns: estimated steps to reach base, current battery

10. **`get_mission_summary() -> dict`**
    - Returns: total survivors found, total survivors remaining, survivors lost (health=0), coverage percentage (cells scanned / total), drone fleet status, mission elapsed steps, mesh network topology, disaster events count

11. **`advance_simulation(steps: int = 1) -> dict`**
    - Advances the Mesa model by N steps (battery drain, charging, movement, health decay, pheromone decay, possible aftershock/water events)
    - Returns: updated fleet status, any drones that hit 0 battery, any disaster events that occurred, any survivors that died

#### Innovation Tools (6 new differentiators)

12. **`get_pheromone_map() -> dict`**
    - Returns all three pheromone layers as 12x12 2D arrays: `scanned`, `survivor_nearby`, `danger`
    - Also returns: suggested exploration targets (cells with low `scanned` + high heatmap probability)
    - The agent uses this for strategic planning; drones use it locally for autonomous navigation

13. **`get_disaster_events() -> dict`**
    - Returns the recent disaster event log: aftershocks (which cells became DEBRIS), rising water (which cells flooded), survivor casualties
    - Includes: current terrain map reflecting all changes, predicted next event window
    - Agent uses this to re-route drones away from danger and prioritize threatened survivors

14. **`assess_survivor(drone_id: str) -> dict`**
    - Returns triage assessment for the nearest found (but not rescued) survivor within scan range of specified drone
    - Data: survivor position, health percentage, severity level, estimated steps until death, distance from drone, rescue priority score
    - Priority score formula: `priority = (1.0 - health) * severity_weight * (1.0 / distance)` where CRITICAL=3, MODERATE=2, STABLE=1
    - Returns null if no found survivors are nearby
    - This tool exists so the agent can do **explicit triage reasoning** in its chain-of-thought

15. **`deploy_as_relay(drone_id: str, x: int, y: int) -> dict`**
    - Moves specified drone to (x, y) and converts it to a stationary communication relay
    - Sets `is_relay = True`, `status = "relay"`, `comm_range = 6` (extended)
    - Returns: relay position, drones now within extended range, network improvement metrics
    - Trade-off: sacrifices a searcher to improve network resilience — agent must reason about whether the network benefit outweighs losing a search drone

16. **`get_network_resilience() -> dict`**
    - Returns network analysis: connectivity ratio (connected/total drones), critical relay nodes, coverage gaps (grid quadrants with no comm coverage), single points of failure
    - Includes: recommended positions for relay deployment to maximize coverage
    - Agent uses this proactively before/after blackouts to assess swarm health

17. **`coordinate_swarm(sector: str) -> dict`**
    - Assigns all available drones to a sector-based search pattern
    - Sector format: `"NW"`, `"NE"`, `"SW"`, `"SE"`, or `"ALL"`
    - Divides the 12x12 grid into quadrants (6x6 each) and assigns `assigned_sector` to each drone
    - Returns: drone-to-sector mapping, estimated coverage time, pheromone summary per sector
    - Drones with `assigned_sector` will continue scanning that sector autonomously during blackouts

---

## Agent Brain (LangGraph)

### File: `agent/prompts.py`

```python
SYSTEM_PROMPT = """You are the Autonomous Rescue Command Agent deployed in a disaster zone in the ASEAN region after a Category 5 typhoon. All terrestrial communication is down. You command a fleet of rescue drones via MCP tools.

## YOUR MISSION
Find and locate all survivors in the 12x12 grid disaster zone using your drone fleet. Survivors are DYING — their health drains every step. You must find and prioritize the most critical survivors first.

## CRITICAL RULES
1. ALWAYS call discover_drones() first to see your available fleet. Never assume drone IDs.
2. ALWAYS explain your reasoning BEFORE executing any tool call. Use chain-of-thought.
3. Use get_priority_map() and get_pheromone_map() to make data-driven decisions about where to scan next.
4. Monitor battery levels — recall any drone below 20% battery to base (0,0).
5. If a drone is disconnected, do NOT send it commands. It will continue autonomously using pheromone gradients. Wait for reconnection or use sync_findings().
6. Use simulate_mission() before committing to long-distance moves to verify feasibility.
7. After each scan, reassess the heatmap and adjust your plan.
8. Coordinate drones to avoid scanning the same area twice — use coordinate_swarm() for sector assignments.
9. Check get_disaster_events() regularly — aftershocks and rising water change the terrain dynamically.
10. Use get_network_resilience() before and after blackouts to assess communication health.

## TRIAGE PROTOCOL (MOST IMPORTANT)
When multiple survivors are found, you MUST triage. Use assess_survivor() and reason through this decision tree:

1. **CRITICAL survivors with health < 30%** — assign nearest drone IMMEDIATELY, interrupt other tasks
2. **CRITICAL survivors with health 30-60%** — high priority, assign within 2-3 steps
3. **MODERATE survivors with health < 40%** — medium-high priority
4. **STABLE survivors** — can wait, assign when convenient
5. If two survivors are equally urgent, prioritize the one CLOSER to a drone (minimize travel cost)
6. If a CRITICAL survivor will die before any drone can reach them — acknowledge the loss, don't waste resources

Show your triage reasoning explicitly:
"TRIAGE: Survivor A at (3,7) is CRITICAL with 25% health (~5 steps to death). Survivor B at (9,2) is MODERATE with 80% health (~40 steps). Drone Bravo is 3 steps from A, 6 steps from B. DECISION: Assign Bravo to A — every step counts."

## RELAY SACRIFICE DECISION
When network resilience drops below 50% connectivity, consider deploying a drone as a relay:
- Use get_network_resilience() to identify coverage gaps
- Weigh: is the network benefit worth losing a search drone?
- Best candidate: drone with lowest battery (limited search value anyway)
- Show reasoning: "RELAY DECISION: Connectivity at 40%. Drone Delta has only 22% battery — limited search remaining. Deploying at (6,6) bridges the gap between NE and SW sectors."

## REASONING FORMAT
Before each action, explain like this:
"REASONING: Drone Alpha has 72% battery at (3,4). The heatmap shows cell (6,7) has 0.83 probability — highest unscanned. Pheromone map shows no 'scanned' pheromone there (fresh territory). simulate_mission shows it can reach and return. Assigning Drone Alpha to (6,7)."

Then execute the tool calls.

## DYNAMIC EVENTS
The disaster zone is ALIVE. Watch for:
- Aftershock alerts: terrain changes, re-route drones away from new DEBRIS
- Rising water: survivors in threatened areas become highest priority regardless of severity
- Survivor death: acknowledge losses, don't dwell — refocus on saveable survivors

## VICTORY CONDITION
Mission succeeds when all LIVING survivors are located. Minimize steps, battery usage, and survivor casualties. Every death is a failure — but strategic triage means accepting some losses to save many.
"""
```

### File: `agent/graph.py`

Build a LangGraph `StateGraph` with `MessagesState`:

```
Nodes:
  - "agent": calls the LLM with tools bound, uses SYSTEM_PROMPT
  - "tools": ToolNode that executes MCP tool calls

Edges:
  - START -> "agent"
  - "agent" -> tools_condition (if tool call) -> "tools"
  - "agent" -> END (if no tool call, mission complete)
  - "tools" -> "agent" (loop back for next reasoning step)
```

Use `langchain-mcp-adapters` `MultiServerMCPClient` to load tools from the MCP server:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.chat_models import init_chat_model

client = MultiServerMCPClient({
    "swarm": {
        "url": "http://localhost:8000/mcp",
        "transport": "http",
    }
})
tools = await client.get_tools()
model = init_chat_model("openai:gpt-5-mini")
```

### File: `agent/runner.py`

Entry point that:
1. Connects to MCP server
2. Builds the LangGraph agent
3. Invokes with initial message: "Begin search and rescue mission. Discover your fleet and plan your approach."
4. Streams agent reasoning + tool calls to `logs/mission_log.json`
5. Publishes each reasoning entry + state change to the FastAPI bridge (for SSE streaming)
6. Loops until agent declares mission complete or max steps reached (50)

---

## API Bridge (FastAPI)

### File: `api/bridge.py`

Serves current simulation state to the frontend dashboard. **Primary transport is SSE** (Innovation 5) for real-time updates; REST endpoints remain as fallback.

#### SSE Streaming Endpoint (Innovation 5)

- **`GET /api/stream`** — Server-Sent Events endpoint using `StreamingResponse`:
  ```python
  from fastapi.responses import StreamingResponse

  @app.get("/api/stream")
  async def stream():
      async def event_generator():
          while True:
              # Yield state update on every simulation step
              state = get_current_state()
              yield f"event: state\ndata: {json.dumps(state)}\n\n"
              # Yield new reasoning log entries
              new_logs = get_new_logs(since=last_sent)
              if new_logs:
                  yield f"event: logs\ndata: {json.dumps(new_logs)}\n\n"
              # Yield disaster events
              events = get_new_disaster_events()
              if events:
                  yield f"event: disaster\ndata: {json.dumps(events)}\n\n"
              await asyncio.sleep(0.5)
      return StreamingResponse(event_generator(), media_type="text/event-stream")
  ```

  SSE event types:
  | Event | Data | Purpose |
  |---|---|---|
  | `state` | Full simulation state (drones, terrain, heatmap, pheromones) | Grid + panel updates |
  | `logs` | New agent reasoning entries | Reasoning log + voice narration |
  | `disaster` | Aftershock/water/death events | Alert flashes + terrain updates |
  | `blackout` | Blackout zone info | Red flash overlay on dashboard |

#### REST Endpoints (fallback)

- `GET /api/state` — returns full simulation state (same schema as SSE `state` event):
  ```json
  {
    "grid": { "width": 12, "height": 12 },
    "terrain": [[...]],
    "drones": [
      { "id": "drone_alpha", "position": [3, 4], "battery": 72, "status": "active", "connected": true, "is_relay": false, "assigned_sector": "NE" }
    ],
    "survivors": [
      { "position": [6, 7], "found": true, "rescued": false, "health": 0.65, "severity": "CRITICAL", "alive": true }
    ],
    "heatmap": [[0.3, 0.5, ...], ...],
    "pheromones": {
      "scanned": [[...]],
      "survivor_nearby": [[...]],
      "danger": [[...]]
    },
    "mesh_topology": { "drone_alpha": ["drone_bravo"], "drone_bravo": ["drone_alpha"] },
    "scanned_cells": [[3,4], [3,5], ...],
    "mission_stats": { "found": 3, "total": 8, "alive": 7, "dead": 1, "coverage": 0.45, "steps": 12 },
    "disaster_events": [
      { "step": 10, "type": "aftershock", "cells_affected": [[4,5], [7,2]], "description": "Aftershock: 2 cells became debris" }
    ]
  }
  ```
  Note: Only return survivor positions for survivors where `found=True`. Hidden survivors are not exposed.

- `GET /api/logs` — returns array of agent reasoning entries:
  ```json
  [
    {
      "step": 1,
      "type": "reasoning",
      "content": "REASONING: Starting mission. Calling discover_drones()...",
      "timestamp": "2025-03-15T10:00:00Z",
      "is_critical": false
    },
    {
      "step": 3,
      "type": "triage",
      "content": "TRIAGE: Survivor at (3,7) is CRITICAL with 25% health. Assigning Drone Bravo immediately.",
      "timestamp": "2025-03-15T10:00:05Z",
      "is_critical": true
    }
  ]
  ```
  Entries with `is_critical: true` trigger voice narration on the frontend.

- `GET /api/history` — **(Innovation 7: Mission Replay)** returns array of complete state snapshots, one per simulation step:
  ```json
  {
    "total_steps": 24,
    "snapshots": [
      { "step": 0, "state": { /* full state at step 0 */ } },
      { "step": 1, "state": { /* full state at step 1 */ } },
      ...
    ]
  }
  ```
  Used by TimelineSlider component to enable judges to rewind to any point in the mission.

- `POST /api/blackout` — triggers a blackout event: `{ "zone_x": 5, "zone_y": 5, "radius": 3 }`
- `POST /api/step` — manually advance simulation by N steps
- `POST /api/start` — begins autonomous agent mission
- `GET /api/mesh` — returns current mesh network topology as adjacency list

**Run:** `uvicorn api.bridge:app --port 8001`

---

## Frontend Dashboard (Next.js)

### Main Page Layout (`app/page.tsx`)

4-panel layout using CSS Grid + timeline slider at bottom:

```
┌──────────────────────────────────┬──────────────────┐
│                                  │   Drone Panel    │
│      Grid Map + Heatmap          │   (battery bars, │
│      (main visualization)        │    status, pos,  │
│      CSS transitions on moves    │    survivor HP)  │
│      Scan pulse animations       │                  │
├──────────────────────────────────┼──────────────────┤
│    Agent Reasoning Log           │  Control Panel   │
│    (scrolling text log)          │  (buttons/toggles│
│    + Voice narration indicator   │   blackout, step,│
│                                  │   voice on/off)  │
├──────────────────────────────────┴──────────────────┤
│           Timeline Slider (Mission Replay)           │
│   |◄──●─────────────────────────────────────────►|   │
│   Step 0              Step 12              Step 24   │
└──────────────────────────────────────────────────────┘
```

### Data Connection: SSE (`lib/api.ts`)

```typescript
// Primary: SSE for real-time updates
export function connectSSE(onState: (s: State) => void, onLogs: (l: LogEntry[]) => void, onDisaster: (d: DisasterEvent) => void) {
  const es = new EventSource("http://localhost:8001/api/stream");
  es.addEventListener("state", (e) => onState(JSON.parse(e.data)));
  es.addEventListener("logs", (e) => onLogs(JSON.parse(e.data)));
  es.addEventListener("disaster", (e) => onDisaster(JSON.parse(e.data)));
  es.addEventListener("blackout", (e) => {
    // Trigger red flash overlay
    document.body.classList.add("blackout-flash");
    setTimeout(() => document.body.classList.remove("blackout-flash"), 2000);
  });
  return es;
}

// Fallback: REST polling
export async function fetchState(): Promise<State> { ... }
export async function fetchLogs(): Promise<LogEntry[]> { ... }
export async function fetchHistory(): Promise<HistoryData> { ... }
```

### Components

#### `GridMap.tsx`
- 12x12 grid rendered as colored cells
- **Terrain colors:** Building = gray, Road = light gray, Open = green, Water = blue, Debris = dark brown (new)
- **Heatmap overlay:** Semi-transparent red gradient based on probability values (0.0 = transparent, 1.0 = solid red)
- **Pheromone overlay (toggle):** `scanned` = blue tint, `survivor_nearby` = gold glow, `danger` = red pulse
- **Drone markers:** Colored circles with drone ID label, different color per drone. **CSS transitions** on position changes for smooth movement animation (transition: transform 0.3s ease)
- **Relay drones:** Antenna icon instead of circle, with radiating comm range rings
- **Found survivors:** Yellow star icon on cells where survivors are found, with **health bar** below (green→yellow→red)
- **Dead survivors:** Gray X mark (permanent failure indicator)
- **Scanned cells:** Subtle border or checkmark to show already-scanned areas, opacity fading based on `scanned` pheromone (recently scanned = bright, old = faded)
- **Blackout zone:** Dark overlay on cells affected by communication blackout, **red flash animation** on blackout trigger
- **Scan pulse animation:** When a drone scans, a circular pulse radiates outward from the drone (CSS @keyframes, 0.5s)
- **Aftershock animation:** Brief shake animation on the grid when aftershock occurs
- **Rising water animation:** Blue cells expand with a wave-like CSS transition
- Data source: SSE `state` events (replaces REST polling)

#### `DronePanel.tsx`
- Card per drone showing:
  - ID and color (matching grid marker)
  - Battery bar (green > 50%, yellow 20-50%, red < 20%) — **animated width transitions**
  - Status badge (active/returning/charging/offline/**relay** — new)
  - Connected indicator (green dot = connected, red dot = disconnected)
  - Current position coordinates
  - Assigned sector indicator (NW/NE/SW/SE if set)
- **Found survivor health bars** section below drone cards:
  - List of all found (alive) survivors with health bar, severity badge (CRITICAL=red, MODERATE=orange, STABLE=green), position
  - Health bars drain in real-time via SSE updates
  - Flash red when a survivor dies

#### `MeshGraph.tsx`
- Simple network visualization showing drones as nodes, edges where they can communicate
- **Relay drones** shown as larger nodes with extended range rings
- Highlight disconnected drones in red
- Show relay paths back to base
- **Network resilience indicator:** percentage badge (green > 70%, yellow 40-70%, red < 40%)
- Can use simple SVG lines between drone position dots

#### `ReasoningLog.tsx`
- Scrolling log showing agent's chain-of-thought reasoning
- Color-code entries:
  - Blue = reasoning text
  - Green = successful tool call
  - Orange = warning (low battery, disconnection)
  - Red = error or blackout event
  - **Purple = triage decision** (new)
  - **Dark red = survivor death** (new)
- Auto-scroll to bottom on new entries
- Data source: SSE `logs` events (replaces REST polling)
- **Voice narration indicator:** speaker icon next to entries that are being read aloud

##### Voice Narration (Innovation 6)

~20 lines of integration using the browser's `SpeechSynthesis` API:

```typescript
// Inside ReasoningLog.tsx
const synth = window.speechSynthesis;
const [voiceEnabled, setVoiceEnabled] = useState(false);

useEffect(() => {
  if (!voiceEnabled || !newEntry) return;
  // Only read critical entries aloud (triage, blackout, disaster, death)
  if (newEntry.is_critical) {
    const utterance = new SpeechSynthesisUtterance(newEntry.content);
    utterance.rate = 1.1;
    utterance.pitch = 0.9; // Slightly deeper for urgency
    synth.speak(utterance);
  }
}, [newEntry, voiceEnabled]);
```

Entries that trigger voice narration:
- Triage decisions (`type: "triage"`)
- Blackout events
- Survivor discoveries
- Survivor deaths
- Mission complete

The `voiceEnabled` state is controlled by the toggle in ControlPanel.

#### `ControlPanel.tsx`
- **Start Mission** button — POST /api/start
- **Trigger Blackout** button — opens modal to set zone_x, zone_y, radius, then POST /api/blackout
- **Manual Step** button — POST /api/step
- **Mission Stats** display — survivors found/total, **survivors alive/dead**, coverage %, steps elapsed
- **Voice Narration toggle** — on/off switch, controls `voiceEnabled` state passed to ReasoningLog (Innovation 6)
- **Reset** button — restart simulation from scratch

#### `TimelineSlider.tsx` (Innovation 7: Mission Replay)

A scrubber component at the bottom of the dashboard that enables judges to rewind and replay the entire mission:

```typescript
interface TimelineSliderProps {
  totalSteps: number;
  currentStep: number;
  onStepChange: (step: number) => void;
  isLive: boolean;
  onToggleLive: () => void;
}
```

Features:
- **Range slider** (`<input type="range">`) spanning from step 0 to current step
- **Play/pause button** for auto-playback at adjustable speed (1x, 2x, 5x)
- **"Go Live" button** — jumps to current step and re-enables SSE streaming
- **Step labels** showing key events: "Survivor found", "Blackout", "Aftershock", "Death" as markers on the timeline
- **State restoration:** When slider moves to step N, the dashboard renders `history.snapshots[N].state` instead of live data
- Fetches history from `GET /api/history`
- Keyboard shortcuts: Left/Right arrow for step-by-step, Space for play/pause

Implementation:
```typescript
function TimelineSlider({ totalSteps, currentStep, onStepChange, isLive, onToggleLive }: TimelineSliderProps) {
  const [history, setHistory] = useState<HistoryData | null>(null);
  const [playSpeed, setPlaySpeed] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    fetch("/api/history").then(r => r.json()).then(setHistory);
  }, [totalSteps]); // Refresh when new steps arrive

  // Auto-playback
  useEffect(() => {
    if (!isPlaying || isLive) return;
    const interval = setInterval(() => {
      onStepChange(prev => Math.min(prev + 1, totalSteps));
    }, 1000 / playSpeed);
    return () => clearInterval(interval);
  }, [isPlaying, playSpeed, isLive]);

  return (
    <div className="timeline-slider">
      <button onClick={() => setIsPlaying(!isPlaying)}>{isPlaying ? "⏸" : "▶"}</button>
      <input type="range" min={0} max={totalSteps} value={currentStep} onChange={e => onStepChange(+e.target.value)} />
      <span>Step {currentStep} / {totalSteps}</span>
      <select onChange={e => setPlaySpeed(+e.target.value)}>
        <option value={1}>1x</option>
        <option value={2}>2x</option>
        <option value={5}>5x</option>
      </select>
      <button onClick={onToggleLive} className={isLive ? "bg-green-500" : "bg-gray-500"}>
        {isLive ? "● LIVE" : "Go Live"}
      </button>
    </div>
  );
}
```

---

## Bayesian Heatmap Algorithm

The heatmap is a core intelligence layer. Here's the update logic:

```python
def update_heatmap(model, scan_position: tuple, found_survivors: list[tuple]):
    x, y = scan_position
    scan_radius = 1  # cells around scan position

    for dx in range(-scan_radius, scan_radius + 1):
        for dy in range(-scan_radius, scan_radius + 1):
            nx, ny = x + dx, y + dy
            if 0 <= nx < model.grid.width and 0 <= ny < model.grid.height:
                if (nx, ny) in found_survivors:
                    # Positive hit: increase adjacent cell probabilities
                    model.heatmap[nx][ny] = min(1.0, model.heatmap[nx][ny] + 0.2)
                    # Boost neighbors
                    for ddx in range(-1, 2):
                        for ddy in range(-1, 2):
                            nnx, nny = nx + ddx, ny + ddy
                            if 0 <= nnx < model.grid.width and 0 <= nny < model.grid.height:
                                model.heatmap[nnx][nny] = min(1.0, model.heatmap[nnx][nny] + 0.1)
                else:
                    # Negative result: decrease probability
                    model.heatmap[nx][ny] = max(0.05, model.heatmap[nx][ny] * 0.5)
```

---

## Stigmergy (Pheromone) System

The pheromone system provides **implicit swarm coordination** without centralized control. This is what makes the system truly decentralised — drones leave chemical-like traces that influence each other's behavior, even without direct communication.

### How Pheromones Work

```python
# In model.py — each step
def step(self):
    # ... other step logic ...

    # Decay all pheromone layers
    self.pheromone_scanned *= 0.9
    self.pheromone_survivor_nearby *= 0.9
    self.pheromone_danger *= 0.9

# In agents.py — DroneAgent
def deposit_pheromones(self):
    x, y = self.position
    # After scanning: mark territory
    self.model.pheromone_scanned[x][y] = 1.0

def autonomous_navigation(self):
    """Pheromone-guided movement when disconnected."""
    best_score = -float('inf')
    best_cell = self.position
    for nx, ny in self.get_neighbors():
        score = (
            self.model.pheromone_survivor_nearby[nx][ny] * 1.0   # attracted to survivor signals
            - self.model.pheromone_scanned[nx][ny] * 0.5          # repelled by already-scanned
            - self.model.pheromone_danger[nx][ny] * 2.0           # strongly repelled by danger
        )
        if score > best_score:
            best_score = score
            best_cell = (nx, ny)
    self.move_to(*best_cell)
```

### Why This Matters for Judges
Traditional swarm simulations use **centralized control** (the LLM tells every drone what to do). Our pheromone system means:
1. Drones **naturally spread out** (scanned pheromone is repulsive → avoids duplication)
2. Drones **converge on promising areas** (survivor_nearby pheromone is attractive → cluster near finds)
3. Drones **avoid danger** without being told (danger pheromone from aftershocks/water)
4. All of this works **during blackouts** when the LLM cannot communicate with drones

This is real stigmergy — the same mechanism ants use. It's biologically inspired, scientifically grounded, and produces emergent intelligent behavior.

---

## Mesh Network & Self-Healing Logic

### Connection Rules
- Each drone has `comm_range = 4` cells (6 cells if deployed as relay)
- Two drones can communicate directly if Manhattan distance <= comm_range
- A drone is `connected` to command if there exists a relay path (chain of drones within range of each other) back to base (0,0)
- Base station at (0,0) has unlimited comm range to drones within 4 cells
- Relay drones (`is_relay = True`) are stationary and have extended range, acting as communication infrastructure

### Blackout Logic
- `trigger_blackout(zone_x, zone_y, radius)` forces all drones within radius to `connected = False`
- Blackout overrides relay paths — even if a relay exists, drones in the blackout zone can't use it
- Drones in blackout **activate autonomous_step()** — they continue scanning using pheromone-guided navigation
- Scan results during blackout are stored in `findings_buffer`

### Self-Healing
- Each time `compute_mesh_topology()` is called, check if any disconnected drone now has a relay path
- If a previously disconnected drone is now within comm_range of a connected drone (or relay drone), set `connected = True`
- Agent should then call `sync_findings(drone_id)` to retrieve buffered data
- If connectivity is critically low, the agent can sacrifice a drone via `deploy_as_relay()` to restore network

---

## Digital Twin / simulate_mission()

```python
def simulate_mission(drone_id, target_x, target_y):
    drone = get_drone(drone_id)

    # Calculate Manhattan distance
    distance = abs(drone.position[0] - target_x) + abs(drone.position[1] - target_y)

    # Battery cost: 2 per move step
    battery_cost_to_target = distance * 2
    battery_at_arrival = drone.battery - battery_cost_to_target

    # Can it return to base after scanning?
    distance_back = abs(target_x - 0) + abs(target_y - 0)
    battery_cost_return = distance_back * 2 + 3  # +3 for one scan
    can_return = battery_at_arrival - 3 - (distance_back * 2) > 5  # 5% safety margin

    # Heatmap probability at target
    survivor_probability = model.heatmap[target_x][target_y]

    return {
        "drone_id": drone_id,
        "target": (target_x, target_y),
        "distance": distance,
        "battery_cost": battery_cost_to_target,
        "battery_at_arrival": max(0, battery_at_arrival),
        "scan_cost": 3,
        "can_return_to_base": can_return,
        "survivor_probability": round(survivor_probability, 3),
        "recommended": can_return and survivor_probability > 0.3
    }
```

---

## Demo Script (Presentation Flow)

Use this scripted sequence for the live demo. The demo is designed as a **dramatic narrative arc** with clear "wow moments" for judges.

### Act 1: Discovery (Steps 1-5)
1. **Opening** — Show the empty 12x12 grid. "A Category 5 typhoon has struck Manila. All cell towers are down. Survivors are trapped and their conditions are deteriorating every second."
2. **Agent discovers fleet** — Watch `discover_drones()` reveal 4 drones at base. Agent reasons about initial strategy using the heatmap.
3. **Pheromone + heatmap overlay** — Toggle the overlay. Buildings glow red (high probability). "The agent doesn't scan randomly — it uses Bayesian probabilities AND bio-inspired pheromone trails."
4. **Sector assignment** — Agent calls `coordinate_swarm("ALL")` to assign drones to quadrants. "Each drone now has a sector to cover — and they'll continue autonomously even if communication fails."
5. **Deployment** — Watch drones fan out to high-probability zones with smooth CSS transition animations. Agent explains each assignment in the reasoning log.

### Act 2: The Living Disaster (Steps 6-15)
6. **First survivor found** — Yellow star + health bar appears. Scan pulse animation radiates outward. Agent reads severity: "CRITICAL, health at 85%." Voice narration reads the triage assessment aloud.
7. **Pheromone deposit visible** — Toggle pheromone overlay: gold glow around found survivor, blue tint on scanned cells. "Other drones are automatically drawn toward survivor signals — stigmergy, the same mechanism ants use."
8. **Second survivor found** — MODERATE severity. Agent performs triage reasoning: "TRIAGE: Survivor A is CRITICAL at (3,7) with 75% health. Survivor B is MODERATE at (8,2) with 95% health. Prioritizing Survivor A."
9. **AFTERSHOCK EVENT** — Grid shakes animation. 2 cells become DEBRIS. Danger pheromone appears. "The disaster isn't static — aftershocks change the terrain. Watch the drones autonomously route around the new debris."
10. **Triage decision** — A third survivor found (STABLE). Agent shows deep reasoning: weighs health drain rates, drone positions, battery levels. Voice narrates the decision. "This is the LLM doing real-time triage — not following a script."

### Act 3: Communication Crisis (Steps 16-25)
11. **Trigger blackout** — Click blackout button. 2 drones go offline. Mesh graph shows broken links. Red flash animation on dashboard. Voice: "Communication lost in sector NE."
12. **Autonomous drones** — Point out that disconnected drones CONTINUE scanning — they follow pheromone gradients. "These drones are not puppets. They have local intelligence."
13. **Drone sacrifice for relay** — Agent checks `get_network_resilience()`, sees 40% connectivity. Reasons about sacrificing Drone Delta (lowest battery, 22%) as a relay. Calls `deploy_as_relay()`. "The agent sacrificed a searcher to save the network. That's strategic thinking."
14. **Self-healing** — Connected drone moves within range, relay path restores through the deployed relay. Agent calls `sync_findings()` to retrieve buffered data. Heatmap updates with offline discoveries.
15. **Rising water event** — WATER cells expand. A survivor is threatened. Agent recalculates priorities: "TRIAGE UPDATE: Survivor at (9,8) was STABLE but rising water threatens position. Elevating to immediate priority."

### Act 4: Race Against Time (Steps 26-35)
16. **Low battery recall** — Agent notices Drone Alpha at 18%, runs `simulate_mission()` for 3 remaining targets, picks the optimal one before recalling. Uses digital twin to verify it can reach ONE more survivor and still return. Voice narrates the reasoning.
17. **Survivor death** — A CRITICAL survivor's health reaches 0. Gray X appears. Voice: "We've lost the survivor at (5,9). Their injuries were too severe." Agent acknowledges, refocuses. "This is what makes the simulation real — there are consequences."
18. **Final push** — Remaining drones converge on last known high-probability areas. Pheromone map shows clear coverage: blue everywhere scanned, gold fading near found survivors.

### Act 5: Victory & Replay (Steps 36-40)
19. **Mission complete** — All living survivors located. Voice reads mission summary. Show stats: "7 of 8 survivors saved. 1 casualty. 89% coverage in 38 steps."
20. **Timeline replay** — Slide the TimelineSlider back to key moments. "Judges, you can rewind to any decision point. Watch the triage reasoning at step 10. See the autonomous behavior during blackout at step 16. This is a full mission replay."

### Wow Moments Summary for Judges
| Moment | Innovation Shown |
|---|---|
| Pheromone overlay on grid | Stigmergy / decentralised coordination |
| Drones continue scanning during blackout | Two-tier local autonomy |
| Aftershock changes terrain mid-mission | Dynamic disaster progression |
| Agent explicitly triages CRITICAL vs STABLE | Triage reasoning with real stakes |
| Drone sacrificed as relay node | Strategic network management |
| Survivor health bar draining to death | Real consequences / urgency |
| Voice reads triage decisions aloud | Voice narration |
| Timeline slider rewinds to any step | Mission replay |
| Smooth animations on drone movement | SSE streaming + CSS transitions |

---

## Key Differentiators (Why This Wins)

1. **Two-Tier Decentralised Intelligence** — Not just an LLM controlling puppets. Drones have LOCAL autonomy: pheromone-guided navigation, auto-return, sector scanning — all without commander input. This is what "decentralised" actually means.

2. **Stigmergy (Pheromone System)** — Bio-inspired coordination. Drones leave traces that attract or repel other drones. Emergent intelligent behavior without centralized control. Scientifically grounded in ant colony optimization theory.

3. **Dynamic Disaster Progression** — The disaster zone is ALIVE. Aftershocks change terrain, water rises, survivors deteriorate. Other teams will have static maps. Our simulation has real consequences: survivors die if you're too slow.

4. **Triage Reasoning** — The deepest chain-of-thought reasoning in any submission. The agent explicitly weighs health drain rates, proximity, battery costs, and makes life-or-death triage decisions visible in the reasoning log. This showcases what LLM agents can really do.

5. **SSE Streaming Dashboard** — While other teams poll every second, our dashboard updates in real-time via Server-Sent Events with smooth CSS transitions, scan pulse animations, and dramatic visual effects for disasters.

6. **Voice Narration** — The agent literally speaks its critical decisions aloud. Triage calls, blackout alerts, mission updates. ~20 lines of code, massive demo impact.

7. **Mission Replay Timeline** — Judges can rewind to any step and review any decision. No other team will have this. It turns a live demo into an explorable experience.

### Baseline Differentiators (from original PRD)

8. **Bayesian Heatmap Intelligence** — Agent doesn't randomly scan. It uses probability-driven search that updates in real-time.

9. **Real Communication Failure** — Actually sever connections, buffer data, and self-heal through mesh relay. Not just a checkbox.

10. **Digital Twin Planning** — Agent simulates before committing. Chain-of-thought shows "I ran 3 simulations, option B is optimal because..."

11. **Dynamic Fleet Discovery** — No hard-coded drone IDs. Agent discovers the fleet each time, adapts when drones go offline or new ones come online.

12. **Visible Reasoning** — Dashboard shows the LLM's chain-of-thought in real-time. Judges see WHY each decision was made.

---

## 3-Day Implementation Schedule

### Day 1: Backend Foundation (Simulation + MCP + Agent)

| Time Block | Task | Details |
|---|---|---|
| Morning (3-4h) | Mesa simulation engine | `model.py`: grid, terrain, PropertyLayers (heatmap + 3 pheromones), disaster progression (aftershocks, rising water). `agents.py`: DroneAgent with full local autonomy methods, SurvivorAgent with health decay. `mesh_network.py`: topology, blackout, relay, resilience analysis. |
| Afternoon (3-4h) | MCP server + all 17 tools | `server.py`: implement all tool functions against the Mesa model. Test each tool in isolation with `mcp dev`. Focus on core tools first (1-11), then innovation tools (12-17). |
| Evening (2-3h) | LangGraph agent + system prompt | `prompts.py`: full system prompt with triage protocol. `graph.py`: StateGraph with MessagesState. `runner.py`: entry point with MCP client. Test agent loop end-to-end: does it discover, scan, triage, handle blackout? |
| **Day 1 deliverable** | Agent runs a full mission via MCP against the simulation. Triage works, pheromones work, disasters fire. No frontend yet — validate in terminal. |

### Day 2: Frontend Dashboard + SSE

| Time Block | Task | Details |
|---|---|---|
| Morning (3-4h) | FastAPI bridge + SSE streaming | `bridge.py`: SSE endpoint (`/api/stream`), REST fallbacks, history endpoint (`/api/history`). State snapshot recording per step. Next.js scaffolding: `create-next-app`, layout, `api.ts` with EventSource client. |
| Afternoon (3-4h) | Core dashboard components | `GridMap.tsx`: terrain rendering, heatmap overlay, drone markers with CSS transitions, scan pulse animation. `DronePanel.tsx`: battery bars, status, survivor health bars. `ReasoningLog.tsx`: color-coded entries, auto-scroll. `MeshGraph.tsx`: SVG network topology. |
| Evening (2-3h) | Control panel + interactivity | `ControlPanel.tsx`: start, blackout, step, reset, voice toggle. Wire up SSE to all components. Test: start mission from dashboard, watch grid update in real-time, trigger blackout from UI. |
| **Day 2 deliverable** | Full working dashboard showing live mission with SSE updates, drone animations, heatmap, reasoning log. |

### Day 3: Polish + Wow Factors + Demo Prep

| Time Block | Task | Details |
|---|---|---|
| Morning (2-3h) | Voice narration + timeline slider | `ReasoningLog.tsx`: add SpeechSynthesis (~20 lines). `TimelineSlider.tsx`: range slider, play/pause, speed control, "Go Live" button. Wire to `/api/history`. Test: replay a completed mission. |
| Afternoon (2-3h) | Visual polish + animations | Pheromone overlay toggle, aftershock shake animation, rising water CSS transition, blackout red flash, survivor death gray-out. Responsive layout fixes. Edge cases: what if all drones die? What if agent errors? |
| Evening (2-3h) | Demo rehearsal | Run `demo.py` scripted sequence 3+ times. Time it (target: 8-10 minutes). Practice narration alongside voice narration. Ensure blackout timing creates drama. Prepare backup: if agent goes off-script, know where to manual-step. Record a backup video. |
| **Day 3 deliverable** | Demo-ready. Voice narration works, timeline replay works, animations are smooth, demo script rehearsed. |

### Risk Mitigations
- **If LLM is slow:** Pre-cache a mission log and run in "replay mode" for demo
- **If SSE has issues:** REST polling fallback is built in
- **If voice narration is buggy:** It's a toggle — just turn it off
- **If timeline slider has edge cases:** Lock it to "live" mode during demo

---

## Running the Project

### Terminal 1: MCP Server
```bash
cd project-root
python -m mcp_server.server
# Serves on http://localhost:8000/mcp
```

### Terminal 2: API Bridge
```bash
cd project-root
uvicorn api.bridge:app --port 8001 --reload
# Serves on http://localhost:8001
```

### Terminal 3: Agent Runner
```bash
cd project-root
python -m agent.runner
# Connects to MCP server, starts mission
```

### Terminal 4: Frontend
```bash
cd project-root/dashboard
npm run dev
# Serves on http://localhost:3000
```

---

## Environment Variables

```env
OPENAI_API_KEY=sk-xxxxx
MCP_SERVER_URL=http://localhost:8000/mcp
API_BRIDGE_URL=http://localhost:8001
GRID_WIDTH=12
GRID_HEIGHT=12
NUM_DRONES=4
NUM_SURVIVORS=8
MAX_MISSION_STEPS=50
```

---

## Success Criteria

### Mandatory (Case Study Requirements)
- [ ] Agent discovers drones dynamically (no hard-coded IDs)
- [ ] All MCP tool calls go through the MCP protocol (no direct function calls from agent)
- [ ] Agent demonstrates chain-of-thought reasoning before every action
- [ ] Bayesian heatmap updates correctly on scan results
- [ ] Blackout disconnects drones, they buffer findings, self-heal on reconnection
- [ ] Digital twin simulate_mission() runs predictions before moves
- [ ] Dashboard shows real-time grid, heatmap, drone status, and reasoning log
- [ ] Mission completes with all survivors found
- [ ] Mission log is exportable as JSON

### Innovation Criteria (Differentiators)
- [ ] Drones continue scanning autonomously during blackout using pheromone gradients (Two-Tier Intelligence)
- [ ] Three pheromone layers (scanned, survivor_nearby, danger) visible on dashboard with decay (Stigmergy)
- [ ] Aftershocks change terrain and rising water threatens survivors mid-mission (Dynamic Disaster)
- [ ] Agent performs explicit triage reasoning with severity levels and health drain (Triage Reasoning)
- [ ] Dashboard updates via SSE with smooth CSS transitions and scan pulse animations (SSE Streaming)
- [ ] Voice narration reads critical agent decisions aloud via SpeechSynthesis (Voice Narration)
- [ ] Timeline slider enables judges to rewind and replay any step of the mission (Mission Replay)
- [ ] All 17 MCP tools are functional (11 core + 6 innovation)
- [ ] Demo script produces at least 5 distinct "wow moments" for judges
