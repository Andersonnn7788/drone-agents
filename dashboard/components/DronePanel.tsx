'use client';

import { DroneStatus, GameScore, ScoreBreakdown, Severity, SimState } from '@/lib/api';

const GRADE_COLORS: Record<string, string> = {
  A: 'text-green-400',
  B: 'text-blue-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  F: 'text-red-400',
};

const DRONE_ORDER = ['drone_alpha', 'drone_bravo', 'drone_charlie', 'drone_delta'];

const DRONE_COLORS: Record<string, string> = {
  drone_alpha: '#FFD700',
  drone_bravo: '#00FFFF',
  drone_charlie: '#FF8C00',
  drone_delta: '#A855F7',
};

const STATUS_BADGE: Record<DroneStatus, string> = {
  active: 'bg-green-100 text-green-800 border border-green-200',
  returning: 'bg-yellow-100 text-yellow-800 border border-yellow-200',
  charging: 'bg-blue-100 text-blue-800 border border-blue-200',
  relay: 'bg-purple-100 text-purple-800 border border-purple-200',
  dead: 'bg-red-100 text-red-700 border border-red-200',
};

const SEVERITY_BADGE: Record<Severity, string> = {
  CRITICAL: 'bg-red-100 text-red-700 border border-red-200',
  MODERATE: 'bg-orange-100 text-orange-700 border border-orange-200',
  STABLE: 'bg-green-100 text-green-700 border border-green-200',
};

function batteryBarColor(battery: number): string {
  if (battery >= 50) return 'bg-green-500';
  if (battery >= 20) return 'bg-yellow-400';
  return 'bg-red-500';
}

function healthBarColor(severity: Severity, alive: boolean): string {
  if (!alive) return 'bg-gray-300';
  if (severity === 'CRITICAL') return 'bg-red-500';
  if (severity === 'MODERATE') return 'bg-orange-400';
  return 'bg-green-500';
}

interface DronePanelProps {
  state: SimState | null;
  gameScore?: GameScore;
  scorePop?: boolean;
  livesPop?: boolean;
  backendScore?: ScoreBreakdown | null;
  missionNum?: number;
}

