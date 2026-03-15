# Drone Rescuer

Drone Rescuer is a **self-healing rescue drone swarm simulation** where an autonomous AI Command Agent orchestrates a fleet of drones to find survivors in a disaster zone — with zero cloud connectivity. All communication between the Agent (LLM) and Drones (simulation) flows through **Model Context Protocol (MCP)**.

**Hackathon Track:** Agentic AI (Decentralised Swarm Intelligence)

**SDG Alignment:** SDG 9 (Industry, Innovation, Infrastructure) + SDG 3 (Good Health & Well-being)

---

## What It Does

An LLM Commander orchestrates 4 drones across a 12x12 disaster zone grid to locate and triage 8 survivors with deteriorating health. The simulation is alive: aftershocks reshape terrain, rising water floods cells, and communication blackouts sever the link between the AI and its drones.

What makes this system genuinely decentralised: **drones are not puppets**. The LLM sets high-level strategy, but every drone carries local autonomy rules — continuing to scan, avoid danger, and follow pheromone gradients even when communication is severed. Survivors deteriorate at different rates based on severity, forcing real-time triage decisions that showcase the LLM's chain-of-thought reasoning depth.

The entire system is observable through a real-time Next.js dashboard with grid visualization, drone telemetry, reasoning logs, mesh network topology, mission timeline replay, and voice narration of critical events.

---

## Key Innovation: Two-Tier Intelligence

| Tier | Role | How It Works |
|------|------|-------------|
| **Tier 1 — LLM Commander** (Strategic) | Sector assignments, triage reasoning, digital twin planning, pheromone map analysis, swarm coordination | Communicates via MCP tool calls over Streamable HTTP |
| **Tier 2 — Drone Local Autonomy** (Tactical) | Continue scanning, auto-return at low battery, pheromone gradient navigation, mesh relay, buffer findings | Operates independently during blackouts — no LLM needed |

During a communication blackout, drones seamlessly switch to autonomous mode: following pheromone gradients (`score = survivor_nearby - 0.5*scanned - 2.0*danger`), auto-returning when battery drops below 15%, and buffering discoveries until connectivity is restored.

---

## Architecture

### System Architecture

```mermaid
flowchart TB
    subgraph Frontend["Next.js Dashboard :3000"]
        RC[React Components]
        ES[EventSource Client]
        REST_C[REST Fetch Helpers]
    end

    subgraph API["FastAPI Bridge :8001"]
        SSE["/api/stream (SSE)"]
        STATE["/api/state (REST)"]
        LOGS["/api/logs (REST)"]
        HIST["/api/history (REST)"]
        MESH_EP["/api/mesh (REST)"]
        START["/api/start (POST)"]
        STEP["/api/step (POST)"]
        BLACKOUT_EP["/api/blackout (POST)"]
    end

    subgraph Agent["LangGraph Agent"]
        LLM["GPT-5 mini (LLM)"]
        SG[StateGraph]
        SP[System Prompt + Triage Protocol]
    end

    subgraph MCP["MCP Server :8000/mcp"]
        TOOLS["17 @mcp.tool() endpoints"]
    end

    subgraph Sim["Mesa Simulation Engine"]
        MODEL[DisasterModel]
        GRID["12x12 MultiGrid"]
        DRONES[DroneAgents]
        SURVIVORS[SurvivorAgents]
        PL[PropertyLayers]
        DYN[Dynamic Disasters]
    end

    RC -->|"SSE subscribe"| SSE
    RC -->|"HTTP GET/POST"| STATE
    ES -->|"EventSource"| SSE

    API -->|"reads state"| MODEL

    SG -->|"MCP tool calls (HTTP)"| TOOLS
    TOOLS -->|"direct Python calls"| MODEL

    START -->|"launches"| SG
    STEP -->|"advance_simulation"| MODEL

    MODEL --- GRID
    MODEL --- DRONES
    MODEL --- SURVIVORS
    MODEL --- PL
    MODEL --- DYN
```

### Two-Tier Intelligence Flow

