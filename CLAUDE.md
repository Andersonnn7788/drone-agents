# CLAUDE.md — Drone Swarm Rescue Simulation

## Project Overview

Self-healing rescue drone swarm simulation for a hackathon (Agentic AI track). An LLM Command Agent orchestrates 4-5 drones to find survivors in a 12x12 disaster zone grid — with zero cloud connectivity. All agent-to-simulation communication flows through **MCP (Model Context Protocol)**.

**Key insight:** Drones are NOT puppets. Two-tier intelligence — LLM sets strategy, drones carry local autonomy (pheromone-guided navigation, auto-return, sector scanning) that works even during communication blackouts.

## Tech Stack

| Layer | Technology | Port |
|---|---|---|
| Simulation Engine | Mesa 3 (Python) | — |
| MCP Server | FastMCP (`mcp` SDK, Streamable HTTP) | `localhost:8000/mcp` |
| Agent Brain | LangChain + LangGraph + `langchain-mcp-adapters` | — |
| LLM | OpenAI GPT-5 mini (`gpt-5-mini`) via `langchain-openai` | — |
| API Bridge | FastAPI (SSE streaming + REST) | `localhost:8001` |
| Frontend | Next.js 16+ (App Router) + React + TypeScript + Tailwind | `localhost:3000` |

## Architecture

```
Next.js Dashboard (SSE: GET /api/stream, REST fallback)
        │
   FastAPI Bridge (:8001)
        │
   ┌────┴────┐
   │         │
LangGraph  MCP Server (FastMCP, :8000/mcp)
 Agent       │ direct Python calls
             │
        Mesa Simulation Engine
        ├─ 12x12 MultiGrid (terrain: BUILDING, ROAD, OPEN, WATER, DEBRIS)
        ├─ DroneAgents (local autonomy)
        ├─ SurvivorAgents (health decay, severity: CRITICAL/MODERATE/STABLE)
        ├─ PropertyLayers (Bayesian heatmap + 3 pheromone layers)
        └─ Dynamic disasters (aftershocks, rising water)
```

### Two-Tier Intelligence

- **Tier 1 — LLM Commander (Strategic):** Sector assignments, triage reasoning, digital twin planning, pheromone map analysis, swarm coordination. Communicates via MCP tool calls.
- **Tier 2 — Drone Local Autonomy (Tactical):** During blackout/no orders: continue scanning assigned sector, auto-return at battery < 15%, follow pheromone gradients (`score = survivor_nearby - 1.5*scanned - 2.0*danger + 0.5*heatmap`), attempt mesh relay, buffer findings.

## Directory Structure

```
project-root/
├── CLAUDE.md
├── prd.md
├── requirements.txt
├── simulation/
│   ├── __init__.py
│   ├── model.py          # DisasterModel (grid, terrain, heatmap, pheromones, disasters)
│   ├── agents.py         # DroneAgent (local autonomy), SurvivorAgent (health decay)
│   ├── mesh_network.py   # Mesh topology, blackout, relay, resilience analysis
│   └── state.py          # Simulation state snapshot & serialization helpers
├── mcp_server/
│   ├── __init__.py
│   └── server.py         # FastMCP server — 19 @mcp.tool() definitions
├── agent/
│   ├── __init__.py
│   ├── graph.py          # LangGraph StateGraph (MessagesState)
│   ├── memory.py         # Cross-mission memory — lessons learned persistence
│   ├── prompts.py        # System prompt with triage protocol
│   ├── runner.py         # Entry point: MCP client → agent loop
│   └── shared.py         # Shared state & config across agent modules
├── api/
│   ├── __init__.py
│   └── bridge.py         # FastAPI: SSE /api/stream, REST /api/state, /api/logs, /api/history
├── dashboard/            # Next.js app
│   ├── app/
│   │   ├── page.tsx      # 4-panel layout + timeline slider
│   │   └── layout.tsx
│   ├── components/
│   │   ├── GridMap.tsx        # 12x12 grid, heatmap overlay, pheromones, drone markers, animations
│   │   ├── DronePanel.tsx     # Battery bars, status, survivor health bars
│   │   ├── MeshGraph.tsx      # SVG network topology
│   │   ├── ReasoningLog.tsx   # Color-coded CoT log + SpeechSynthesis voice narration
│   │   ├── ControlPanel.tsx   # Start, blackout, step, voice toggle, reset
│   │   ├── TimelineSlider.tsx # Mission replay scrubber (rewind to any step)
│   │   └── RescueToast.tsx    # Toast notifications for rescue events
│   └── lib/
│       └── api.ts             # SSE client (EventSource) + REST fetch helpers
├── scripts/
│   ├── run_all.sh
│   └── demo.py
└── logs/
    ├── mission_log.json
    └── lessons_learned.json
```

