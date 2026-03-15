# Architecture — Drone Swarm Rescue Simulation

Visual architecture reference for the self-healing rescue drone swarm simulation. All diagrams use [Mermaid](https://mermaid.js.org/) syntax and render on GitHub, VS Code (with Mermaid extension), and most modern Markdown previewers.

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
        TC["MCP Tool Calls\n(Streamable HTTP)"]
    end

    subgraph Tier2["Tier 2 — Drone Local Autonomy (Tactical)"]
        CS[Continue Scanning Sector]
        AR["Auto-Return\n(battery < 15%)"]
        PG["Pheromone Gradient\nNavigation"]
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

    BLACKOUT["Communication\nBlackout"] -.->|"severs link"| TC
    BLACKOUT -.->|"activates"| Tier2

    PG -->|"score = survivor_nearby\n- 0.5*scanned\n- 2.0*danger"| NAV[Navigation Decision]
```

---

## 3. Mesa Simulation Internals

Components within the DisasterModel.

```mermaid
flowchart TB
    subgraph DM["DisasterModel"]
        subgraph Grid["12x12 MultiGrid (torus=False)"]
            BUILDING["BUILDING\n(prob 0.7)"]
            ROAD["ROAD\n(prob 0.5)"]
            OPEN["OPEN\n(prob 0.3)"]
            WATER["WATER"]
            DEBRIS["DEBRIS"]
        end

        subgraph Agents_Layer["Agents"]
            DA["DroneAgents (4-5)\nBattery: 100\nStart: (0,0)"]
            SVA["SurvivorAgents (8)\nSeverity: CRITICAL / MODERATE / STABLE"]
        end

        subgraph PL["PropertyLayers"]
            BH["Bayesian Heatmap\n(12x12 probability grid)"]
            PS["scanned (repulsive)\ndecay: 0.9x/step"]
            PN["survivor_nearby (attractive)\ndecay: 0.9x/step"]
            PD["danger (strongly repulsive)\ndecay: 0.9x/step"]
        end

        subgraph DD["Dynamic Disasters"]
            AQ[Aftershocks]
            RW[Rising Water]
            TRC[Terrain Reshaping]
        end
    end

    DA -->|"move: -2 battery\nscan: -3 battery\nstep: -1 battery"| Grid
    SVA -->|"CRITICAL: -0.05/step\nMODERATE: -0.02/step\nSTABLE: -0.01/step"| Grid
    DD -->|"modify terrain"| Grid
    DA -->|"deposit/read"| PL
    BH -->|"scan hit → boost\nscan miss → halve (floor 0.05)"| Grid
```

---

## 4. MCP Tool Categories

17 tools organized by category.

```mermaid
flowchart LR
    subgraph Core["Core Tools (11)"]
        discover_drones["discover_drones\nList active drones"]
        move_to["move_to\nMove drone to cell"]
        thermal_scan["thermal_scan\nScan cell for survivors"]
        get_battery["get_battery_status\nDrone battery level"]
        get_priority["get_priority_map\nBayesian heatmap"]
        simulate["simulate_mission\nDigital twin prediction"]
        sync["sync_findings\nSync buffered data"]
        trigger_blackout["trigger_blackout\nForce comm blackout"]
        recall["recall_drone\nReturn drone to base"]
        get_summary["get_mission_summary\nMission statistics"]
        advance["advance_simulation\nStep simulation forward"]
    end

    subgraph Innovation["Innovation Tools (6)"]
        pheromone["get_pheromone_map\nPheromone layer data"]
        disaster["get_disaster_events\nActive disaster list"]
        assess["assess_survivor\nSurvivor triage info"]
        relay["deploy_as_relay\nConvert drone to relay"]
        resilience["get_network_resilience\nMesh health metrics"]
        coordinate["coordinate_swarm\nMulti-drone orders"]
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

    Relay --> [*]: stationary relay\n(mission end)

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
    NORMAL["Normal Operation\nDrones connected\ncomm_range = 4 (Manhattan)"] -->|"blackout triggered"| BLACKOUT

    subgraph BLACKOUT["Blackout Zone"]
        DISC["Drones in zone:\nconnected = False"]
        AUTO["Activate Autonomous Mode\n• Continue sector scan\n• Follow pheromone gradients\n• Auto-return if battery < 15%"]
        BUFF["Buffer findings locally\n(findings_buffer)"]
    end

    DISC --> AUTO
    AUTO --> BUFF

    BUFF -->|"Agent deploys relay"| RELAY["deploy_as_relay()\nLow-battery drone becomes\nstationary relay (range = 6)"]

    RELAY --> RECOMPUTE["Topology Recomputation\nDetect restored relay paths"]

    RECOMPUTE -->|"path found"| SYNC["sync_findings()\nFlush buffered data\nto command"]

    RECOMPUTE -->|"still isolated"| BUFF

    SYNC --> RECOVERED["Connected State Restored\nAgent receives buffered\nsurvivor/scan data"]

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
        SSE_GEN["SSE Generator\n(GET /api/stream)"]
        REST_EP["REST Endpoints\n(GET /api/state)\n(GET /api/logs)\n(GET /api/history)\n(GET /api/mesh)"]
    end

    subgraph Dashboard["Next.js Dashboard :3000"]
        EVS["EventSource\nClient"]
        subgraph Components["React Components"]
            GM[GridMap.tsx]
            DP[DronePanel.tsx]
            MG[MeshGraph.tsx]
            RL[ReasoningLog.tsx]
            CP[ControlPanel.tsx]
            TS[TimelineSlider.tsx]
        end
        SNAP["State Snapshot\nHistory (for replay)"]
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
            S_EFF["Effect: -0.5 weight\n(drones avoid re-scanning)"]
        end
        subgraph Survivor["survivor_nearby (attractive)"]
            SN_DEP["Deposit: survivor detected\n(boosts cell + neighbors)"]
            SN_EFF["Effect: +1.0 weight\n(drones converge)"]
        end
        subgraph Danger["danger (strongly repulsive)"]
            D_DEP["Deposit: aftershock or\nrising water event"]
            D_EFF["Effect: -2.0 weight\n(drones strongly avoid)"]
        end
    end

    DECAY["Global Decay\n0.9x per step\n(all three layers)"]

    Scanned --> DECAY
    Survivor --> DECAY
    Danger --> DECAY

    subgraph Navigation["Drone Navigation Score"]
        FORMULA["score = survivor_nearby\n        - 0.5 * scanned\n        - 2.0 * danger"]
        BEST["Move to neighbor\nwith highest score"]
    end

    S_EFF --> FORMULA
    SN_EFF --> FORMULA
    D_EFF --> FORMULA
    FORMULA --> BEST

    NOTE["Works during blackouts\nNo LLM involvement needed"]
    BEST --- NOTE
```

---

## 10. Triage Decision Tree

Priority protocol when multiple survivors are found.

```mermaid
flowchart TB
    START["Multiple Survivors\nDetected"] --> CHECK_CRIT{"Severity?"}

    CHECK_CRIT -->|"CRITICAL"| CRIT_HEALTH{"Health level?"}
    CHECK_CRIT -->|"MODERATE"| MOD_HEALTH{"Health < 40%?"}
    CHECK_CRIT -->|"STABLE"| STABLE["Priority: LOW\n(health drain: 0.01/step\n~100 steps to expire)"]

    CRIT_HEALTH -->|"< 30%"| P1["Priority: IMMEDIATE\nRespond this step\n(health drain: 0.05/step\n~20 steps to expire)"]
    CRIT_HEALTH -->|"30% - 60%"| P2["Priority: HIGH\nRespond within 2-3 steps"]
    CRIT_HEALTH -->|"> 60%"| P2B["Priority: HIGH\nMonitor closely"]

    MOD_HEALTH -->|"Yes"| P3["Priority: MEDIUM-HIGH\n(health drain: 0.02/step\n~50 steps to expire)"]
    MOD_HEALTH -->|"No"| P4["Priority: MEDIUM\nSchedule when available"]

    P1 --> TIEBREAK
    P2 --> TIEBREAK
    P2B --> TIEBREAK
    P3 --> TIEBREAK
    P4 --> TIEBREAK
    STABLE --> TIEBREAK

    TIEBREAK{"Equal urgency\ntie-break?"} -->|"Yes"| CLOSEST["Assign drone\nclosest to survivor"]
    TIEBREAK -->|"No"| ASSIGN["Assign by\npriority rank"]

    CLOSEST --> DISPATCH["Dispatch Drone\nvia move_to()"]
    ASSIGN --> DISPATCH

    DISPATCH --> DIGITAL_TWIN["simulate_mission()\nVerify: battery sufficient?\nCan return to base?"]
    DIGITAL_TWIN -->|"feasible"| EXECUTE["Execute Mission"]
    DIGITAL_TWIN -->|"not feasible"| REASSIGN["Reassign to\ncloser drone or\ndefer rescue"]
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
