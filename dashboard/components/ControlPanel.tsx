'use client';

import { useState } from 'react';
import { SimState } from '@/lib/api';

interface ControlPanelProps {
  state: SimState | null;
  missionRunning: boolean;
  voiceEnabled: boolean;
  onVoiceToggle: () => void;
  onStart: () => void;
  onStep: (steps: number) => void;
  onBlackout: (zone_x: number, zone_y: number, radius: number) => void;
  onReset: () => void;
}

export default function ControlPanel({
  state,
  missionRunning,
  voiceEnabled,
  onVoiceToggle,
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
    <div className="bg-white rounded border border-gray-200 shadow-sm p-2 flex flex-col gap-2 overflow-y-auto min-h-0">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider flex-shrink-0">
        Controls
      </h2>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-1 flex-shrink-0">
        {statTiles.map((tile) => (
          <div
            key={tile.label}
            className="bg-gray-50 rounded p-1.5 text-center border border-gray-200"
          >
            <div className="text-[10px] text-gray-500">{tile.label}</div>
            <div className="text-xs font-bold text-cyan-700 mt-0.5">{tile.value}</div>
          </div>
        ))}
      </div>

      {/* Start Mission */}
      <button
        onClick={onStart}
        disabled={missionRunning}
        className="w-full py-1.5 text-xs font-medium rounded bg-cyan-600 hover:bg-cyan-500 border border-cyan-500
          disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200 disabled:cursor-not-allowed
          text-white transition-colors flex-shrink-0"
      >
        {missionRunning ? 'Mission Running...' : 'Start Mission'}
      </button>

      {/* Manual Step */}
      <button
        onClick={() => onStep(1)}
        className="w-full py-1.5 text-xs font-medium rounded bg-gray-100 hover:bg-gray-200
          text-gray-800 border border-gray-300 transition-colors flex-shrink-0"
      >
        +1 Step
      </button>

      {/* Voice toggle */}
      <button
        onClick={onVoiceToggle}
        className={`w-full py-1.5 text-xs font-medium rounded transition-colors flex-shrink-0 border ${
          voiceEnabled
            ? 'bg-amber-100 hover:bg-amber-200 text-amber-800 border-amber-300'
            : 'bg-gray-100 hover:bg-gray-200 text-gray-800 border-gray-300'
        }`}
      >
        {voiceEnabled ? 'Voice On' : 'Voice Off'}
      </button>

      {/* Trigger Blackout toggle */}
      <button
        onClick={() => setShowBlackout((v) => !v)}
        className="w-full py-1.5 text-xs font-medium rounded bg-purple-600 hover:bg-purple-500
          text-white border border-purple-500 transition-colors flex-shrink-0"
      >
        {showBlackout ? 'Cancel Blackout' : 'Trigger Blackout'}
      </button>

      {/* Inline blackout config */}
      {showBlackout && (
        <div className="bg-purple-50 rounded p-2 border border-purple-200 flex flex-col gap-1.5 flex-shrink-0">
          <span className="text-[10px] text-purple-700 font-medium">Blackout Zone</span>
          {(
            [
              ['Zone X', bx, setBx, 0, 11],
              ['Zone Y', by, setBy, 0, 11],
              ['Radius', br, setBr, 1, 6],
            ] as [string, number, (v: number) => void, number, number][]
          ).map(([label, val, setter, min, max]) => (
            <label key={label} className="flex items-center justify-between text-[10px]">
              <span className="text-gray-600">{label}</span>
              <input
                type="number"
                min={min}
                max={max}
                value={val}
                onChange={(e) => setter(Number(e.target.value))}
                className="w-12 bg-white text-gray-800 rounded px-1 py-0.5 text-right
                  border border-gray-300 focus:outline-none focus:border-purple-400"
              />
            </label>
          ))}
          <button
            onClick={() => {
              onBlackout(bx, by, br);
              setShowBlackout(false);
            }}
            className="w-full py-1 mt-0.5 rounded bg-purple-600 hover:bg-purple-500
              text-white text-xs font-medium transition-colors border border-purple-500"
          >
            Deploy Blackout
          </button>
        </div>
      )}

      {/* Reset */}
      <button
        onClick={handleReset}
        className={`w-full py-1.5 text-xs font-medium rounded transition-colors flex-shrink-0 mt-1 border ${
          resetArmed
            ? 'bg-red-600 hover:bg-red-500 text-white border-red-500 animate-pulse'
            : 'bg-gray-100 hover:bg-gray-200 text-gray-800 border-gray-300'
        }`}
      >
        {resetArmed ? 'Confirm Reset?' : 'Reset Simulation'}
      </button>
    </div>
  );
}