```mermaid
flowchart TB
    subgraph Tier1["Tier 1 — LLM Commander (Strategic)"]
        SA[Sector Assignments]
        TR[Triage Reasoning]
        DT[Digital Twin Planning]
        PMA[Pheromone Map Analysis]
        SC[Swarm Coordination]
    end

    subgraph MCP_Layer["MCP Protocol Layer"]
        TC["MCP Tool Calls<br>(Streamable HTTP)"]
    end

    subgraph Tier2["Tier 2 — Drone Local Autonomy (Tactical)"]
        CS[Continue Scanning Sector]
        AR["Auto-Return<br>(battery < 15%)"]
        PG["Pheromone Gradient<br>Navigation"]
        MR[Mesh Relay Attempt]
        BF[Buffer Findings]
    end

    SA --> TC
    TR --> TC
    DT --> TC
    PMA --> TC
    SC --> TC

    TC --> CS
    TC --> AR
    TC --> PG
    TC --> MR
    TC --> BF

    BLACKOUT["Communication<br>Blackout"] -.->|"severs link"| TC
    BLACKOUT -.->|"activates"| Tier2

    PG -->|"score = survivor_nearby<br>- 0.5*scanned<br>- 2.0*danger"| NAV[Navigation Decision]
```

### Mission Step Lifecycle

```mermaid
sequenceDiagram
    participant Agent as LangGraph Agent
    participant MCP as MCP Server
    participant Mesa as Mesa Simulation
    participant API as FastAPI Bridge
    participant UI as Next.js Dashboard

    Agent->>Agent: Reason (CoT) over current state
    Agent->>MCP: MCP tool call (e.g., move_to, thermal_scan)
    MCP->>Mesa: Direct Python function call
    Mesa->>Mesa: Update grid, agents, pheromones
    Mesa-->>MCP: Return result (scan data, battery, etc.)
    MCP-->>Agent: Tool call response

    Agent->>MCP: advance_simulation()
    MCP->>Mesa: model.step()
    Mesa->>Mesa: Decay pheromones, drain health, trigger disasters
    Mesa-->>MCP: Updated state

    API->>Mesa: Poll / read state
    API-->>UI: SSE event: "state" (grid snapshot)
    API-->>UI: SSE event: "logs" (agent reasoning)
    API-->>UI: SSE event: "disaster" (if triggered)
    API-->>UI: SSE event: "blackout" (if active)

    UI->>UI: Render grid, panels, logs
    UI->>UI: Store snapshot for timeline replay
```

### Pheromone System

```mermaid
flowchart TB
    subgraph Layers["Three Pheromone PropertyLayers"]
        subgraph Scanned["scanned (repulsive)"]
            S_DEP["Deposit: drone completes scan"]
            S_EFF["Effect: -0.5 weight<br>(drones avoid re-scanning)"]
        end
        subgraph Survivor["survivor_nearby (attractive)"]
            SN_DEP["Deposit: survivor detected<br>(boosts cell + neighbors)"]
            SN_EFF["Effect: +1.0 weight<br>(drones converge)"]
        end
        subgraph Danger["danger (strongly repulsive)"]
            D_DEP["Deposit: aftershock or<br>rising water event"]
            D_EFF["Effect: -2.0 weight<br>(drones strongly avoid)"]
        end
    end

    DECAY["Global Decay<br>0.9x per step<br>(all three layers)"]

    Scanned --> DECAY
    Survivor --> DECAY
    Danger --> DECAY

    subgraph Navigation["Drone Navigation Score"]
        FORMULA["score = survivor_nearby<br>        - 0.5 * scanned<br>        - 2.0 * danger"]
        BEST["Move to neighbor<br>with highest score"]
    end

    S_EFF --> FORMULA
    SN_EFF --> FORMULA
    D_EFF --> FORMULA
    FORMULA --> BEST

    NOTE["Works during blackouts<br>No LLM involvement needed"]
    BEST --- NOTE
```

### Triage Decision Tree

