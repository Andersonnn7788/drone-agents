'use client';

import { useMemo, useRef } from 'react';
import {
  BlackoutZone,
  DroneState,
  SimState,
  SurvivorState,
  TerrainType,
} from '@/lib/api';

const GRID_SIZE = 12;

const TERRAIN_BG: Record<TerrainType, string> = {
  OPEN: 'bg-green-950',
  BUILDING: 'bg-gray-600',
  ROAD: 'bg-gray-400',
  WATER: 'bg-blue-800',
  DEBRIS: 'bg-amber-900',
};

const TERRAIN_BORDER: Record<TerrainType, string> = {
  OPEN: 'border-green-900',
  BUILDING: 'border-gray-500',
  ROAD: 'border-gray-300',
  WATER: 'border-blue-600',
  DEBRIS: 'border-amber-700',
};

const DRONE_COLORS: Record<string, string> = {
  drone_alpha: '#FFD700',
  drone_bravo: '#00FFFF',
  drone_charlie: '#FF8C00',
  drone_delta: '#A855F7',
};

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: '#ef4444',
  MODERATE: '#f97316',
  STABLE: '#22c55e',
};

function manhattanDistance(
  x1: number,
  y1: number,
  x2: number,
  y2: number
): number {
  return Math.abs(x1 - x2) + Math.abs(y1 - y2);
}

function isInBlackout(x: number, y: number, zones: BlackoutZone[]): boolean {
  return zones.some((z) => manhattanDistance(x, y, z.center[0], z.center[1]) <= z.radius);
}

interface GridMapProps {
  state: SimState | null;
  gridEffect?: 'aftershock' | 'water' | null;
}

