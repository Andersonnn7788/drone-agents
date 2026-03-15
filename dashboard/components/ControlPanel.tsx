'use client';

import { useState } from 'react';
import { SimState } from '@/lib/api';

interface ControlPanelProps {
  state: SimState | null;
  missionRunning: boolean;
  onStart: () => void;
  onStep: (steps: number) => void;
  onBlackout: (zone_x: number, zone_y: number, radius: number) => void;
  onReset: () => void;
}

export default function ControlPanel({
  state,
  missionRunning,
  onStart,
  onStep,
  onBlackout,
  onReset,
}: ControlPanelProps) {
  const [showBlackout, setShowBlackout] = useState(false);
  const [bx, setBx] = useState(6);
  const [by, setBy] = useState(6);
  const [br, setBr] = useState(2);
  const [resetArmed, setResetArmed] = useState(false);

  const stats = state?.stats;

  const handleReset = () => {
    if (!resetArmed) {
      setResetArmed(true);
      setTimeout(() => setResetArmed(false), 3000);
    } else {
      setResetArmed(false);
      onReset();
    }
  };

  const statTiles = [
    { label: 'Step', value: state ? String(state.mission_step) : '—' },
    {
      label: 'Found',
      value: stats ? `${stats.found}/${stats.total_survivors}` : '—',
    },
    { label: 'Rescued', value: stats ? String(stats.rescued) : '—' },
    { label: 'Alive', value: stats ? String(stats.alive) : '—' },
    {
      label: 'Coverage',
      value: stats ? `${stats.coverage_pct}%` : '—',
    },
    {
      label: 'Drones',
      value: stats ? `${stats.active_drones}/${stats.total_drones}` : '—',
    },
  ];

  return (
    <div className="bg-gray-900 rounded border border-gray-800 p-2 flex flex-col gap-2 overflow-y-auto min-h-0">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex-shrink-0">
        Controls
      </h2>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-1 flex-shrink-0">
        {statTiles.map((tile) => (
          <div
            key={tile.label}
            className="bg-gray-800 rounded p-1.5 text-center border border-gray-700"
          >
            <div className="text-[9px] text-gray-500">{tile.label}</div>
            <div className="text-xs font-bold text-cyan-300 mt-0.5">{tile.value}</div>
          </div>
        ))}
      </div>

      {/* Start Mission */}
      <button
        onClick={onStart}
        disabled={missionRunning}
        className="w-full py-1.5 text-xs font-medium rounded bg-cyan-800 hover:bg-cyan-700
          disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed
          text-cyan-100 transition-colors flex-shrink-0"
      >
        {missionRunning ? 'Mission Running...' : 'Start Mission'}
      </button>

      {/* Manual Step */}
      <button
        onClick={() => onStep(1)}
        className="w-full py-1.5 text-xs font-medium rounded bg-gray-700 hover:bg-gray-600
          text-gray-200 transition-colors flex-shrink-0"
      >
        +1 Step
      </button>

      {/* Trigger Blackout toggle */}
      <button
        onClick={() => setShowBlackout((v) => !v)}
        className="w-full py-1.5 text-xs font-medium rounded bg-purple-900 hover:bg-purple-800
          text-purple-200 transition-colors flex-shrink-0"
      >
        {showBlackout ? 'Cancel Blackout' : 'Trigger Blackout'}
      </button>

      {/* Inline blackout config */}
      {showBlackout && (
        <div className="bg-gray-800 rounded p-2 border border-purple-800 flex flex-col gap-1.5 flex-shrink-0">
          <span className="text-[10px] text-purple-300 font-medium">Blackout Zone</span>
          {(
            [
              ['Zone X', bx, setBx, 0, 11],
              ['Zone Y', by, setBy, 0, 11],
              ['Radius', br, setBr, 1, 6],
            ] as [string, number, (v: number) => void, number, number][]
          ).map(([label, val, setter, min, max]) => (
            <label key={label} className="flex items-center justify-between text-[10px]">
              <span className="text-gray-400">{label}</span>
              <input
                type="number"
                min={min}
                max={max}
                value={val}
                onChange={(e) => setter(Number(e.target.value))}
                className="w-12 bg-gray-700 text-gray-100 rounded px-1 py-0.5 text-right
                  border border-gray-600 focus:outline-none focus:border-purple-500"
              />
            </label>
          ))}
          <button
            onClick={() => {
              onBlackout(bx, by, br);
              setShowBlackout(false);
            }}
            className="w-full py-1 mt-0.5 rounded bg-purple-700 hover:bg-purple-600
              text-purple-100 text-xs font-medium transition-colors"
          >
            Deploy Blackout
          </button>
        </div>
      )}

      {/* Reset */}
      <button
        onClick={handleReset}
        className={`w-full py-1.5 text-xs font-medium rounded transition-colors flex-shrink-0 ${
          resetArmed
            ? 'bg-red-800 hover:bg-red-700 text-red-100 animate-pulse'
            : 'bg-gray-700 hover:bg-gray-600 text-gray-200'
        }`}
      >
        {resetArmed ? 'Confirm Reset?' : 'Reset Simulation'}
      </button>
    </div>
  );
}