## Running the Project

### Install Dependencies

```bash
# Python (from project root)
pip install "mcp[cli]" mesa langchain-mcp-adapters langgraph langchain-openai langchain fastapi uvicorn numpy python-dotenv

# Frontend (from project root)
cd dashboard
npm install
```

### Start Services (4 terminals)

```bash
# Terminal 1: MCP Server
python -m mcp_server.server
# → http://localhost:8000/mcp

# Terminal 2: API Bridge
uvicorn api.bridge:app --port 8001 --reload
# → http://localhost:8001

# Terminal 3: Agent Runner
python -m agent.runner
# Connects to MCP, starts mission

# Terminal 4: Frontend
cd dashboard && npm run dev
# → http://localhost:3000
```

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
DEMO_MODE=true
LLM_MODEL=gpt-5-mini
MSG_WINDOW_SIZE=20
LLM_MAX_TOKENS=4096
```

## Key Design Patterns

### Stigmergy / Pheromone System
Three PropertyLayer pheromones for implicit swarm coordination:
- **`scanned`** (repulsive) — drones avoid re-scanning areas
- **`survivor_nearby`** (attractive) — drones converge on probable survivor locations
- **`danger`** (strongly repulsive) — drones avoid aftershock/water zones

All pheromones decay by 0.9x per step. Works during blackouts without LLM involvement.

### Bayesian Heatmap
12x12 probability grid initialized from terrain (buildings=0.7, roads=0.5, open=0.3). Updated on scan: positive hit boosts cell + neighbors, negative result halves probability (floor 0.05).

### Digital Twin (simulate_mission)
Predicts battery cost, arrival battery, return feasibility, and survivor probability BEFORE committing a drone to a move. Agent uses this for chain-of-thought planning.

### Mesh Network & Self-Healing
- Drones communicate within `comm_range=4` (Manhattan distance); relays get range 6
- Blackout zones force `connected=False`; drones activate autonomous mode
- Disconnected drones buffer findings in `findings_buffer`
- Self-healing: topology recomputation detects restored relay paths → `sync_findings()`
- Agent can sacrifice low-battery drones as stationary relays via `deploy_as_relay()`

### Triage Protocol
When multiple survivors found, agent reasons through priority:
1. CRITICAL + health < 30% → immediate
2. CRITICAL + health 30-60% → within 2-3 steps
3. MODERATE + health < 40% → medium-high
4. STABLE → low priority
5. Equal urgency → prioritize closest to a drone

Survivor health drain: CRITICAL=0.05/step (~20 steps), MODERATE=0.02/step (~50), STABLE=0.01/step (~100).

## MCP Tools (19 total)

**Core (12):** `discover_drones`, `move_to`, `thermal_scan`, `get_battery_status`, `get_priority_map`, `simulate_mission`, `sync_findings`, `trigger_blackout`, `recall_drone`, `get_mission_summary`, `advance_simulation`, `rescue_survivor`

**Innovation (7):** `get_pheromone_map`, `get_disaster_events`, `assess_survivor`, `deploy_as_relay`, `get_network_resilience`, `coordinate_swarm`, `get_performance_score`

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stream` | SSE stream (events: `state`, `logs`, `disaster`, `blackout`) |
| GET | `/api/state` | Full simulation state snapshot |
| GET | `/api/logs` | Agent reasoning entries |
| GET | `/api/history` | All state snapshots for mission replay |
| GET | `/api/mesh` | Mesh network topology |
| POST | `/api/start` | Begin autonomous agent mission |
| POST | `/api/step` | Manually advance simulation N steps |
| POST | `/api/blackout` | Trigger blackout event `{zone_x, zone_y, radius}` |
| GET | `/api/health` | Health check with mission status |
| GET | `/api/score` | RL-inspired performance score for current mission |
| GET | `/api/lessons` | Cross-mission lessons learned |
| POST | `/api/reset` | Reset simulation to fresh state |

## Development Notes

- The agent MUST call `discover_drones()` first — never hard-code drone IDs
- All agent-to-simulation communication goes through MCP protocol (no direct function calls)
- SSE is the primary data transport to the frontend; REST endpoints are fallback
- State snapshots are recorded each step for the timeline replay feature
- Voice narration uses browser `SpeechSynthesis` API — only reads `is_critical: true` log entries
- Grid is 12x12, `torus=False`. Base station at `(6,5)`
- Drones start at `(6,5)`. Battery: 100, costs 1/step, 2/move, 3/scan
