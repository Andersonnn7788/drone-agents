'use client';

import { useEffect, useRef, useState } from 'react';
import {
  api,
  connectSSE,
  DisasterEvent,
  HistoryResponse,
  LogEntry,
  SimState,
} from '@/lib/api';
import GridMap from '@/components/GridMap';
import DronePanel from '@/components/DronePanel';
import MeshGraph from '@/components/MeshGraph';
import ReasoningLog from '@/components/ReasoningLog';
import ControlPanel from '@/components/ControlPanel';
import TimelineSlider from '@/components/TimelineSlider';

export default function Page() {
  const [simState, setSimState] = useState<SimState | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [history, setHistory] = useState<HistoryResponse>({ total_steps: 0, snapshots: [] });
  const [replayStep, setReplayStep] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  const [missionRunning, setMissionRunning] = useState(false);
  const [flashBlackout, setFlashBlackout] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [rightTab, setRightTab] = useState<'fleet' | 'mesh'>('fleet');
  const [gridEffect, setGridEffect] = useState<'aftershock' | 'water' | null>(null);

  // Keep a ref to the latest simState for use in SSE handlers
  const simStateRef = useRef<SimState | null>(null);
  simStateRef.current = simState;

  useEffect(() => {
    // Initial data load
    api.getState().then(setSimState).catch(() => {});
    api.getLogs().then(setLogs).catch(() => {});
    api.getHistory().then(setHistory).catch(() => {});

    // SSE subscription
    const es = connectSSE({
      onState: (state) => {
        setSimState(state);
        // Append to local history for timeline
        setHistory((prev) => {
          const alreadyHas = prev.snapshots.some((s) => s.step === state.mission_step);
          if (alreadyHas) return { ...prev, total_steps: state.mission_step };
          return {
            total_steps: state.mission_step,
            snapshots: [...prev.snapshots, { step: state.mission_step, state }],
          };
        });
      },
      onLogs: (newLogs) => setLogs((prev) => [...prev, ...newLogs]),
      onDisaster: (event) => {
        // Re-fetch state on disaster to get updated terrain
        api.getState().then(setSimState).catch(() => {});
        // Trigger grid effect
        if (event.type === 'aftershock') {
          setGridEffect('aftershock');
          setTimeout(() => setGridEffect(null), 600);
        } else if (event.type === 'rising_water') {
          setGridEffect('water');
          setTimeout(() => setGridEffect(null), 800);
        }
      },
      onBlackout: () => {
        setFlashBlackout(true);
        setTimeout(() => setFlashBlackout(false), 1200);
        api.getState().then(setSimState).catch(() => {});
      },
    });

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    return () => es.close();
  }, []);

  // Displayed state: replay snapshot or live state
  const displayState =
    replayStep !== null
      ? (history.snapshots.find((s) => s.step === replayStep)?.state ?? simState)
      : simState;

  const displayLogs =
    replayStep !== null ? logs.filter((l) => l.step <= replayStep) : logs;

  // Control panel handlers
  const handleStart = async () => {
    try {
      await api.startMission();
      setMissionRunning(true);
    } catch {
      // ignore
    }
  };

  const handleStep = async (steps: number) => {
    try {
      await api.step(steps);
    } catch {
      // ignore
    }
  };

  const handleBlackout = async (zone_x: number, zone_y: number, radius: number) => {
    try {
      await api.triggerBlackout(zone_x, zone_y, radius);
    } catch {
      // ignore
    }
  };

  const handleReset = async () => {
    try {
      await api.reset();
      setMissionRunning(false);
      setLogs([]);
      setReplayStep(null);
      const [state, hist] = await Promise.all([api.getState(), api.getHistory()]);
      setSimState(state);
      setHistory(hist);
    } catch {
      // ignore
    }
  };

  return (
    <div
      className={`h-screen flex flex-col p-2 gap-2 bg-gray-950 ${
        flashBlackout ? 'blackout-flash-active' : ''
      }`}
    >
      {/* Header */}
      <header className="flex items-center justify-between px-3 py-1.5 bg-gray-900 rounded border border-gray-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-bold text-cyan-400 tracking-widest uppercase">
            Drone Swarm — Mission Control
          </h1>
          {replayStep !== null && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-amber-900 text-amber-300 font-medium uppercase tracking-wide">
              Replay Mode
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? 'bg-green-400' : 'bg-red-500 blink'
            }`}
          />
          <span className="text-gray-400">
            {connected
              ? `Step ${displayState?.mission_step ?? 0}`
              : 'Reconnecting...'}
          </span>
        </div>
      </header>

      {/* 4-panel grid */}
      <div className="flex-1 grid grid-cols-[1fr_280px] grid-rows-2 gap-2 min-h-0">
        <GridMap state={displayState} gridEffect={gridEffect} />

        {/* Right column top: Fleet / Mesh tabs */}
        <div className="bg-gray-900 rounded border border-gray-800 p-2 flex flex-col min-h-0">
          <div className="flex gap-1 mb-2 flex-shrink-0">
            <button
              onClick={() => setRightTab('fleet')}
              className={`flex-1 py-1 text-[10px] font-semibold uppercase tracking-wider rounded transition-colors ${
                rightTab === 'fleet'
                  ? 'bg-gray-700 text-cyan-300'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              Fleet
            </button>
            <button
              onClick={() => setRightTab('mesh')}
              className={`flex-1 py-1 text-[10px] font-semibold uppercase tracking-wider rounded transition-colors ${
                rightTab === 'mesh'
                  ? 'bg-gray-700 text-cyan-300'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              Mesh
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {rightTab === 'fleet' ? (
              <DronePanel state={displayState} />
            ) : (
              <MeshGraph state={displayState} />
            )}
          </div>
        </div>

        <ReasoningLog logs={displayLogs} voiceEnabled={voiceEnabled} />
        <ControlPanel
          state={displayState}
          missionRunning={missionRunning}
          voiceEnabled={voiceEnabled}
          onVoiceToggle={() => setVoiceEnabled((v) => !v)}
          onStart={handleStart}
          onStep={handleStep}
          onBlackout={handleBlackout}
          onReset={handleReset}
        />
      </div>

      {/* Timeline slider */}
      <TimelineSlider
        history={history}
        replayStep={replayStep}
        currentStep={simState?.mission_step ?? 0}
        onStepChange={setReplayStep}
        onGoLive={() => setReplayStep(null)}
      />
    </div>
  );
}
