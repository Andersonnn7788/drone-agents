# Implementation Plan: Drone Swarm Rescue Simulation

## Context
Greenfield hackathon project (Agentic AI track). Self-healing rescue drone swarm simulation — LLM Command Agent orchestrates 4-5 drones to find survivors in a 12x12 disaster zone. All agent-to-simulation communication flows through MCP. Two-tier intelligence: LLM sets strategy, drones carry local autonomy.

**Approach: Backend first.** Frontend needs data. Build bottom-up.

---

## 6 Stages

```
Stage 1: Simulation Engine     ✅ COMPLETE
    ↓
Stage 2: MCP Server            ✅ COMPLETE
    ↓  (can parallel with Stage 3)
Stage 3: FastAPI Bridge        ✅ COMPLETE
    ↓
Stage 4: LangGraph Agent       ✅ COMPLETE
    ↓
Stage 5: Dashboard (Core)      ✅ COMPLETE
    ↓
Stage 6: Polish + Demo         ← UP NEXT (depends on Stages 4+5)
```

---

## Stage 1: Mesa Simulation Engine [x]

**Goal:** Fully functional simulation — drones, survivors, terrain, heatmap, pheromones, mesh network, dynamic disasters. Can be stepped programmatically.

### Files

| File | Purpose | Status |
|------|---------|--------|
| `requirements.txt` | Python dependencies | [x] |
| `simulation/__init__.py` | Package marker | [x] |
| `simulation/model.py` | DisasterModel — grid, terrain, heatmap, pheromones, disasters, state serialization | [x] |
| `simulation/agents.py` | DroneAgent (local autonomy) + SurvivorAgent (health decay) | [x] |
| `simulation/mesh_network.py` | Mesh topology, blackout, relay paths, resilience analysis | [x] |

### simulation/agents.py

**DroneAgent(mesa.Agent):**
- Properties: `drone_id`, `battery=100`, `status="active"`, `connected=True`, `comm_range=4`, `findings_buffer=[]`, `scan_radius=1`, `assigned_sector=None`, `is_relay=False`
- `move_to(x, y)` — validate passable + battery >= 2, move via grid, drain 2
- `thermal_scan()` — check cells within scan_radius, mark found survivors, deposit pheromones (scanned=1.0, survivor_nearby=1.0+0.5 neighbors), update heatmap, drain 3, buffer if disconnected
- `return_to_base()` — set status "returning", pathfind to (0,0)
- `charge()` — at base, +10/step until 100
- `deploy_as_relay()` — is_relay=True, status="relay", comm_range=6
- `autonomous_step()` — local autonomy: battery<15% auto-return, sector scanning, pheromone nav (`score = survivor_nearby - 0.5*scanned - 2.0*danger`)
- `step()` — called by Mesa: handle charging, returning, autonomous behavior

**SurvivorAgent(mesa.Agent):**
- Properties: `severity`, `health=1.0`, `found=False`, `rescued=False`, `alive=True`
- `step()` — drain health (CRITICAL=0.05, MODERATE=0.02, STABLE=0.01), die at 0

### simulation/model.py

**DisasterModel Constructor:**
- 12x12 MultiGrid(torus=False)
- Terrain grid: ~8-10 BUILDING (clusters), ROAD (certain rows/cols), 2-3 WATER, rest OPEN
- Bayesian heatmap: numpy 12x12, priors from terrain (BUILDING=0.7, ROAD=0.5, OPEN=0.3, WATER/DEBRIS=0.1)
- 3 pheromone arrays: `pheromone_scanned`, `pheromone_survivor_nearby`, `pheromone_danger` (numpy zeros)
- 4 DroneAgents at (0,0): drone_alpha, drone_bravo, drone_charlie, drone_delta
- 8 SurvivorAgents at random passable positions (~3 CRITICAL, ~3 MODERATE, ~2 STABLE)
- `disaster_events=[]`, `mission_step=0`, `state_history=[]`, `scanned_cells=set()`

**`step()` — per tick:**
1. mission_step += 1
2. Drain 1 battery from all active drones
3. Decay pheromones *= 0.9
4. Step survivors (health drain)
5. Step drones (charging, returning, autonomous)
6. Aftershock check (~every 10 steps): 2-3 OPEN→DEBRIS, deposit danger pheromone
7. Rising water check (~every 15 steps): WATER expands 1 cell, kills threatened survivors
8. Recompute mesh topology
9. Record state snapshot

