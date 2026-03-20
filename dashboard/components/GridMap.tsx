'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BlackoutZone,
  DroneState,
  PendingRescue,
  SimState,
  SurvivorState,
  TerrainType,
  WarningEvent,
} from '@/lib/api';

const GRID_SIZE = 12;

const TERRAIN_BG: Record<TerrainType, string> = {
  OPEN: 'bg-green-500',
  BUILDING: 'bg-slate-600',
  ROAD: 'bg-gray-400',
  WATER: 'bg-blue-500',
  DEBRIS: 'bg-amber-700',
};

const TERRAIN_BORDER: Record<TerrainType, string> = {
  OPEN: 'border-green-400',
  BUILDING: 'border-slate-500',
  ROAD: 'border-gray-300',
  WATER: 'border-blue-400',
  DEBRIS: 'border-amber-600',
};

// Representative heatmap overlay opacity per terrain type (mirrors initial Bayesian priors)
const TERRAIN_HEAT_OVERLAY: Record<TerrainType, number> = {
  BUILDING: Math.min(0.7 * 0.6, 0.85), // 0.42
  ROAD:     Math.min(0.5 * 0.6, 0.85), // 0.30
  OPEN:     Math.min(0.3 * 0.6, 0.85), // 0.18
  WATER:    Math.min(0.1 * 0.6, 0.85), // 0.06
  DEBRIS:   Math.min(0.1 * 0.6, 0.85), // 0.06
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

/** Compute intermediate grid cells along a Manhattan path (X first, then Y). */
function computeGridPath(
  from: [number, number],
  to: [number, number]
): [number, number][] {
  const path: [number, number][] = [];
  let [cx, cy] = from;
  const dx = to[0] > cx ? 1 : -1;
  while (cx !== to[0]) {
    cx += dx;
    path.push([cx, cy]);
  }
  const dy = to[1] > cy ? 1 : -1;
  while (cy !== to[1]) {
    cy += dy;
    path.push([cx, cy]);
  }
  return path;
}

interface GridMapProps {
  state: SimState | null;
  gridEffect?: 'aftershock' | 'water' | null;
  isReplaying?: boolean;
  newlyFoundIds?: Set<number>;
  rescueBursts?: Map<number, [number, number]>;
  activeWarnings?: WarningEvent[];
  pendingRescues?: Map<number, PendingRescue>;
  onRescueArrived?: (survivorId: number) => void;
}

export default function GridMap({ state, gridEffect, isReplaying, newlyFoundIds, rescueBursts, activeWarnings, pendingRescues, onRescueArrived }: GridMapProps) {
  // Build O(1) lookup maps from state
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

  // Compute warning cell set from active (unresolved) warnings
  const warningCells = useMemo(() => {
    const set = new Set<string>();
    for (const w of activeWarnings ?? []) {
      if (w.resolved) continue;
      const [cx, cy] = w.estimated_center;
      for (let dx = -1; dx <= 1; dx++)
        for (let dy = -1; dy <= 1; dy++) {
          const nx = cx + dx, ny = cy + dy;
          if (nx >= 0 && nx < GRID_SIZE && ny >= 0 && ny < GRID_SIZE)
            set.add(`${nx},${ny}`);
        }
    }
    return set;
  }, [activeWarnings]);

  // Track grid container size for absolute drone positioning
  const gridRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [gridSize, setGridSize] = useState({ width: 0, height: 0 });

  // Track drone position history for trail rendering (last 40 positions per drone)
  const droneHistories = useRef<Record<string, [number, number][]>>({});
  const prevStepRef = useRef<number>(0);

  // Animated position queue system
  const displayPositions = useRef<Record<string, [number, number]>>({});
  const moveQueues = useRef<Record<string, [number, number][]>>({});
  const [renderTick, setRenderTick] = useState(0);

  // Refs for pending rescue arrival detection (avoid stale closures in setInterval)
  const pendingRescuesRef = useRef(pendingRescues);
  pendingRescuesRef.current = pendingRescues;
  const onRescueArrivedRef = useRef(onRescueArrived);
  onRescueArrivedRef.current = onRescueArrived;

  // Observe the wrapper to compute square size = min(wrapperWidth, wrapperHeight)
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      const sq = Math.min(width, height);
      setGridSize({ width: sq, height: sq });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [state !== null]);

  // Reset on mission restart
  useEffect(() => {
    if (!state) return;
    if (state.mission_step === 0 || state.mission_step < prevStepRef.current) {
      droneHistories.current = {};
      displayPositions.current = {};
      moveQueues.current = {};
    }
    prevStepRef.current = state.mission_step;
  }, [state?.mission_step]);

  // Enqueue waypoints when drone positions change
  useEffect(() => {
    if (!state || isReplaying) return;
    for (const d of Object.values(state.drones)) {
      const dp = displayPositions.current[d.drone_id];
      if (!dp) {
        // First time seeing this drone — initialize directly
        displayPositions.current[d.drone_id] = d.position;
        const hist = droneHistories.current[d.drone_id] ?? [];
        if (!hist.length || hist[hist.length - 1][0] !== d.position[0] || hist[hist.length - 1][1] !== d.position[1]) {
          droneHistories.current[d.drone_id] = [...hist, d.position].slice(-40);
        }
        continue;
      }
      // Target is current queue destination or display position
      const queue = moveQueues.current[d.drone_id] ?? [];
      const lastQueued = queue.length > 0 ? queue[queue.length - 1] : dp;
      if (lastQueued[0] === d.position[0] && lastQueued[1] === d.position[1]) continue;
      const dist = Math.abs(d.position[0] - lastQueued[0]) + Math.abs(d.position[1] - lastQueued[1]);
      if (dist <= 1) {
        // Adjacent move — append directly
        moveQueues.current[d.drone_id] = [...queue, d.position];
      } else {
        // Distant move — interpolate path and append
        const path = computeGridPath(lastQueued, d.position);
        moveQueues.current[d.drone_id] = [...queue, ...path];
      }
    }
  }, [state, isReplaying]);

  // Animation loop — pop one waypoint per drone every 300ms + detect rescue arrivals
  useEffect(() => {
    if (isReplaying) return;
    const interval = setInterval(() => {
      let advanced = false;
      const queues = moveQueues.current;
      const pendingMap = pendingRescuesRef.current;
      const arrivedCb = onRescueArrivedRef.current;
      for (const droneId of Object.keys(queues)) {
        const queue = queues[droneId];
        if (!queue || queue.length === 0) continue;
        // Drain excess queue: if >8 pending, skip to last 4 (record skipped in trail)
        if (queue.length > 8) {
          const skipped = queue.splice(0, queue.length - 4);
          for (const pos of skipped) {
            // Fire pending rescue if drone passes through survivor cell
            if (pendingMap && pendingMap.size > 0 && arrivedCb) {
              for (const [survivorId, rescue] of Array.from(pendingMap.entries())) {
                if (pos[0] === rescue.position[0] && pos[1] === rescue.position[1]) {
                  arrivedCb(survivorId);
                }
              }
            }
            const hist = droneHistories.current[droneId] ?? [];
            const last = hist[hist.length - 1];
            if (!last || last[0] !== pos[0] || last[1] !== pos[1]) {
              droneHistories.current[droneId] = [...hist, pos].slice(-40);
            }
          }
        }
        const next = queue.shift()!;
        displayPositions.current[droneId] = next;
        // Record in trail history
        const hist = droneHistories.current[droneId] ?? [];
        const last = hist[hist.length - 1];
        if (!last || last[0] !== next[0] || last[1] !== next[1]) {
          droneHistories.current[droneId] = [...hist, next].slice(-40);
        }
        advanced = true;
      }
      // Check if any drone's display position matches a pending rescue
      if (pendingMap && pendingMap.size > 0 && arrivedCb) {
        for (const [survivorId, rescue] of Array.from(pendingMap.entries())) {
          for (const did of Object.keys(displayPositions.current)) {
            const dp = displayPositions.current[did];
            if (dp && dp[0] === rescue.position[0] && dp[1] === rescue.position[1]) {
              arrivedCb(survivorId);
              break;
            }
          }
        }
      }
      if (advanced) setRenderTick((t) => t + 1);
    }, 300);
    return () => clearInterval(interval);
  }, [isReplaying]);

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

  // Compute distress signal positions from survivor_detected events
  // Show only where no found survivor exists yet (avoid doubling up after scan)
  const distressSignals = useMemo<Map<string, string>>(() => {
    const signals = new Map<string, string>(); // posKey -> severity
    if (!state) return signals;

    // Collect found survivor positions
    const foundPositions = new Set<string>();
    for (const s of state.survivors) {
      if (s.position && s.found) {
        foundPositions.add(`${s.position[0]},${s.position[1]}`);
      }
    }

    // Gather survivor_detected events from all steps up to current
    for (const evt of state.disaster_events) {
      if (evt.type !== 'survivor_detected' || !evt.position) continue;
      if (evt.step > state.mission_step) continue;
      const key = `${evt.position[0]},${evt.position[1]}`;
      if (!foundPositions.has(key)) {
        signals.set(key, evt.severity ?? 'STABLE');
      }
    }
    return signals;
  }, [state]);

  if (!state) {
    return (
      <div className="bg-white rounded border border-gray-200 shadow-sm p-2 flex items-center justify-center">
        <span className="text-gray-500 text-sm">Connecting to simulation...</span>
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
      const survivors = survivorsByPos.get(posKey) ?? [];
      const isScanned = scannedSet.has(posKey);
      const inBlackout = isInBlackout(x, y, state.blackout_zones);
      const isBase = x === 6 && y === 5;

      cells.push(
        <div
          key={posKey}
          className={`relative border ${TERRAIN_BG[terrain]} ${TERRAIN_BORDER[terrain]}`}
          style={{ minWidth: 0, minHeight: 0 }}
          title={`(${x},${y}) ${terrain}`}
        >
          {/* Heatmap overlay — only on scanned cells so initial priors don't distort terrain colors */}
          {isScanned && heat > 0.05 && (
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

          {/* Warning zone pulse overlay */}
          {warningCells.has(posKey) && (
            <div className="absolute inset-0 pointer-events-none warning-zone-pulse" style={{ zIndex: 18 }} />
          )}

          {/* Distress signal overlay — unconfirmed survivor detection */}
          {distressSignals.has(posKey) && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-20">
              <div className="distress-signal-pulse" style={{
                width: '60%',
                height: '60%',
                borderRadius: '50%',
                border: `2px solid ${SEVERITY_COLORS[distressSignals.get(posKey)!] ?? '#f97316'}`,
                background: `radial-gradient(circle, ${SEVERITY_COLORS[distressSignals.get(posKey)!] ?? '#f97316'}33 0%, transparent 70%)`,
              }}>
                <span style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  transform: 'translate(-50%, -50%)',
                  fontSize: 9,
                  fontWeight: 900,
                  color: SEVERITY_COLORS[distressSignals.get(posKey)!] ?? '#f97316',
                  textShadow: '0 0 4px rgba(0,0,0,0.8)',
                  lineHeight: 1,
                }}>?</span>
              </div>
            </div>
          )}

          {/* Blackout overlay */}
          {inBlackout && (
            <div className="absolute inset-0 bg-purple-950/50 pointer-events-none" />
          )}

          {/* Base station marker */}
          {isBase && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-20">
              <div style={{
                background: 'rgba(0,0,0,0.55)',
                borderRadius: 3,
                padding: '1px 3px',
                border: '1px solid rgba(253,224,71,0.7)',
              }}>
                <span style={{ fontSize: 8, fontWeight: 800, color: '#fde047', lineHeight: 1, display: 'block', letterSpacing: '0.04em' }}>BASE</span>
              </div>
            </div>
          )}

        </div>
      );
    }
  }

  return (
    <div className="bg-white rounded border border-gray-200 shadow-sm p-2 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-1.5 flex-shrink-0">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Grid Map
        </h2>
        <span className="text-[10px] text-gray-500">
          Step {state.mission_step} &middot; {state.stats.coverage_pct}% covered
        </span>
      </div>

      <div className="relative flex-1 min-h-0">
        {/* Warning banners — absolute overlay, no layout shift */}
        <div className="absolute top-0 left-0 right-0 z-30 flex flex-col gap-1 p-1 pointer-events-none">
          {(activeWarnings ?? []).filter((w) => !w.resolved).map((w, i) => (
            <div
              key={`${w.type}-${w.step}-${i}`}
              className={`${w.dismissing ? 'warning-banner-out' : 'warning-banner-blink'} flex items-center gap-2 px-3 py-1.5 rounded border border-amber-300 bg-amber-50 pointer-events-auto`}
            >
              <span className="warning-icon-shake text-amber-600 text-sm font-bold">&#9888;</span>
              <span className="text-xs font-semibold text-amber-800 flex-1">{w.message}</span>
              <span className="text-[9px] text-amber-500 font-mono">
                ({w.estimated_center[0]},{w.estimated_center[1]})
              </span>
            </div>
          ))}
        </div>

        <div
          ref={wrapperRef}
          className={`w-full h-full flex items-center justify-center overflow-hidden ${gridEffect === 'aftershock' ? 'aftershock-shake' : ''}`}
        >
        <div
          ref={gridRef}
          className="relative flex-shrink-0"
          style={{
            width: gridSize.width || undefined,
            height: gridSize.height || undefined,
            display: 'grid',
            gridTemplateColumns: `repeat(${GRID_SIZE}, 1fr)`,
            gridTemplateRows: `repeat(${GRID_SIZE}, 1fr)`,
          }}
        >
          {cells}

          {/* Trail SVG — below drone dots, above terrain */}
          {gridSize.width > 0 && !isReplaying && (
            <svg
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                overflow: 'visible',
                zIndex: 5,
              }}
            >
              {Object.values(state.drones).map((d) => {
                const hist = droneHistories.current[d.drone_id] ?? [];
                if (hist.length < 2) return null;
                const color = DRONE_COLORS[d.drone_id] ?? '#fff';
                const cellSize = gridSize.width / GRID_SIZE;
                return hist.slice(0, -1).map((from, i) => {
                  const to = hist[i + 1];
                  const age = hist.length - 2 - i;
                  const opacity = Math.pow(0.78, age);
                  const strokeWidth = Math.max(0.5, 1.5 - age * 0.07);
                  const x1 = from[0] * cellSize + cellSize / 2;
                  const y1 = (GRID_SIZE - 1 - from[1]) * cellSize + cellSize / 2;
                  const x2 = to[0] * cellSize + cellSize / 2;
                  const y2 = (GRID_SIZE - 1 - to[1]) * cellSize + cellSize / 2;
                  return (
                    <line
                      key={`${d.drone_id}-t${i}`}
                      x1={x1} y1={y1} x2={x2} y2={y2}
                      stroke={color}
                      strokeWidth={strokeWidth}
                      opacity={opacity}
                      strokeLinecap="round"
                    />
                  );
                });
              })}
            </svg>
          )}

          {/* Mesh connection lines — between trails and drone markers */}
          {gridSize.width > 0 && state.mesh_topology && (
            <svg
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                overflow: 'visible',
                zIndex: 20,
              }}
            >
              {(() => {
                const cellSize = gridSize.width / GRID_SIZE;
                const basePos = state.base_position ?? [6, 5];
                const drawn = new Set<string>();
                const lines: React.ReactNode[] = [];

                for (const [nodeId, neighbors] of Object.entries(state.mesh_topology)) {
                  for (const neighborId of neighbors) {
                    const edgeKey = [nodeId, neighborId].sort().join('--');
                    if (drawn.has(edgeKey)) continue;
                    drawn.add(edgeKey);

                    // Resolve positions — use animated positions in live mode
                    const posOf = (id: string): [number, number] | null => {
                      if (id === 'base') return basePos as [number, number];
                      const d = state.drones[id];
                      if (!d || !d.connected) return null;
                      if (!isReplaying) {
                        return displayPositions.current[id] ?? d.position;
                      }
                      return d.position;
                    };
                    const p1 = posOf(nodeId);
                    const p2 = posOf(neighborId);
                    if (!p1 || !p2) continue;

                    const x1 = p1[0] * cellSize + cellSize / 2;
                    const y1 = (GRID_SIZE - 1 - p1[1]) * cellSize + cellSize / 2;
                    const x2 = p2[0] * cellSize + cellSize / 2;
                    const y2 = (GRID_SIZE - 1 - p2[1]) * cellSize + cellSize / 2;

                    // Glow line (wider, more transparent) behind the main line
                    lines.push(
                      <line
                        key={`${edgeKey}-glow`}
                        x1={x1} y1={y1} x2={x2} y2={y2}
                        stroke="#0891b2"
                        strokeWidth={6}
                        opacity={0.25}
                        strokeLinecap="round"
                      />
                    );
                    lines.push(
                      <line
                        key={edgeKey}
                        x1={x1} y1={y1} x2={x2} y2={y2}
                        stroke="#0891b2"
                        strokeWidth={2}
                        strokeDasharray="4 3"
                        opacity={0.8}
                        strokeLinecap="round"
                      />
                    );
                  }
                }
                return lines;
              })()}
            </svg>
          )}

          {/* Drone overlays — rendered on top of grid for smooth animation */}
          {gridSize.width > 0 && (() => {
            const droneList = Object.values(state.drones);

            // Use displayPositions for live mode, raw positions for replay
            const positionOf = (d: DroneState): [number, number] =>
              isReplaying
                ? d.position
                : (displayPositions.current[d.drone_id] ?? d.position);

            // Group by displayed cell to offset overlapping drones
            const dronesByCell = new Map<string, number>();
            const droneIndex = new Map<string, number>();
            for (const d of droneList) {
              const pos = positionOf(d);
              const key = `${pos[0]},${pos[1]}`;
              const count = dronesByCell.get(key) ?? 0;
              droneIndex.set(d.drone_id, count);
              dronesByCell.set(key, count + 1);
            }

            const cellSize = gridSize.width / GRID_SIZE;
            const MARKER = 22;

            return droneList.map((d) => {
              const pos = positionOf(d);

              // Offset when multiple drones share a cell
              const key = `${pos[0]},${pos[1]}`;
              const idx = droneIndex.get(d.drone_id) ?? 0;
              const total = dronesByCell.get(key) ?? 1;
              const offsetX = total > 1 ? (idx % 2) * 16 : 0;
              const offsetY = total > 1 ? Math.floor(idx / 2) * 16 : 0;

              const left = pos[0] * cellSize + cellSize / 2 - MARKER / 2 + offsetX;
              const top = (GRID_SIZE - 1 - pos[1]) * cellSize + cellSize / 2 - MARKER / 2 + offsetY;

              const droneColor = DRONE_COLORS[d.drone_id] ?? '#ffffff';
              const initial = d.drone_id[6]?.toUpperCase() ?? '?';
              const batteryColor = d.battery > 40 ? '#4ade80' : d.battery > 20 ? '#fbbf24' : '#f87171';

              return (
                <div
                  key={d.drone_id}
                  className={`pointer-events-none ${!d.connected ? 'blink' : ''}`}
                  style={{
                    position: 'absolute',
                    left,
                    top,
                    width: MARKER,
                    height: MARKER,
                    transition: 'left 0.3s ease-in-out, top 0.3s ease-in-out',
                    borderRadius: '50%',
                    background: `radial-gradient(circle at 38% 32%, ${droneColor}dd, ${droneColor}88)`,
                    border: d.is_relay
                      ? '2.5px solid rgba(255,255,255,0.95)'
                      : `2px solid ${droneColor}`,
                    boxShadow: `0 0 10px ${droneColor}99, 0 0 3px rgba(0,0,0,0.6)`,
                    zIndex: 10,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <span style={{
                    fontSize: 9,
                    color: '#fff',
                    fontWeight: 800,
                    lineHeight: 1,
                    textShadow: '0 1px 3px rgba(0,0,0,0.9)',
                    userSelect: 'none',
                  }}>
                    {initial}
                  </span>
                  {/* Battery bar */}
                  <div style={{
                    position: 'absolute',
                    bottom: -5,
                    left: 0,
                    width: MARKER,
                    height: 3,
                    background: 'rgba(0,0,0,0.45)',
                    borderRadius: 2,
                  }}>
                    <div style={{
                      width: `${d.battery}%`,
                      height: '100%',
                      background: batteryColor,
                      borderRadius: 2,
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                </div>
              );
            });
          })()}

          {/* Survivor overlays — rendered absolutely over grid like drone markers */}
          {gridSize.width > 0 && (() => {
            const cellSize = gridSize.width / GRID_SIZE;
            const S_MARKER = 16;

            // Group by cell for offset logic — exclude rescued survivors (unless pending)
            const survivorsByCell = new Map<string, number>();
            const survivorIndex = new Map<number, number>();
            for (const s of state.survivors) {
              if (!s.position || (s.rescued && !(pendingRescues?.has(s.survivor_id)))) continue;
              const key = `${s.position[0]},${s.position[1]}`;
              const count = survivorsByCell.get(key) ?? 0;
              survivorIndex.set(s.survivor_id, count);
              survivorsByCell.set(key, count + 1);
            }

            return state.survivors.map((s) => {
              if (!s.position) return null;

              const color = !s.alive ? '#6b7280' : (SEVERITY_COLORS[s.severity] ?? '#fff');
              const isNewlyFound = newlyFoundIds?.has(s.survivor_id) ?? false;

              // Rescued survivors: show muted ✓ marker (burst overlay handled separately)
              // If rescue is pending (drone hasn't visually arrived), keep showing as active
              if (s.rescued && !(pendingRescues?.has(s.survivor_id))) {
                if (rescueBursts?.has(s.survivor_id)) return null; // burst is showing
                const left = s.position[0] * cellSize + cellSize / 2 - S_MARKER / 2;
                const top  = (GRID_SIZE - 1 - s.position[1]) * cellSize + cellSize / 2 - S_MARKER / 2;
                return (
                  <div
                    key={s.survivor_id}
                    className="pointer-events-none rescue-muted-in"
                    style={{
                      position: 'absolute', left, top,
                      width: S_MARKER, height: S_MARKER,
                      borderRadius: '50%',
                      background: 'rgba(107,114,128,0.25)',
                      border: '1.5px solid rgba(107,114,128,0.4)',
                      zIndex: 8,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    <span style={{ fontSize: 8, color: 'rgba(255,255,255,0.7)', fontWeight: 900, lineHeight: 1 }}>✓</span>
                  </div>
                );
              }

              const idx   = survivorIndex.get(s.survivor_id) ?? 0;
              const total = survivorsByCell.get(`${s.position[0]},${s.position[1]}`) ?? 1;
              const offsetX = total > 1 ? (idx % 2) * 14 - 7 : 0;
              const offsetY = total > 1 ? Math.floor(idx / 2) * 14 - (total > 2 ? 7 : 0) : 0;

              const left = s.position[0] * cellSize + cellSize / 2 - S_MARKER / 2 + offsetX;
              const top  = (GRID_SIZE - 1 - s.position[1]) * cellSize + cellSize / 2 - S_MARKER / 2 + offsetY;

              const healthColor = s.health > 0.6 ? '#4ade80' : s.health > 0.3 ? '#fbbf24' : '#f87171';
              const label = s.severity === 'CRITICAL' ? '!' : s.severity === 'MODERATE' ? '+' : '·';

              const isFound    = s.found && s.alive;
              const isCritical = s.severity === 'CRITICAL';

              // SOS ring speed: faster as health drops (0.6s near-death → 2.0s full health)
              const sosDuration   = (0.6 + s.health * 1.4).toFixed(2) + 's';
              const sosBlinkSpeed = (0.4 + s.health * 0.6).toFixed(2) + 's';

              // Unfound survivors keep existing pulse; found+alive get SOS rings instead
              const animClass = !s.alive ? '' : isFound ? '' : isCritical ? 'survivor-critical-pulse' : 'survivor-pulse';

              return (
                <div
                  key={s.survivor_id}
                  className="pointer-events-none"
                  style={{ position: 'absolute', left, top, width: S_MARKER, height: S_MARKER, zIndex: 9 }}
                >
                  {/* SOS sonar rings — only when found+alive */}
                  {isFound && (
                    <>
                      <div
                        className="sos-ring"
                        style={{
                          position: 'absolute',
                          inset: -S_MARKER / 2,
                          borderRadius: '50%',
                          border: `2px solid ${color}`,
                          '--sos-duration': sosDuration,
                        } as React.CSSProperties}
                      />
                      <div
                        className="sos-ring"
                        style={{
                          position: 'absolute',
                          inset: -S_MARKER / 2,
                          borderRadius: '50%',
                          border: `1.5px solid ${color}`,
                          animationDelay: `calc(${sosDuration} / -2)`,
                          '--sos-duration': sosDuration,
                        } as React.CSSProperties}
                      />
                      {isCritical && (
                        <div
                          className="sos-blink"
                          style={{
                            position: 'absolute',
                            top: -14,
                            left: '50%',
                            transform: 'translateX(-50%)',
                            fontSize: 7,
                            fontWeight: 900,
                            color,
                            letterSpacing: '0.1em',
                            textShadow: '0 0 4px rgba(0,0,0,0.9)',
                            whiteSpace: 'nowrap',
                            '--sos-blink-speed': sosBlinkSpeed,
                          } as React.CSSProperties}
                        >
                          SOS
                        </div>
                      )}
                    </>
                  )}

                  {/* Core marker circle */}
                  <div
                    className={animClass}
                    style={{
                      width: S_MARKER,
                      height: S_MARKER,
                      borderRadius: '50%',
                      background: s.alive
                        ? `radial-gradient(circle at 38% 32%, ${color}ee, ${color}77)`
                        : 'rgba(107,114,128,0.5)',
                      border: `1.5px solid ${color}`,
                      boxShadow: s.alive ? `0 0 8px ${color}88, 0 0 2px rgba(0,0,0,0.5)` : 'none',
                      opacity: s.alive ? 1 : 0.35,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <span style={{ fontSize: 8, fontWeight: 900, color: '#fff', lineHeight: 1, textShadow: '0 1px 2px rgba(0,0,0,0.9)', userSelect: 'none' }}>
                      {label}
                    </span>
                    {s.alive && (
                      <div style={{ position: 'absolute', bottom: -5, left: 0, width: S_MARKER, height: 2.5, background: 'rgba(0,0,0,0.45)', borderRadius: 2 }}>
                        <div style={{ width: `${s.health * 100}%`, height: '100%', background: healthColor, borderRadius: 2, transition: 'width 0.5s ease' }} />
                      </div>
                    )}
                  </div>

                  {/* Discovery reveal badge — bounces in when newly found */}
                  {isNewlyFound && (
                    <div
                      className="discovery-reveal"
                      style={{
                        position: 'absolute',
                        top: -26,
                        left: '50%',
                        background: color,
                        borderRadius: 4,
                        padding: '2px 5px',
                        whiteSpace: 'nowrap',
                        boxShadow: `0 0 10px ${color}88`,
                        zIndex: 20,
                        pointerEvents: 'none',
                      }}
                    >
                      <span style={{ fontSize: 7, fontWeight: 900, color: '#fff', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                        FOUND!
                      </span>
                    </div>
                  )}
                </div>
              );
            });
          })()}

          {/* Rescue burst overlays — green rings + checkmark at rescue position */}
          {gridSize.width > 0 && rescueBursts && Array.from(rescueBursts.entries()).map(([id, pos]) => {
            const cellSize = gridSize.width / GRID_SIZE;
            const BURST = 28;
            const left = pos[0] * cellSize + cellSize / 2 - BURST / 2;
            const top  = (GRID_SIZE - 1 - pos[1]) * cellSize + cellSize / 2 - BURST / 2;
            return (
              <div key={`burst-${id}`} className="pointer-events-none" style={{ position: 'absolute', left, top, width: BURST, height: BURST, zIndex: 30 }}>
                <div className="rescue-burst-ring" style={{ position: 'absolute', inset: 0, borderRadius: '50%', border: '3px solid #22c55e', boxShadow: '0 0 10px #22c55e88' }} />
                <div className="rescue-burst-ring2" style={{ position: 'absolute', inset: 0, borderRadius: '50%', border: '2px solid #4ade80' }} />
                <div className="rescue-check-pop" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ fontSize: 13, color: '#22c55e', fontWeight: 900, textShadow: '0 0 8px rgba(0,0,0,0.8)', opacity: 0 }}>✓</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 flex-shrink-0">
        {(Object.entries(TERRAIN_BG) as [TerrainType, string][]).map(([t, cls]) => (
          <span key={t} className="flex items-center gap-1 text-[9px] text-gray-500">
            <span className={`inline-block w-2 h-2 rounded-sm ${cls}`} />
            {t.charAt(0) + t.slice(1).toLowerCase()}
          </span>
        ))}
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-sm" style={{ background: 'rgba(220,38,38,0.75)' }} />
          Heatmap
        </span>
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-sm bg-purple-950/50" />
          Blackout
        </span>
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-sm" style={{ background: 'rgba(245,158,11,0.5)' }} />
          Warning
        </span>
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-full" style={{ border: '1.5px solid #f97316', background: 'rgba(249,115,22,0.2)' }} />
          Distress
        </span>
        <span className="flex items-center gap-1 text-[9px] text-gray-500">
          <span className="inline-block w-4 h-0 border-t-2 border-dashed" style={{ borderColor: '#0891b2' }} />
          Mesh
        </span>
      </div>
    </div>
  );
}
