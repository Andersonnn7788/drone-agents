# Architecture — Drone Swarm Rescue Simulation

Visual architecture for the self-healing rescue drone swarm simulation.

---

## 1. System Architecture

High-level service topology with ports and protocols.

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

---

## 2. Two-Tier Intelligence Flow

Strategic LLM decisions flow down via MCP; tactical drone autonomy operates independently.

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

---

## 3. Mesa Simulation Internals

Components within the DisasterModel.

```mermaid
flowchart TB
    subgraph DM["DisasterModel"]
        subgraph Grid["12x12 MultiGrid (torus=False)"]
            BUILDING["BUILDING<br>(prob 0.7)"]
            ROAD["ROAD<br>(prob 0.5)"]
            OPEN["OPEN<br>(prob 0.3)"]
            WATER["WATER"]
            DEBRIS["DEBRIS"]
        end

        subgraph Agents_Layer["Agents"]
            DA["DroneAgents (4-5)<br>Battery: 100<br>Start: (0,0)"]
            SVA["SurvivorAgents (8)<br>Severity: CRITICAL / MODERATE / STABLE"]
        end

        subgraph PL["PropertyLayers"]
            BH["Bayesian Heatmap<br>(12x12 probability grid)"]
            PS["scanned (repulsive)<br>decay: 0.9x/step"]
            PN["survivor_nearby (attractive)<br>decay: 0.9x/step"]
            PD["danger (strongly repulsive)<br>decay: 0.9x/step"]
        end

        subgraph DD["Dynamic Disasters"]
            AQ[Aftershocks]
            RW[Rising Water]
            TRC[Terrain Reshaping]
        end
    end

    DA -->|"move: -2 battery<br>scan: -3 battery<br>step: -1 battery"| Grid
    SVA -->|"CRITICAL: -0.05/step<br>MODERATE: -0.02/step<br>STABLE: -0.01/step"| Grid
    DD -->|"modify terrain"| Grid
    DA -->|"deposit/read"| PL
    BH -->|"scan hit → boost<br>scan miss → halve (floor 0.05)"| Grid
```

---

## 4. MCP Tool Categories

17 tools organized by category.

```mermaid
flowchart LR
    subgraph Core["Core Tools (11)"]
        discover_drones["discover_drones<br>List active drones"]
        move_to["move_to<br>Move drone to cell"]
        thermal_scan["thermal_scan<br>Scan cell for survivors"]
        get_battery["get_battery_status<br>Drone battery level"]
        get_priority["get_priority_map<br>Bayesian heatmap"]
        simulate["simulate_mission<br>Digital twin prediction"]
        sync["sync_findings<br>Sync buffered data"]
        trigger_blackout["trigger_blackout<br>Force comm blackout"]
        recall["recall_drone<br>Return drone to base"]
        get_summary["get_mission_summary<br>Mission statistics"]
        advance["advance_simulation<br>Step simulation forward"]
    end

    subgraph Innovation["Innovation Tools (6)"]
        pheromone["get_pheromone_map<br>Pheromone layer data"]
        disaster["get_disaster_events<br>Active disaster list"]
        assess["assess_survivor<br>Survivor triage info"]
        relay["deploy_as_relay<br>Convert drone to relay"]
        resilience["get_network_resilience<br>Mesh health metrics"]
        coordinate["coordinate_swarm<br>Multi-drone orders"]
    end

    AGENT["LangGraph Agent"] -->|"MCP HTTP"| Core
    AGENT -->|"MCP HTTP"| Innovation
    Core -->|"Python calls"| MESA["Mesa Simulation"]
    Innovation -->|"Python calls"| MESA
```

---

## 5. Drone Agent State Machine

Drone lifecycle states and transitions.

```mermaid
stateDiagram-v2
    [*] --> Active: Mission Start

    Active --> Returning: battery < 15%
    Active --> Relay: deploy_as_relay()
    Active --> Autonomous: blackout / disconnected
    Active --> Scanning: thermal_scan()

    Scanning --> Active: scan complete

    Autonomous --> Active: connection restored
    Autonomous --> Returning: battery < 15%

    Returning --> Charging: reached base (0,0)

    Charging --> Active: battery recharged

    Relay --> [*]: stationary relay<br>(mission end)

    Active --> [*]: mission complete
```

---

## 6. Mission Step Lifecycle

Sequence of events during a single simulation step.

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

---

## 7. Mesh Network & Self-Healing

How the mesh network responds to blackouts and recovers.

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

## 8. Data Flow: SSE Streaming

How state flows from simulation to the user's browser.

```mermaid
flowchart LR
    subgraph Mesa["Mesa Simulation"]
        MS[Model State]
        AL[Agent Logs]
        DE[Disaster Events]
        BZ[Blackout Zones]
    end

    subgraph Bridge["FastAPI Bridge :8001"]
        POLL["State Poller"]
        SSE_GEN["SSE Generator<br>(GET /api/stream)"]
        REST_EP["REST Endpoints<br>(GET /api/state)<br>(GET /api/logs)<br>(GET /api/history)<br>(GET /api/mesh)"]
    end

    subgraph Dashboard["Next.js Dashboard :3000"]
        EVS["EventSource<br>Client"]
        subgraph Components["React Components"]
            GM[GridMap.tsx]
            DP[DronePanel.tsx]
            MG[MeshGraph.tsx]
            RL[ReasoningLog.tsx]
            CP[ControlPanel.tsx]
            TS[TimelineSlider.tsx]
        end
        SNAP["State Snapshot<br>History (for replay)"]
    end

    MS --> POLL
    AL --> POLL
    DE --> POLL
    BZ --> POLL

    POLL --> SSE_GEN
    POLL --> REST_EP

    SSE_GEN -->|"event: state"| EVS
    SSE_GEN -->|"event: logs"| EVS
    SSE_GEN -->|"event: disaster"| EVS
    SSE_GEN -->|"event: blackout"| EVS

    REST_EP -->|"HTTP GET (fallback)"| Components

    EVS --> GM
    EVS --> DP
    EVS --> MG
    EVS --> RL

    GM --> SNAP
    TS -->|"scrub to step N"| SNAP
```

---

## 9. Pheromone System

Three pheromone layers, their triggers, decay, and effect on drone navigation.

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

---

## 10. Triage Decision Tree

Priority protocol when multiple survivors are found.

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

---

## Quick Reference

| Service | Port | Protocol |
|---|---|---|
| MCP Server | `:8000/mcp` | Streamable HTTP |
| FastAPI Bridge | `:8001` | SSE + REST |
| Next.js Dashboard | `:3000` | HTTP |
| Base Station | Grid `(0,0)` | — |

| Resource | Cost |
|---|---|
| Idle step | 1 battery |
| Move | 2 battery |
| Thermal scan | 3 battery |
| Auto-return threshold | < 15% battery |
| Relay comm range | 6 (vs normal 4) |