**`get_state()` → dict:** Full JSON-serializable state (terrain, drones, found survivors only, heatmap, pheromones, mesh, stats, events)

**`update_heatmap(scan_position, found_survivors)`:** Bayesian update — hit boosts cell+neighbors, miss halves (floor 0.05)

### simulation/mesh_network.py

- `compute_mesh_topology(drones, base_pos)` → adjacency list, update connected via BFS
- `apply_blackout(drones, zone_center, radius)` → force connected=False in zone
- `check_relay_path(drone, base_pos, all_drones)` → BFS for relay path to base
- `sync_drone(drone)` → flush and return findings_buffer
- `get_network_resilience(drones, base_pos)` → connectivity ratio, critical nodes, coverage gaps, relay suggestions

### Verification
```bash
python -c "
from simulation.model import DisasterModel
m = DisasterModel()
print('Drones:', len([a for a in m.agents if hasattr(a, 'drone_id')]))
for _ in range(10): m.step()
print('History:', len(m.state_history), 'snapshots')
print('State keys:', list(m.get_state().keys()))
print('Stage 1 OK')
"
```

### Design Decisions
- Raw numpy arrays for pheromones (simpler than Mesa PropertyLayer, matches PRD code)
- Terrain as 2D list of enums (categorical, not numeric)
- `get_state()` defined once in model, reused by MCP server + API bridge
- Deterministic terrain layout with optional seed for reproducible demos

---

## Stage 2: MCP Server (17 Tools) [x]

**Goal:** Expose simulation via 17 MCP tools over Streamable HTTP at localhost:8000/mcp.

### Files

| File | Purpose | Status |
|------|---------|--------|
| `mcp_server/__init__.py` | Package marker | [x] |
| `mcp_server/server.py` | FastMCP with 17 @mcp.tool() definitions | [x] |

### Tools (17 total)

**Core (11):** `discover_drones`, `move_to`, `thermal_scan`, `get_battery_status`, `get_priority_map`, `simulate_mission`, `sync_findings`, `trigger_blackout`, `recall_drone`, `get_mission_summary`, `advance_simulation`

**Innovation (6):** `get_pheromone_map`, `get_disaster_events`, `assess_survivor`, `deploy_as_relay`, `get_network_resilience`, `coordinate_swarm`

Each tool is a thin wrapper: validate inputs → call simulation method → return dict.

### Verification
```bash
python -m mcp_server.server  # starts on :8000
# Test: list tools, call discover_drones, move a drone
```

---

## Stage 3: FastAPI Bridge (SSE + REST) [x]

**Goal:** Serve simulation state to frontend via SSE streaming + REST fallback at localhost:8001.

### Files

| File | Purpose | Status |
|------|---------|--------|
| `api/__init__.py` | Package marker | [x] |
| `api/bridge.py` | FastAPI app with SSE + REST endpoints | [x] |
| `simulation/state.py` | Shared model singleton (used by MCP + bridge) | [x] |

### Endpoints
- `GET /api/stream` — SSE (events: state, logs, disaster, blackout)
- `GET /api/state` — Full simulation state snapshot
- `GET /api/logs` — Agent reasoning entries
- `GET /api/history` — All state snapshots for replay
- `GET /api/mesh` — Mesh network topology
- `POST /api/start` — Begin agent mission
- `POST /api/step` — Advance simulation N steps
- `POST /api/blackout` — Trigger blackout event

### Shared State
MCP server + API bridge share same DisasterModel via `simulation/state.py` singleton. Run in same process (bridge spawns MCP in background thread).

### Verification
```bash
uvicorn api.bridge:app --port 8001
curl http://localhost:8001/api/state | python -m json.tool
curl -X POST http://localhost:8001/api/step -d '{"steps": 5}'
curl -N http://localhost:8001/api/stream  # SSE events
```

---

## Stage 4: LangGraph Agent [x]

**Goal:** LLM command agent that connects to MCP, discovers drones, runs search-and-rescue with chain-of-thought triage reasoning.

### Files