```mermaid
flowchart TB
    START["Multiple Survivors<br>Detected"] --> CHECK_CRIT{"Severity?"}

    CHECK_CRIT -->|"CRITICAL"| CRIT_HEALTH{"Health level?"}
    CHECK_CRIT -->|"MODERATE"| MOD_HEALTH{"Health < 40%?"}
    CHECK_CRIT -->|"STABLE"| STABLE["Priority: LOW<br>(health drain: 0.01/step<br>~100 steps to expire)"]

    CRIT_HEALTH -->|"< 30%"| P1["Priority: IMMEDIATE<br>Respond this step<br>(health drain: 0.05/step<br>~20 steps to expire)"]
    CRIT_HEALTH -->|"30% - 60%"| P2["Priority: HIGH<br>Respond within 2-3 steps"]
    CRIT_HEALTH -->|"> 60%"| P2B["Priority: HIGH<br>Monitor closely"]

    MOD_HEALTH -->|"Yes"| P3["Priority: MEDIUM-HIGH<br>(health drain: 0.02/step<br>~50 steps to expire)"]
    MOD_HEALTH -->|"No"| P4["Priority: MEDIUM<br>Schedule when available"]

    P1 --> TIEBREAK
    P2 --> TIEBREAK
    P2B --> TIEBREAK
    P3 --> TIEBREAK
    P4 --> TIEBREAK
    STABLE --> TIEBREAK

    TIEBREAK{"Equal urgency<br>tie-break?"} -->|"Yes"| CLOSEST["Assign drone<br>closest to survivor"]
    TIEBREAK -->|"No"| ASSIGN["Assign by<br>priority rank"]

    CLOSEST --> DISPATCH["Dispatch Drone<br>via move_to()"]
    ASSIGN --> DISPATCH

    DISPATCH --> DIGITAL_TWIN["simulate_mission()<br>Verify: battery sufficient?<br>Can return to base?"]
    DIGITAL_TWIN -->|"feasible"| EXECUTE["Execute Mission"]
    DIGITAL_TWIN -->|"not feasible"| REASSIGN["Reassign to<br>closer drone or<br>defer rescue"]
```

### Mesh Network & Self-Healing

```mermaid
flowchart TB
    NORMAL["Normal Operation<br>Drones connected<br>comm_range = 4 (Manhattan)"] -->|"blackout triggered"| BLACKOUT

    subgraph BLACKOUT["Blackout Zone"]
        DISC["Drones in zone:<br>connected = False"]
        AUTO["Activate Autonomous Mode<br>• Continue sector scan<br>• Follow pheromone gradients<br>• Auto-return if battery < 15%"]
        BUFF["Buffer findings locally<br>(findings_buffer)"]
    end

    DISC --> AUTO
    AUTO --> BUFF

    BUFF -->|"Agent deploys relay"| RELAY["deploy_as_relay()<br>Low-battery drone becomes<br>stationary relay (range = 6)"]

    RELAY --> RECOMPUTE["Topology Recomputation<br>Detect restored relay paths"]

    RECOMPUTE -->|"path found"| SYNC["sync_findings()<br>Flush buffered data<br>to command"]

    RECOMPUTE -->|"still isolated"| BUFF

    SYNC --> RECOVERED["Connected State Restored<br>Agent receives buffered<br>survivor/scan data"]

    subgraph Resilience["Network Resilience Analysis"]
        R1[Connectivity ratio]
        R2[Average path length]
        R3[Isolated drone count]
        R4[Relay coverage]
    end

    RECOMPUTE --> Resilience
```

---

## Tech Stack

| Layer | Technology | Port |
|---|---|---|
| Simulation Engine | Mesa 3 (Python) | — |
| MCP Server | FastMCP (`mcp` SDK, Streamable HTTP) | `localhost:8000/mcp` |
| Agent Brain | LangChain + LangGraph + `langchain-mcp-adapters` | — |
| LLM | OpenAI GPT-5 mini (`gpt-5-mini`) via `langchain-openai` | — |
| API Bridge | FastAPI (SSE streaming + REST) | `localhost:8001` |
| Frontend | Next.js 14+ (App Router) + React + TypeScript + Tailwind | `localhost:3000` |

---

## Features