export default function GridMap({ state, gridEffect }: GridMapProps) {
  // Build O(1) lookup maps from state
  const dronesByPos = useMemo<Map<string, DroneState[]>>(() => {
    const map = new Map<string, DroneState[]>();
    if (!state) return map;
    for (const drone of Object.values(state.drones)) {
      const key = `${drone.position[0]},${drone.position[1]}`;
      const existing = map.get(key) ?? [];
      map.set(key, [...existing, drone]);
    }
    return map;
  }, [state]);

  const survivorsByPos = useMemo<Map<string, SurvivorState[]>>(() => {
    const map = new Map<string, SurvivorState[]>();
    if (!state) return map;
    for (const s of state.survivors) {
      if (!s.position) continue;
      const key = `${s.position[0]},${s.position[1]}`;
      const existing = map.get(key) ?? [];
      map.set(key, [...existing, s]);
    }
    return map;
  }, [state]);

  const scannedSet = useMemo<Set<string>>(() => {
    if (!state) return new Set();
    return new Set(state.scanned_cells.map(([x, y]) => `${x},${y}`));
  }, [state]);

  // Track previously scanned cells for scan-pulse on fresh scans
  const prevScannedRef = useRef<Set<string>>(new Set());
  const freshlyScanned = useMemo(() => {
    const fresh = new Set<string>();
    for (const key of scannedSet) {
      if (!prevScannedRef.current.has(key)) fresh.add(key);
    }
    // Update ref after computing diff
    prevScannedRef.current = new Set(scannedSet);
    return fresh;
  }, [scannedSet]);

  // Compute disaster-affected cells for the current step
  const { floodedCells, aftershockCells } = useMemo(() => {
    const flooded = new Set<string>();
    const aftershock = new Set<string>();
    if (!state) return { floodedCells: flooded, aftershockCells: aftershock };
    for (const evt of state.disaster_events) {
      if (evt.step !== state.mission_step) continue;
      if (evt.type === 'rising_water' && evt.flooded_cells) {
        for (const [x, y] of evt.flooded_cells) flooded.add(`${x},${y}`);
      }
      if (evt.type === 'aftershock' && evt.affected_cells) {
        for (const [x, y] of evt.affected_cells) aftershock.add(`${x},${y}`);
      }
    }
    return { floodedCells: flooded, aftershockCells: aftershock };
  }, [state]);

  if (!state) {
    return (
      <div className="bg-gray-900 rounded border border-gray-800 p-2 flex items-center justify-center">
        <span className="text-gray-600 text-sm">Connecting to simulation...</span>
      </div>
    );
  }

  const cells: React.ReactNode[] = [];

  // Render rows from y=GRID_SIZE-1 down to y=0 so (0,0) is at visual bottom-left
  for (let y = GRID_SIZE - 1; y >= 0; y--) {
    for (let x = 0; x < GRID_SIZE; x++) {
      const terrain = state.terrain[y]?.[x] ?? 'OPEN';
      const heat = state.heatmap[y]?.[x] ?? 0;
      const posKey = `${x},${y}`;
      const drones = dronesByPos.get(posKey) ?? [];
      const survivors = survivorsByPos.get(posKey) ?? [];
      const isScanned = scannedSet.has(posKey);
      const inBlackout = isInBlackout(x, y, state.blackout_zones);
      const isBase = x === 0 && y === 0;

      cells.push(
        <div
          key={posKey}
          className={`relative border ${TERRAIN_BG[terrain]} ${TERRAIN_BORDER[terrain]}`}
          style={{ minWidth: 0, minHeight: 0 }}
          title={`(${x},${y}) ${terrain}`}
        >
          {/* Heatmap overlay */}
          {heat > 0.05 && (
            <div
              className="absolute inset-0 pointer-events-none"
              style={{ background: `rgba(220,38,38,${Math.min(heat * 0.6, 0.85)})` }}
            />
          )}

          {/* Scanned overlay */}
          {isScanned && (
            <div className="absolute inset-0 ring-1 ring-inset ring-white/15 bg-white/5 pointer-events-none" />
          )}

          {/* Scan-pulse on freshly scanned cells */}
          {freshlyScanned.has(posKey) && (
            <div className="absolute inset-0 pointer-events-none scan-pulse" style={{ background: 'rgba(34,211,238,0.3)' }} />
          )}

          {/* Water expansion overlay */}
          {floodedCells.has(posKey) && (
            <div className="absolute inset-0 pointer-events-none water-expansion z-20" />
          )}

          {/* Aftershock cell flash */}
          {aftershockCells.has(posKey) && (
            <div className="absolute inset-0 pointer-events-none aftershock-cell-flash z-20" />
          )}

          {/* Blackout overlay */}
          {inBlackout && (
            <div className="absolute inset-0 bg-purple-950/50 pointer-events-none" />
          )}

          {/* Base station marker */}
          {isBase && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-20">
              <span className="text-[6px] font-bold text-yellow-300 leading-none">BASE</span>
            </div>
          )}

          {/* Drone markers */}
          {drones.map((d, i) => (
            <div
              key={d.drone_id}
              className={`absolute rounded-full z-10 ${!d.connected ? 'blink' : ''}`}
              style={{
                width: 9,
                height: 9,
                background: DRONE_COLORS[d.drone_id] ?? '#ffffff',
                top: 2 + i * 4,
                left: 2 + i * 4,
                border: d.is_relay ? '2px solid rgba(255,255,255,0.9)' : '1px solid rgba(0,0,0,0.4)',
                boxShadow: `0 0 4px ${DRONE_COLORS[d.drone_id] ?? '#fff'}80`,
              }}
            />
          ))}

          {/* Survivor indicators */}
          {survivors.map((s, i) => (
            <div
              key={s.survivor_id}
              className="absolute rounded-full z-10"
              style={{
                width: 5,
                height: 5,
                background: !s.alive ? '#6b7280' : SEVERITY_COLORS[s.severity] ?? '#fff',
                bottom: 2 + i * 6,
                right: 2,
                opacity: s.alive ? 1 : 0.5,
              }}
            />
          ))}
        </div>
      );
    }
  }

  return (
    <div className="bg-gray-900 rounded border border-gray-800 p-2 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-1.5 flex-shrink-0">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Grid Map
        </h2>
        <span className="text-[10px] text-gray-600">
          Step {state.mission_step} &middot; {state.stats.coverage_pct}% covered
        </span>
      </div>

      <div
        className={`flex-1 min-h-0 ${gridEffect === 'aftershock' ? 'aftershock-shake' : ''}`}
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${GRID_SIZE}, 1fr)`,
          gridTemplateRows: `repeat(${GRID_SIZE}, 1fr)`,
        }}
      >
        {cells}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 flex-shrink-0">
        {(Object.entries(TERRAIN_BG) as [TerrainType, string][]).map(([t, cls]) => (
          <span key={t} className="flex items-center gap-1 text-[9px] text-gray-500">
            <span className={`inline-block w-2 h-2 rounded-sm ${cls}`} />
            {t}
          </span>
        ))}
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-sm bg-red-600 opacity-60" />
          Heatmap
        </span>
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-sm bg-purple-900" />
          Blackout
        </span>
      </div>
    </div>
  );
}