export default function DronePanel({ state, gameScore, scorePop, livesPop, backendScore, missionNum }: DronePanelProps) {
  if (!state) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-gray-500 text-sm">No data</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 overflow-y-auto min-h-0 panel-scroll">

      {/* Gamification Score Panel — backend-powered */}
      {(gameScore || backendScore) && (
        <div className="bg-gray-900 rounded-lg p-2.5 border border-gray-700 flex-shrink-0">
          <div className="flex items-center justify-between mb-1.5">
            <div className="text-[9px] text-gray-400 uppercase tracking-widest font-semibold">
              Mission Score
            </div>
            {missionNum && missionNum > 1 && (
              <span className="text-[8px] px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300 border border-purple-700 font-medium">
                AI Mission #{missionNum}
              </span>
            )}
          </div>
          <div className="flex items-end justify-between mb-1.5">
            <div className="flex items-baseline gap-2">
              <span
                className={`text-2xl font-black text-yellow-400 leading-none tabular-nums ${scorePop ? 'score-pop' : ''}`}
              >
                {(backendScore?.total ?? gameScore?.total ?? 0).toLocaleString()}
              </span>
              {backendScore && (
                <span className={`text-xl font-black leading-none ${GRADE_COLORS[backendScore.grade] ?? 'text-gray-400'}`}>
                  {backendScore.grade}
                </span>
              )}
            </div>
            <span className="text-[9px] text-gray-500 uppercase tracking-wide mb-0.5">pts</span>
          </div>
          {backendScore && (
            <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[8px] text-gray-500 mb-1.5">
              <span>Rescue: {backendScore.rescue_points}</span>
              <span>Cov: +{backendScore.coverage_bonus}</span>
              {backendScore.speed_bonus > 0 && <span>Speed: +{backendScore.speed_bonus}</span>}
              {backendScore.death_penalty > 0 && <span className="text-red-400">Deaths: -{backendScore.death_penalty}</span>}
              <span>Eff: +{backendScore.efficiency_bonus}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-gray-400">Lives Saved:</span>
              <span className={`text-sm font-bold text-green-400 tabular-nums ${livesPop ? 'lives-pop' : ''}`}>
                {backendScore?.rescues ?? gameScore?.livesSaved ?? 0}
              </span>
            </div>
            {gameScore && gameScore.streak >= 2 && (
              <div className="streak-pulse-badge px-1.5 py-0.5 rounded text-[9px] font-black text-yellow-900 bg-yellow-400">
                {gameScore.streak}x STREAK
              </div>
            )}
          </div>
        </div>
      )}

      {/* Drone cards */}
      {DRONE_ORDER.map((id) => {
        const d = state.drones[id];
        if (!d) return null;
        return (
          <div
            key={id}
            className="bg-gray-50 rounded p-2 border border-gray-200 flex-shrink-0"
          >
            {/* Header row */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ background: DRONE_COLORS[id] ?? '#fff' }}
                />
                <span className="text-xs font-medium text-gray-800 capitalize">
                  {id.replace('drone_', '')}
                </span>
                {!d.connected && (
                  <span className="text-[8px] px-1 py-0.5 rounded bg-orange-100 text-orange-700 border border-orange-200 font-medium blink">DISCO</span>
                )}
                {d.is_relay && (
                  <span className="text-[8px] px-1 py-0.5 rounded bg-purple-100 text-purple-700 border border-purple-200 font-medium">RELAY</span>
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
              <div className="flex-1 bg-gray-200 rounded-full h-2">
                <div
                  className={`h-2 rounded-full bar-transition ${batteryBarColor(d.battery)}`}
                  style={{ width: `${Math.max(0, d.battery)}%` }}
                />
              </div>
              <span className="text-[9px] text-gray-500 w-7 text-right flex-shrink-0">
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
                <span className="text-gray-400">
                  Sector ({d.assigned_sector[0]},{d.assigned_sector[1]})
                </span>
              )}
              {d.findings_buffer_size > 0 && (
                <span className="text-amber-600">{d.findings_buffer_size} buffered</span>
              )}
            </div>
          </div>
        );
      })}

      {/* Survivor section */}
      {state.survivors.length > 0 && (
        <>
          <div className="flex items-center justify-between flex-shrink-0 pt-1">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">
              Survivors
            </span>
            <span className="text-[9px] text-gray-500">
              {state.stats.found}/{state.stats.total_survivors} found
            </span>
          </div>

          {state.survivors.map((s) => (
            <div
              key={s.survivor_id}
              className={`rounded p-1.5 border flex-shrink-0 transition-colors ${
                s.rescued
                  ? 'border-green-200 bg-green-50/50'
                  : !s.alive
                    ? 'border-gray-200 bg-gray-50 opacity-40'
                    : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="flex items-center justify-between mb-0.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`text-[9px] px-1 py-0.5 rounded font-medium ${SEVERITY_BADGE[s.severity]}`}
                  >
                    {s.severity}
                  </span>
                  <span className="text-[9px] text-gray-500">
                    #{s.survivor_id}
                  </span>
                  {s.rescued && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-green-100 text-green-700 border border-green-300 font-bold">
                      ✓ RESCUED
                    </span>
                  )}
                  {!s.alive && !s.rescued && (
                    <span className="text-[9px] text-gray-500 font-medium">DECEASED</span>
                  )}
                </div>
                <span className="text-[9px] text-gray-500">
                  {Math.round(s.health * 100)}%
                </span>
              </div>
              <div className="bg-gray-200 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full bar-transition ${s.rescued ? 'bg-green-400' : healthBarColor(s.severity, s.alive)}`}
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