- **Stigmergy / Pheromone System** — Three pheromone layers (`scanned`, `survivor_nearby`, `danger`) enable implicit swarm coordination. Drones follow pheromone gradients autonomously — no centralized control needed. All pheromones decay 0.9x per step.

- **Bayesian Heatmap** — 12x12 probability grid initialized from terrain priors (buildings=0.7, roads=0.5, open=0.3). Updated in real-time: positive scan hits boost cell + neighbors, misses halve probability (floor 0.05).

- **Digital Twin (`simulate_mission`)** — Predicts battery cost, arrival battery, return feasibility, and survivor probability *before* committing a drone. Enables chain-of-thought planning.

- **Mesh Network & Self-Healing** — Drones communicate within `comm_range=4` (Manhattan distance). Blackout zones force autonomous mode. Disconnected drones buffer findings. Self-healing via topology recomputation detects restored relay paths and triggers `sync_findings()`. Low-battery drones can be sacrificed as stationary relays (`comm_range=6`).

- **Triage Protocol** — LLM reasons through survivor priority: CRITICAL + low health = immediate, MODERATE = medium, STABLE = low. Equal urgency ties broken by proximity. Digital twin validates feasibility before dispatch.

- **Dynamic Disasters** — Aftershocks (~every 10 steps) convert terrain to DEBRIS and deposit danger pheromone. Rising water (~every 15 steps) expands WATER cells and threatens nearby survivors.

- **Timeline Replay** — Every simulation step is recorded. Scrub through the entire mission with the timeline slider to review decisions and outcomes.

- **Voice Narration** — Browser SpeechSynthesis reads critical log entries aloud. Toggle on/off from the control panel.

---

## MCP Tools (17 total)

**Core (11):**

| Tool | Description |
|------|-------------|
| `discover_drones` | List active drones and their status |
| `move_to` | Move a drone to a target cell |
| `thermal_scan` | Scan cells around a drone for survivors |
| `get_battery_status` | Check a drone's battery level |
| `get_priority_map` | Get the Bayesian heatmap |
| `simulate_mission` | Digital twin prediction before committing |
| `sync_findings` | Sync buffered data from disconnected drones |
| `trigger_blackout` | Force a communication blackout zone |
| `recall_drone` | Return a drone to base |
| `get_mission_summary` | Mission statistics and progress |
| `advance_simulation` | Step the simulation forward |

**Innovation (6):**

| Tool | Description |
|------|-------------|
| `get_pheromone_map` | Read pheromone layer data |
| `get_disaster_events` | List active disaster events |
| `assess_survivor` | Get detailed survivor triage info |
| `deploy_as_relay` | Convert a drone into a stationary relay |
| `get_network_resilience` | Mesh health metrics and coverage |
| `coordinate_swarm` | Issue multi-drone coordinated orders |

---

## Project Structure

```
drone-agents/
├── CLAUDE.md                  # Project instructions
├── prd.md                     # Product requirements document
├── architecture.md            # Mermaid architecture diagrams
├── plan.md                    # Implementation plan (6 stages)
├── requirements.txt           # Python dependencies
├── simulation/
│   ├── __init__.py
│   ├── model.py               # DisasterModel (grid, terrain, heatmap, pheromones, disasters)
│   ├── agents.py              # DroneAgent (local autonomy), SurvivorAgent (health decay)
│   ├── mesh_network.py        # Mesh topology, blackout, relay, resilience analysis
│   └── state.py               # Shared model singleton (used by MCP + bridge)
├── mcp_server/
│   ├── __init__.py
│   └── server.py              # FastMCP server — 17 @mcp.tool() definitions
├── agent/
│   ├── __init__.py
│   ├── graph.py               # LangGraph StateGraph (MessagesState)
│   ├── prompts.py             # System prompt with triage protocol
│   └── runner.py              # Entry point: MCP client → agent loop
├── api/
│   ├── __init__.py
│   └── bridge.py              # FastAPI: SSE /api/stream, REST /api/state, /api/logs, /api/history
├── dashboard/                 # Next.js app
│   ├── app/
│   │   ├── page.tsx           # 4-panel layout + timeline slider
│   │   └── layout.tsx         # Dark theme layout
│   ├── components/
│   │   ├── GridMap.tsx         # 12x12 grid, heatmap overlay, pheromones, drone markers
│   │   ├── DronePanel.tsx     # Battery bars, status, survivor health bars
│   │   ├── MeshGraph.tsx      # SVG network topology (force-directed)
│   │   ├── ReasoningLog.tsx   # Color-coded CoT log + SpeechSynthesis voice narration
│   │   ├── ControlPanel.tsx   # Start, blackout, step, voice toggle, reset
│   │   └── TimelineSlider.tsx # Mission replay scrubber (rewind to any step)
│   └── lib/
│       └── api.ts             # SSE client (EventSource) + REST fetch helpers
├── scripts/
│   ├── run_all.sh             # Start all 4 services
│   └── demo.py                # Scripted 5-act demo sequence
└── logs/
    └── mission_log.json       # Persisted agent reasoning + tool calls
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI API key

### Install Dependencies

```bash
# Python (from project root)
pip install "mcp[cli]" mesa langchain-mcp-adapters langgraph langchain-openai langchain fastapi uvicorn numpy