| File | Purpose | Status |
|------|---------|--------|
| `agent/__init__.py` | Package marker | [x] |
| `agent/prompts.py` | System prompt with triage protocol | [x] |
| `agent/graph.py` | LangGraph StateGraph (MessagesState) | [x] |
| `agent/runner.py` | Entry point: MCP client → agent loop | [x] |
| `logs/mission_log.json` | Persisted reasoning + tool calls | [x] |

### Architecture
- StateGraph: START → agent → tools_condition → tools → agent (loop) → END
- MultiServerMCPClient connecting to http://localhost:8000/mcp
- GPT-5 mini via langchain-openai
- Streams reasoning to logs + API bridge

### Verification
```bash
python -m agent.runner
# Watch: discover_drones → sector assignment → scanning → triage reasoning → mission complete
```

---

## Stage 5: Next.js Dashboard (Core) [x]

**Goal:** Real-time dashboard visualizing simulation via SSE from the API bridge.

### Files

| File | Purpose | Status |
|------|---------|--------|
| `dashboard/` | Next.js scaffold (manual, Next.js 16) | [x] |
| `dashboard/lib/api.ts` | SSE client + REST helpers + TypeScript interfaces | [x] |
| `dashboard/app/page.tsx` | 4-panel CSS Grid layout | [x] |
| `dashboard/app/layout.tsx` | Dark theme layout | [x] |
| `dashboard/components/GridMap.tsx` | 12x12 grid with terrain, heatmap, drones, survivors | [x] |
| `dashboard/components/DronePanel.tsx` | Battery bars, status, survivor health bars | [x] |
| `dashboard/components/ReasoningLog.tsx` | Color-coded scrolling CoT log | [x] |
| `dashboard/components/ControlPanel.tsx` | Start, blackout, step, reset | [x] |
| `dashboard/components/TimelineSlider.tsx` | Mission replay scrubber | [x] |

### Verification
```bash
cd dashboard && npm run dev
# Open http://localhost:3000 with API bridge running
# Grid renders, drones visible, start mission works, SSE updates flow
```

---

## Stage 6: Polish + Demo [ ]

**Goal:** Wow-factor features — timeline replay, voice narration, animations, demo script.

### Files

| File | Purpose | Status |
|------|---------|--------|
| `dashboard/components/TimelineSlider.tsx` | Mission replay scrubber | [x] | Already built in Stage 5 (75 lines, live/replay modes, go-live button) |
| `dashboard/components/MeshGraph.tsx` | SVG network topology | [ ] | Does not exist |
| Voice in `ReasoningLog.tsx` | SpeechSynthesis for critical entries | [ ] | Not implemented |
| CSS animations | Scan pulse, aftershock shake, water expansion, blackout flash | [partial] | blink, blackout-flash, bar-transition, scan-pulse exist; aftershock shake + water expansion missing |
| `scripts/demo.py` | Scripted 5-act demo sequence | [ ] | Does not exist |
| `scripts/run_all.sh` | Start all 4 services | [ ] | Does not exist |

### Verification
Full end-to-end demo: run_all.sh → open dashboard → start mission → watch 5-act narrative → trigger blackout → replay with timeline slider → voice narration works

---

## Progress Log

| Date | Stage | What was done |
|------|-------|---------------|
| 2026-03-15 | Stage 1 | Simulation engine complete — DisasterModel, DroneAgent, SurvivorAgent, mesh network, pheromones, terrain, heatmap, dynamic disasters |
| 2026-03-15 | Stage 2 | MCP server complete — 17 tools (11 core + 6 innovation) exposed via FastMCP on Streamable HTTP |
| 2026-03-15 | Stage 3 | FastAPI bridge complete — SSE streaming, REST endpoints, shared model singleton, CORS, blackout/step/start controls |
| 2026-03-15 | Stage 4 | LangGraph agent complete — system prompt with triage protocol, StateGraph (agent→tools loop), runner with in-process MCP+bridge servers, GPT-5-mini, logging pipeline to model.agent_logs, mission_log.json persistence |
| 2026-03-15 | Stage 5 | Next.js dashboard complete — manually scaffolded (Next.js 16), lib/api.ts (TypeScript interfaces + SSE + REST), page.tsx (4-panel grid), GridMap (12×12 terrain+heatmap+drone markers), DronePanel (battery+health bars), ReasoningLog (color-coded CoT), ControlPanel (start/step/blackout/reset), TimelineSlider (replay scrubber) |
