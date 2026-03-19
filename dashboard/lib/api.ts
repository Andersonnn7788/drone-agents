// ── Domain types ─────────────────────────────────────────────────────────────

export type TerrainType = 'OPEN' | 'BUILDING' | 'ROAD' | 'WATER' | 'DEBRIS';

export type DroneStatus = 'active' | 'returning' | 'charging' | 'relay' | 'dead';

export type Severity = 'CRITICAL' | 'MODERATE' | 'STABLE';

export type LogType =
  | 'reasoning'
  | 'tool_call'
  | 'result'
  | 'triage'
  | 'narrative'
  | 'system'
  | 'warning'
  | 'error'
  | 'reflection';

export interface DroneState {
  drone_id: string;
  position: [number, number];
  battery: number;
  status: DroneStatus;
  connected: boolean;
  is_relay: boolean;
  comm_range: number;
  assigned_sector: [number, number, number, number] | null;
  findings_buffer_size: number;
}

export interface SurvivorState {
  survivor_id: number;
  position: [number, number] | null;
  severity: Severity;
  health: number;
  found: boolean;
  rescued: boolean;
  alive: boolean;
}

export interface Pheromones {
  scanned: number[][];
  survivor_nearby: number[][];
  danger: number[][];
}

export interface BlackoutZone {
  center: [number, number];
  radius: number;
}

export interface DisasterEvent {
  type: 'aftershock' | 'rising_water' | 'blackout' | 'blackout_cleared';
  step: number;
  center?: [number, number];
  affected_cells?: [number, number][];
  source?: [number, number];
  flooded_cells?: [number, number][];
  radius?: number;
  affected_drones?: string[];
}

export interface WarningEvent {
  type: 'aftershock_warning' | 'rising_water_warning' | 'blackout_warning';
  step: number;
  estimated_center: [number, number];
  message: string;
  resolved: boolean;
}

export interface MissionStats {
  total_survivors: number;
  found: number;
  alive: number;
  rescued: number;
  active_drones: number;
  total_drones: number;
  cells_scanned: number;
  total_cells: number;
  coverage_pct: number;
}

export interface ScoreBreakdown {
  total: number;
  grade: string;
  rescue_points: number;
  speed_bonus: number;
  coverage_bonus: number;
  death_penalty: number;
  efficiency_bonus: number;
  rescues: number;
  rescue_events: Array<{
    survivor_id: number;
    severity: Severity;
    health_at_rescue: number;
    step: number;
    points: number;
    drone_id: string;
  }>;
}

export interface LessonLearned {
  lesson: string;
  evidence: string;
  priority: string;
  mission_num: number;
  mission_score: number;
  mission_grade: string;
}

export interface MissionCompleteData {
  mission_step: number;
  stats: MissionStats;
  disaster_event_count: number;
  status: string;
  score?: ScoreBreakdown;
}

export interface SimState {
  mission_step: number;
  base_position?: [number, number];
  terrain: TerrainType[][];
  drones: Record<string, DroneState>;
  survivors: SurvivorState[];
  heatmap: number[][];
  pheromones: Pheromones;
  scanned_cells: [number, number][];
  mesh_topology: Record<string, string[]>;
  disaster_events: DisasterEvent[];
  warning_events: WarningEvent[];
  blackout_zones: BlackoutZone[];
  stats: MissionStats;
  score?: ScoreBreakdown;
}

export interface LogEntry {
  step: number;
  timestamp: number;
  message: string;
  is_critical: boolean;
  type: LogType;
}

export interface HistoryResponse {
  total_steps: number;
  snapshots: { step: number; state: SimState }[];
}

// ── SSE connection ────────────────────────────────────────────────────────────

const API_BASE =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8001')
    : 'http://localhost:8001';

export interface SSEHandlers {
  onState: (state: SimState) => void;
  onLogs: (logs: LogEntry[]) => void;
  onDisaster: (event: DisasterEvent) => void;
  onBlackout: (event: DisasterEvent) => void;
  onMissionComplete: (data: MissionCompleteData) => void;
  onWarning: (event: WarningEvent) => void;
}

export function connectSSE(handlers: SSEHandlers): EventSource {
  const es = new EventSource(`${API_BASE}/api/stream`);

  es.addEventListener('state', (e) => {
    try {
      handlers.onState(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore malformed event
    }
  });

  es.addEventListener('logs', (e) => {
    try {
      handlers.onLogs(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  es.addEventListener('disaster', (e) => {
    try {
      handlers.onDisaster(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  es.addEventListener('blackout', (e) => {
    try {
      handlers.onBlackout(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  es.addEventListener('warning', (e) => {
    try {
      handlers.onWarning(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  es.addEventListener('mission_complete', (e) => {
    try {
      handlers.onMissionComplete(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  return es;
}

// ── REST helpers ──────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

// ── Gamification types ────────────────────────────────────────────────────────

export interface RescueToast {
  id: string;
  survivorId: number;
  severity: Severity;
  healthAtRescue: number;
  points: number;
  dismissing: boolean;
}

export interface GameScore {
  total: number;
  livesSaved: number;
  streak: number;
  lastRescueStep: number | null;
}

export const api = {
  getState: () => get<SimState>('/api/state'),
  getLogs: () => get<LogEntry[]>('/api/logs'),
  getHistory: () => get<HistoryResponse>('/api/history'),
  getScore: () => get<ScoreBreakdown>('/api/score'),
  getLessons: () => get<LessonLearned[]>('/api/lessons'),
  startMission: () => post<{ status: string; mission_step: number }>('/api/start'),
  step: (steps = 1) => post<{ steps_advanced: number; mission_step: number }>('/api/step', { steps }),
  triggerBlackout: (zone_x: number, zone_y: number, radius: number) =>
    post<DisasterEvent>('/api/blackout', { zone_x, zone_y, radius }),
  reset: (seed = 42) => post<{ status: string; seed: number }>('/api/reset', { seed }),
};