# Frontend
cd dashboard
npm install
```

### Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-xxxxx
MCP_SERVER_URL=http://localhost:8000/mcp
API_BRIDGE_URL=http://localhost:8001
```

### Start All Services

**Option A: One command (recommended)**

```bash
bash scripts/run_all.sh
```

This starts all 4 services (MCP Server, API Bridge, Agent Runner, Dashboard) and prints their URLs. Press `Ctrl+C` to stop everything.

**Option B: Manual (4 terminals)**

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

---

## Demo

A scripted 5-act demo drives the simulation through a compelling narrative:

| Act | Title | What Happens |
|-----|-------|-------------|
| 1 | Discovery | LLM Commander discovers drones, analyzes the zone, deploys the swarm |
| 2 | The Living Disaster | Drones scan the grid, find survivors, aftershocks reshape terrain |
| 3 | Communication Crisis | Blackout at zone (8,8) — drones lose contact and go autonomous |
| 4 | Race Against Time | Battery dropping, survivors losing health, critical triage decisions |
| 5 | Mission Complete | Final results, timeline replay, voice narration |

```bash
# Prerequisite: all services running (run_all.sh or manual)
python scripts/demo.py
```

The demo pauses between acts for live narration. Open the dashboard at `http://localhost:3000` to watch in real-time.

---

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

---

## Dashboard

The Next.js dashboard provides 6 React components for real-time mission observation:

| Component | What It Shows |
|-----------|--------------|
| **GridMap** | 12x12 grid with terrain coloring, Bayesian heatmap overlay, pheromone visualization, drone markers with movement trails, survivor indicators, and scan pulse animations |
| **DronePanel** | Battery level bars, drone status (active/returning/relay/autonomous), position, and survivor health bars for found survivors |
| **MeshGraph** | Force-directed SVG graph showing drone-to-drone communication links, relay nodes, and blackout zone overlay |
| **ReasoningLog** | Color-coded scrolling log of the LLM's chain-of-thought reasoning, tool calls, and triage decisions. Critical entries trigger voice narration |
| **ControlPanel** | Start mission, trigger blackout, advance steps, toggle voice narration, reset simulation |
| **TimelineSlider** | Scrub through recorded mission history step-by-step with live/replay mode toggle |

---

## How It Works

Each mission step follows this cycle:

1. **Reason** — The LangGraph agent analyzes current state (drone positions, battery, heatmap, pheromones, known survivors)
2. **Act** — The agent issues MCP tool calls: move drones, scan cells, assess survivors, coordinate the swarm
3. **Simulate** — The Mesa engine processes actions: update grid, deposit pheromones, update Bayesian heatmap
4. **Advance** — `advance_simulation()` ticks the world: decay pheromones, drain survivor health, trigger random disasters, recompute mesh topology
5. **Observe** — FastAPI bridge streams updated state to the dashboard via SSE
6. **Repeat** — Agent loops back to reasoning with new information, until all survivors are found or resources are exhausted
