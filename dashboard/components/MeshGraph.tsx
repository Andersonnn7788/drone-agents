'use client';

import { useMemo } from 'react';
import { SimState } from '@/lib/api';

const DRONE_COLORS: Record<string, string> = {
  drone_alpha: '#FFD700',
  drone_bravo: '#00FFFF',
  drone_charlie: '#FF8C00',
  drone_delta: '#A855F7',
};

const DRONE_LABELS: Record<string, string> = {
  drone_alpha: 'A',
  drone_bravo: 'B',
  drone_charlie: 'C',
  drone_delta: 'D',
};

const SVG_SIZE = 260;
const PADDING = 30;
const GRID_SIZE = 12;

function gridToSvg(gx: number, gy: number): [number, number] {
  const scale = (SVG_SIZE - PADDING * 2) / (GRID_SIZE - 1);
  return [PADDING + gx * scale, SVG_SIZE - PADDING - gy * scale];
}

function computeConnectivity(
  topology: Record<string, string[]>,
  drones: Record<string, { status: string }>
): number {
  const activeDrones = Object.keys(drones).filter((id) => drones[id].status !== 'dead');
  if (activeDrones.length === 0) return 0;

  // BFS from "base" through adjacency
  const visited = new Set<string>();
  const queue: string[] = ['base'];
  visited.add('base');

  while (queue.length > 0) {
    const node = queue.shift()!;
    const neighbors = topology[node] ?? [];
    for (const n of neighbors) {
      if (!visited.has(n)) {
        visited.add(n);
        queue.push(n);
      }
    }
  }

  const reachable = activeDrones.filter((id) => visited.has(id)).length;
  return Math.round((reachable / activeDrones.length) * 100);
}

interface MeshGraphProps {
  state: SimState | null;
}

export default function MeshGraph({ state }: MeshGraphProps) {
  const connectivity = useMemo(() => {
    if (!state) return 0;
    return computeConnectivity(state.mesh_topology, state.drones);
  }, [state]);

  // Compute base-reachable set for coloring edges
  const baseReachable = useMemo(() => {
    if (!state) return new Set<string>();
    const visited = new Set<string>();
    const queue: string[] = ['base'];
    visited.add('base');
    while (queue.length > 0) {
      const node = queue.shift()!;
      for (const n of state.mesh_topology[node] ?? []) {
        if (!visited.has(n)) {
          visited.add(n);
          queue.push(n);
        }
      }
    }
    return visited;
  }, [state]);

  if (!state) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-gray-500 text-sm">No data</span>
      </div>
    );
  }

  const droneEntries = Object.entries(state.drones);

  // Build edges as unique pairs
  const edges: { from: string; to: string; baseConnected: boolean }[] = [];
  const edgeSet = new Set<string>();
  for (const [nodeId, neighbors] of Object.entries(state.mesh_topology)) {
    for (const neighbor of neighbors) {
      const key = [nodeId, neighbor].sort().join('|');
      if (!edgeSet.has(key)) {
        edgeSet.add(key);
        edges.push({
          from: nodeId,
          to: neighbor,
          baseConnected: baseReachable.has(nodeId) && baseReachable.has(neighbor),
        });
      }
    }
  }

  // Node positions
  const nodePos: Record<string, [number, number]> = {
    base: gridToSvg(0, 0),
  };
  for (const [id, drone] of droneEntries) {
    nodePos[id] = gridToSvg(drone.position[0], drone.position[1]);
  }

  const connColor =
    connectivity >= 75 ? 'text-green-700' : connectivity >= 40 ? 'text-yellow-700' : 'text-red-700';
  const connBg =
    connectivity >= 75 ? 'bg-green-50 border border-green-200' : connectivity >= 40 ? 'bg-yellow-50 border border-yellow-200' : 'bg-red-50 border border-red-200';

  return (
    <div className="flex flex-col h-full">
      <svg viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`} className="flex-1 min-h-0">
        {/* Light background */}
        <rect x="0" y="0" width={SVG_SIZE} height={SVG_SIZE} fill="#f8fafc" rx="4" />

        {/* Edges */}
        {edges.map(({ from, to, baseConnected }) => {
          const p1 = nodePos[from];
          const p2 = nodePos[to];
          if (!p1 || !p2) return null;
          return (
            <line
              key={`${from}-${to}`}
              x1={p1[0]}
              y1={p1[1]}
              x2={p2[0]}
              y2={p2[1]}
              stroke={baseConnected ? '#0891b2' : '#94a3b8'}
              strokeWidth={baseConnected ? 1.5 : 1}
              strokeOpacity={baseConnected ? 0.8 : 0.5}
            />
          );
        })}

        {/* Base node */}
        {(() => {
          const [bx, by] = nodePos.base;
          return (
            <g>
              <rect
                x={bx - 8}
                y={by - 8}
                width={16}
                height={16}
                rx={3}
                fill="#92400e"
                stroke="#d97706"
                strokeWidth={1.5}
              />
              <text x={bx} y={by + 3.5} textAnchor="middle" fill="#fef3c7" fontSize="7" fontWeight="bold">
                BASE
              </text>
            </g>
          );
        })()}

        {/* Drone nodes */}
        {droneEntries.map(([id, drone]) => {
          const pos = nodePos[id];
          if (!pos) return null;
          const [cx, cy] = pos;
          const color = DRONE_COLORS[id] ?? '#fff';
          const isDead = drone.status === 'dead';
          const isRelay = drone.is_relay;
          const isDisconnected = !drone.connected;

          return (
            <g key={id} opacity={isDead ? 0.3 : 1}>
              {/* Comm range ring for relay drones */}
              {isRelay && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={18}
                  fill="none"
                  stroke={color}
                  strokeWidth={1}
                  strokeDasharray="3 2"
                  opacity={0.5}
                />
              )}
              {/* Drone circle */}
              <circle
                cx={cx}
                cy={cy}
                r={isRelay ? 7 : 5}
                fill={color}
                stroke={isDisconnected ? '#ef4444' : 'rgba(0,0,0,0.2)'}
                strokeWidth={isDisconnected ? 2 : 1}
                opacity={0.9}
              />
              {/* Label */}
              <text
                x={cx}
                y={cy + (isRelay ? 15 : 13)}
                textAnchor="middle"
                fill="#374151"
                fontSize="8"
                fontWeight="bold"
              >
                {DRONE_LABELS[id] ?? '?'}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Connectivity badge */}
      <div className={`flex items-center justify-center gap-1.5 py-1 rounded ${connBg} mt-1`}>
        <span className={`text-[10px] font-semibold font-mono ${connColor}`}>
          {connectivity}% Connected
        </span>
      </div>
    </div>
  );
}
