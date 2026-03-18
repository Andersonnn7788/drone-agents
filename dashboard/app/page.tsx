'use client';

import { useEffect, useRef, useState } from 'react';
import {
  api,
  connectSSE,
  DisasterEvent,
  HistoryResponse,
  LogEntry,
  MissionCompleteData,
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
  const [missionComplete, setMissionComplete] = useState(false);
  const [completionData, setCompletionData] = useState<MissionCompleteData | null>(null);

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
      onMissionComplete: (data) => {
        setMissionComplete(true);
        setCompletionData(data);
        setMissionRunning(false);
      },
    });

    es.onopen = () => {
      setConnected(true);
      // Backfill any logs missed during disconnect gap
      api.getLogs().then(setLogs).catch(() => {});
    };
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
      setMissionComplete(false);
      setCompletionData(null);
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
      className={`h-screen flex flex-col p-2 gap-2 bg-slate-100 ${
        flashBlackout ? 'blackout-flash-active' : ''
      }`}
    >
      {/* Header */}
      <header className="flex items-center justify-between px-3 py-1.5 bg-white rounded border border-gray-200 shadow-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-bold text-cyan-700 tracking-widest uppercase">
            Drone Swarm — Mission Control
          </h1>
          {replayStep !== null && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200 font-medium uppercase tracking-wide">
              Replay Mode
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? 'bg-green-500' : 'bg-red-500 blink'
            }`}
          />
          <span className="text-gray-600">
            {connected
              ? `Step ${displayState?.mission_step ?? 0}`
              : 'Reconnecting...'}
          </span>
        </div>
      </header>

      {/* 3-column grid: GridMap | ReasoningLog | Right sidebar */}
      <div className="flex-1 grid grid-cols-[1fr_1fr_260px] gap-2 min-h-0">
        <GridMap state={displayState} gridEffect={gridEffect} isReplaying={replayStep !== null} />

        <ReasoningLog logs={displayLogs} voiceEnabled={voiceEnabled} />

        {/* Right column: Fleet/Mesh tabs + Controls stacked */}
        <div className="flex flex-col gap-2 min-h-0">
          <div className="bg-white rounded border border-gray-200 shadow-sm p-2 flex flex-col min-h-0 flex-1">
            <div className="flex gap-1 mb-2 flex-shrink-0">
              <button
                onClick={() => setRightTab('fleet')}
                className={`flex-1 py-1 text-[10px] font-semibold uppercase tracking-wider rounded transition-colors ${
                  rightTab === 'fleet'
                    ? 'bg-cyan-50 text-cyan-700 border border-cyan-200'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                Fleet
              </button>
              <button
                onClick={() => setRightTab('mesh')}
                className={`flex-1 py-1 text-[10px] font-semibold uppercase tracking-wider rounded transition-colors ${
                  rightTab === 'mesh'
                    ? 'bg-cyan-50 text-cyan-700 border border-cyan-200'
                    : 'text-gray-500 hover:text-gray-700'
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
      </div>

      {/* Timeline slider */}
      <TimelineSlider
        history={history}
        replayStep={replayStep}
        currentStep={simState?.mission_step ?? 0}
        onStepChange={setReplayStep}
        onGoLive={() => setReplayStep(null)}
      />

      {/* Mission Completed overlay */}
      {missionComplete && completionData && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-white rounded-xl shadow-2xl p-8 max-w-md w-full mx-4">
            <div className="text-center mb-6">
              <div className={`inline-flex items-center justify-center w-16 h-16 rounded-full mb-3 ${
                completionData.stats.rescued >= completionData.stats.total_survivors
                  ? 'bg-green-100 text-green-600'
                  : 'bg-amber-100 text-amber-600'
              }`}>
                <span className="text-3xl">
                  {completionData.stats.rescued >= completionData.stats.total_survivors ? '\u2713' : '!'}
                </span>
              </div>
              <h2 className="text-xl font-bold text-gray-900">Mission Completed</h2>
              <p className="text-sm text-gray-500 mt-1">
                {completionData.stats.rescued >= completionData.stats.total_survivors
                  ? 'All survivors rescued successfully'
                  : `${completionData.stats.rescued} of ${completionData.stats.total_survivors} survivors rescued`}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-3 mb-6">
              <div className="bg-green-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-green-700">{completionData.stats.rescued}</div>
                <div className="text-[10px] text-green-600 uppercase tracking-wide">Rescued</div>
              </div>
              <div className="bg-blue-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-blue-700">{completionData.stats.alive}</div>
                <div className="text-[10px] text-blue-600 uppercase tracking-wide">Alive</div>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-slate-700">{completionData.mission_step}</div>
                <div className="text-[10px] text-slate-600 uppercase tracking-wide">Steps</div>
              </div>
              <div className="bg-cyan-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-cyan-700">{completionData.stats.coverage_pct}%</div>
                <div className="text-[10px] text-cyan-600 uppercase tracking-wide">Coverage</div>
              </div>
              <div className="bg-purple-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-purple-700">{completionData.stats.active_drones}</div>
                <div className="text-[10px] text-purple-600 uppercase tracking-wide">Drones Active</div>
              </div>
              <div className="bg-red-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-red-700">{completionData.disaster_event_count}</div>
                <div className="text-[10px] text-red-600 uppercase tracking-wide">Disasters</div>
              </div>
            </div>
            <button
              onClick={handleReset}
              className="w-full py-2.5 bg-cyan-600 hover:bg-cyan-700 text-white font-semibold rounded-lg transition-colors text-sm"
            >
              Reset &amp; Start New Mission
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
