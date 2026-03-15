'use client';

import { DroneStatus, Severity, SimState } from '@/lib/api';

const DRONE_ORDER = ['drone_alpha', 'drone_bravo', 'drone_charlie', 'drone_delta'];

const DRONE_COLORS: Record<string, string> = {
  drone_alpha: '#FFD700',
  drone_bravo: '#00FFFF',
  drone_charlie: '#FF8C00',
  drone_delta: '#A855F7',
};

const STATUS_BADGE: Record<DroneStatus, string> = {
  active: 'bg-green-800 text-green-200',
  returning: 'bg-yellow-800 text-yellow-200',
  charging: 'bg-blue-800 text-blue-200',
  relay: 'bg-purple-800 text-purple-200',
  dead: 'bg-red-900 text-red-300',
};

const SEVERITY_BADGE: Record<Severity, string> = {
  CRITICAL: 'bg-red-900 text-red-300',
  MODERATE: 'bg-orange-900 text-orange-300',
  STABLE: 'bg-green-900 text-green-300',
};

function batteryBarColor(battery: number): string {
  if (battery >= 50) return 'bg-green-500';
  if (battery >= 20) return 'bg-yellow-400';
  return 'bg-red-500';
}

function healthBarColor(severity: Severity, alive: boolean): string {
  if (!alive) return 'bg-gray-600';
  if (severity === 'CRITICAL') return 'bg-red-500';
  if (severity === 'MODERATE') return 'bg-orange-400';
  return 'bg-green-500';
}

interface DronePanelProps {
  state: SimState | null;
}

export default function DronePanel({ state }: DronePanelProps) {
  if (!state) {
    return (
      <div className="bg-gray-900 rounded border border-gray-800 p-2 flex items-center justify-center">
        <span className="text-gray-600 text-sm">No data</span>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded border border-gray-800 p-2 flex flex-col gap-2 overflow-y-auto min-h-0">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex-shrink-0">
        Fleet Status
      </h2>

      {/* Drone cards */}
      {DRONE_ORDER.map((id) => {
        const d = state.drones[id];
        if (!d) return null;
        return (
          <div
            key={id}
            className="bg-gray-800 rounded p-2 border border-gray-700 flex-shrink-0"
          >
            {/* Header row */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ background: DRONE_COLORS[id] ?? '#fff' }}
                />
                <span className="text-xs font-medium text-gray-200 capitalize">
                  {id.replace('drone_', '')}
                </span>
                {!d.connected && (
                  <span className="text-[9px] text-orange-400 font-medium blink">DISCO</span>
                )}
                {d.is_relay && (
                  <span className="text-[9px] text-purple-400 font-medium">RELAY</span>
                )}
              </div>
              <span
                className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${STATUS_BADGE[d.status]}`}
              >
                {d.status.toUpperCase()}
              </span>
            </div>

            {/* Battery bar */}
            <div className="flex items-center gap-1.5 mb-1">
              <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full bar-transition ${batteryBarColor(d.battery)}`}
                  style={{ width: `${Math.max(0, d.battery)}%` }}
                />
              </div>
              <span className="text-[9px] text-gray-400 w-7 text-right flex-shrink-0">
                {d.battery}%
              </span>
            </div>

            {/* Metadata */}
            <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[9px] text-gray-500">
              <span>
                ({d.position[0]},{d.position[1]})
              </span>
              <span>Range:{d.comm_range}</span>
              {d.assigned_sector && (
                <span className="text-gray-600">
                  Sector ({d.assigned_sector[0]},{d.assigned_sector[1]})
                </span>
              )}
              {d.findings_buffer_size > 0 && (
                <span className="text-amber-400">{d.findings_buffer_size} buffered</span>
              )}
            </div>
          </div>
        );
      })}

      {/* Survivor section */}
      {state.survivors.length > 0 && (
        <>
          <div className="flex items-center justify-between flex-shrink-0 mt-1">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Survivors
            </h2>
            <span className="text-[9px] text-gray-500">
              {state.stats.found}/{state.stats.total_survivors} found
            </span>
          </div>

          {state.survivors.map((s) => (
            <div
              key={s.survivor_id}
              className={`bg-gray-800 rounded p-1.5 border flex-shrink-0 ${
                !s.alive ? 'border-gray-700 opacity-40' : 'border-gray-700'
              }`}
            >
              <div className="flex items-center justify-between mb-0.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`text-[9px] px-1 py-0.5 rounded font-medium ${SEVERITY_BADGE[s.severity]}`}
                  >
                    {s.severity}
                  </span>
                  <span className="text-[9px] text-gray-400">
                    #{s.survivor_id}
                  </span>
                  {s.rescued && (
                    <span className="text-[9px] text-green-400 font-medium">RESCUED</span>
                  )}
                  {!s.alive && (
                    <span className="text-[9px] text-gray-500 font-medium">DECEASED</span>
                  )}
                </div>
                <span className="text-[9px] text-gray-500">
                  {Math.round(s.health * 100)}%
                </span>
              </div>
              <div className="bg-gray-700 rounded-full h-1">
                <div
                  className={`h-1 rounded-full bar-transition ${healthBarColor(s.severity, s.alive)}`}
                  style={{ width: `${Math.max(0, s.health * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
