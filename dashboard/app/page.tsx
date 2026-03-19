'use client';

import { useEffect, useRef, useState } from 'react';
import {
  api,
  connectSSE,
  DisasterEvent,
  GameScore,
  HistoryResponse,
  LessonLearned,
  LogEntry,
  MissionCompleteData,
  RescueToast,
  ScoreBreakdown,
  SimState,
  SurvivorState,
  WarningEvent,
} from '@/lib/api';
import GridMap from '@/components/GridMap';
import DronePanel from '@/components/DronePanel';
import RescueToastItem from '@/components/RescueToast';
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
  const [lessons, setLessons] = useState<LessonLearned[]>([]);
  const [missionNum, setMissionNum] = useState(1);
  const [visibleLessons, setVisibleLessons] = useState(0);

  // Gamification state
  const [toasts, setToasts] = useState<RescueToast[]>([]);
  const [gameScore, setGameScore] = useState<GameScore>({ total: 0, livesSaved: 0, streak: 0, lastRescueStep: null });
  const [scorePop, setScorePop] = useState(false);
  const [livesPop, setLivesPop] = useState(false);
  const [newlyFoundIds, setNewlyFoundIds] = useState<Set<number>>(new Set());
  const [rescueBursts, setRescueBursts] = useState<Map<number, [number, number]>>(new Map());
  const [activeWarnings, setActiveWarnings] = useState<WarningEvent[]>([]);
  const prevSurvivorsRef = useRef<Map<number, SurvivorState>>(new Map());

  // Keep a ref to the latest simState for use in SSE handlers
  const simStateRef = useRef<SimState | null>(null);
  simStateRef.current = simState;

  // Survivor state transition detection
  useEffect(() => {
    if (!simState) return;
    const prev = prevSurvivorsRef.current;
    const newlyFound: number[] = [];
    const newlyRescued: SurvivorState[] = [];

    for (const s of simState.survivors) {
      const prevS = prev.get(s.survivor_id);
      if (prevS && !prevS.found && s.found) newlyFound.push(s.survivor_id);
      if (prevS && !prevS.rescued && s.rescued) newlyRescued.push(s);
    }

    if (newlyFound.length > 0) {
      setNewlyFoundIds((cur) => { const next = new Set(cur); newlyFound.forEach((id) => next.add(id)); return next; });
      const ids = [...newlyFound];
      setTimeout(() => {
        setNewlyFoundIds((cur) => { const next = new Set(cur); ids.forEach((id) => next.delete(id)); return next; });
      }, 4000);
    }

    if (newlyRescued.length > 0) {
      // Rescue burst positions
      setRescueBursts((cur) => {
        const next = new Map(cur);
        for (const s of newlyRescued) { if (s.position) next.set(s.survivor_id, s.position); }
        return next;
      });
      const rescuedIds = newlyRescued.map((s) => s.survivor_id);
      setTimeout(() => {
        setRescueBursts((cur) => { const next = new Map(cur); rescuedIds.forEach((id) => next.delete(id)); return next; });
      }, 1400);

      // Scoring
      const stepNow = simState.mission_step;
      setGameScore((prev) => {
        const isStreak = prev.lastRescueStep !== null && stepNow - prev.lastRescueStep <= 5;
        let pointsEarned = 0;
        for (const s of newlyRescued) {
          const base = s.severity === 'CRITICAL' ? 100 : s.severity === 'MODERATE' ? 70 : 50;
          pointsEarned += base + Math.round(s.health * 50);
        }
        return {
          total: prev.total + pointsEarned,
          livesSaved: prev.livesSaved + newlyRescued.length,
          streak: isStreak ? prev.streak + newlyRescued.length : newlyRescued.length,
          lastRescueStep: stepNow,
        };
      });

      setScorePop(true); setLivesPop(true);
      setTimeout(() => setScorePop(false), 500);
      setTimeout(() => setLivesPop(false), 450);

      // Toasts
      for (const s of newlyRescued) {
        const base = s.severity === 'CRITICAL' ? 100 : s.severity === 'MODERATE' ? 70 : 50;
        const bonus = Math.round(s.health * 50);
        const toast: RescueToast = {
          id: `${s.survivor_id}-${Date.now()}`,
          survivorId: s.survivor_id,
          severity: s.severity,
          healthAtRescue: s.health,
          points: base + bonus,
          dismissing: false,
        };
        setToasts((cur) => [...cur, toast]);
        setTimeout(() => {
          setToasts((cur) => cur.map((t) => t.id === toast.id ? { ...t, dismissing: true } : t));
          setTimeout(() => setToasts((cur) => cur.filter((t) => t.id !== toast.id)), 320);
        }, 3000);
      }
    }

    prevSurvivorsRef.current = new Map(simState.survivors.map((s) => [s.survivor_id, s]));
  }, [simState]);

  useEffect(() => {
    // Initial data load
    api.getState().then(setSimState).catch(() => {});
    api.getLogs().then(setLogs).catch(() => {});
    api.getHistory().then(setHistory).catch(() => {});
    api.getLessons().then((l) => {
      setLessons(l);
      if (l.length > 0) {
        const maxMission = Math.max(...l.map((x) => x.mission_num || 0));
        setMissionNum(maxMission + 1);
      }
    }).catch(() => {});

    // SSE subscription
    const es = connectSSE({
      onState: (state) => {
        setSimState(state);
        // Clean up resolved warnings based on state.warning_events
        if (state.warning_events) {
          const resolvedTypes = new Set(
            state.warning_events
              .filter((w) => w.resolved)
              .map((w) => `${w.type}-${w.step}`)
          );
          if (resolvedTypes.size > 0) {
            setActiveWarnings((prev) =>
              prev.filter((w) => !resolvedTypes.has(`${w.type}-${w.step}`))
            );
          }
        }
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
      onWarning: (warning) => {
        setActiveWarnings((prev) => [...prev, warning]);
      },
      onMissionComplete: (data) => {
        setMissionComplete(true);
        setCompletionData(data);
        setMissionRunning(false);
        // Fetch lessons after a short delay (give lesson extraction time)
        setTimeout(() => {
          api.getLessons().then((l) => {
            setLessons(l);
            // Animate lessons appearing one by one
            setVisibleLessons(0);
            const currentMissionLessons = l.filter(
              (x) => x.mission_num === (missionNum || 1)
            );
            currentMissionLessons.forEach((_, i) => {
              setTimeout(() => setVisibleLessons(i + 1), (i + 1) * 600);
            });
          }).catch(() => {});
        }, 3000);
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
      setToasts([]);
      setGameScore({ total: 0, livesSaved: 0, streak: 0, lastRescueStep: null });
      setNewlyFoundIds(new Set());
      setRescueBursts(new Map());
      setActiveWarnings([]);
      prevSurvivorsRef.current = new Map();
      setVisibleLessons(0);
      const [state, hist] = await Promise.all([api.getState(), api.getHistory()]);
      setSimState(state);
      setHistory(hist);
      api.getLessons().then((l) => {
        setLessons(l);
        if (l.length > 0) {
          const maxMission = Math.max(...l.map((x) => x.mission_num || 0));
          setMissionNum(maxMission + 1);
        }
      }).catch(() => {});
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
        <GridMap
          state={displayState}
          gridEffect={gridEffect}
          isReplaying={replayStep !== null}
          newlyFoundIds={newlyFoundIds}
          rescueBursts={rescueBursts}
          activeWarnings={activeWarnings}
        />

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
                <DronePanel
                  state={displayState}
                  gameScore={gameScore}
                  scorePop={scorePop}
                  livesPop={livesPop}
                  backendScore={displayState?.score ?? null}
                  missionNum={missionNum}
                />
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

      {/* Rescue toast stack — fixed top-right, stacks vertically */}
      <div className="fixed top-14 left-2 z-40 flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <RescueToastItem key={toast.id} toast={toast} />
        ))}
      </div>

      {/* Mission Completed overlay */}
      {missionComplete && completionData && (() => {
        const score = completionData.score;
        const gradeColor: Record<string, string> = {
          A: 'text-green-500', B: 'text-blue-500', C: 'text-yellow-500', D: 'text-orange-500', F: 'text-red-500',
        };
        const currentLessons = lessons.filter((l) => l.mission_num === missionNum);
        return (
          <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl p-8 max-w-lg w-full max-h-[90vh] overflow-y-auto">
              <div className="text-center mb-6">
                {score ? (
                  <div className={`inline-flex items-center justify-center w-20 h-20 rounded-full mb-3 bg-gray-900`}>
                    <span className={`text-4xl font-black ${gradeColor[score.grade] ?? 'text-gray-400'}`}>
                      {score.grade}
                    </span>
                  </div>
                ) : (
                  <div className={`inline-flex items-center justify-center w-16 h-16 rounded-full mb-3 ${
                    completionData.stats.rescued >= completionData.stats.total_survivors
                      ? 'bg-green-100 text-green-600'
                      : 'bg-amber-100 text-amber-600'
                  }`}>
                    <span className="text-3xl">
                      {completionData.stats.rescued >= completionData.stats.total_survivors ? '\u2713' : '!'}
                    </span>
                  </div>
                )}
                <h2 className="text-xl font-bold text-gray-900">
                  Mission #{missionNum} Complete
                </h2>
                {score && (
                  <p className="text-2xl font-black text-yellow-500 mt-1">
                    {score.total.toLocaleString()} pts
                  </p>
                )}
                <p className="text-sm text-gray-500 mt-1">
                  {completionData.stats.rescued >= completionData.stats.total_survivors
                    ? 'All survivors rescued successfully'
                    : `${completionData.stats.rescued} of ${completionData.stats.total_survivors} survivors rescued`}
                </p>
              </div>

              {/* Score breakdown */}
              {score && (
                <div className="grid grid-cols-5 gap-2 mb-4">
                  <div className="bg-green-50 rounded-lg p-2 text-center">
                    <div className="text-sm font-bold text-green-700">+{score.rescue_points}</div>
                    <div className="text-[8px] text-green-600 uppercase">Rescue</div>
                  </div>
                  <div className="bg-blue-50 rounded-lg p-2 text-center">
                    <div className="text-sm font-bold text-blue-700">+{score.speed_bonus}</div>
                    <div className="text-[8px] text-blue-600 uppercase">Speed</div>
                  </div>
                  <div className="bg-cyan-50 rounded-lg p-2 text-center">
                    <div className="text-sm font-bold text-cyan-700">+{score.coverage_bonus}</div>
                    <div className="text-[8px] text-cyan-600 uppercase">Coverage</div>
                  </div>
                  <div className="bg-slate-50 rounded-lg p-2 text-center">
                    <div className="text-sm font-bold text-slate-700">+{score.efficiency_bonus}</div>
                    <div className="text-[8px] text-slate-600 uppercase">Efficiency</div>
                  </div>
                  <div className="bg-red-50 rounded-lg p-2 text-center">
                    <div className="text-sm font-bold text-red-700">-{score.death_penalty}</div>
                    <div className="text-[8px] text-red-600 uppercase">Deaths</div>
                  </div>
                </div>
              )}

              {/* Stats grid */}
              <div className="grid grid-cols-3 gap-3 mb-4">
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
              </div>

              {/* Lessons learned */}
              {currentLessons.length > 0 && (
                <div className="mb-4">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-2">
                    Lessons Learned
                  </div>
                  <div className="space-y-1.5">
                    {currentLessons.slice(0, visibleLessons).map((lesson, i) => (
                      <div
                        key={i}
                        className="bg-purple-50 border border-purple-200 rounded-lg p-2 transition-all duration-500"
                        style={{ opacity: 1, transform: 'translateY(0)' }}
                      >
                        <div className="flex items-start gap-1.5">
                          <span className={`text-[8px] px-1 py-0.5 rounded font-bold flex-shrink-0 mt-0.5 ${
                            lesson.priority === 'high'
                              ? 'bg-red-100 text-red-700'
                              : lesson.priority === 'medium'
                                ? 'bg-yellow-100 text-yellow-700'
                                : 'bg-green-100 text-green-700'
                          }`}>
                            {lesson.priority.toUpperCase()}
                          </span>
                          <div>
                            <div className="text-[11px] text-gray-800 font-medium">{lesson.lesson}</div>
                            {lesson.evidence && (
                              <div className="text-[9px] text-gray-500 mt-0.5">{lesson.evidence}</div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Mission history bar chart */}
              {(() => {
                const missionMap = new Map<number, { score: number; grade: string }>();
                for (const l of lessons) {
                  if (l.mission_num && !missionMap.has(l.mission_num)) {
                    missionMap.set(l.mission_num, { score: l.mission_score, grade: l.mission_grade });
                  }
                }
                if (score) {
                  missionMap.set(missionNum, { score: score.total, grade: score.grade });
                }
                const missions = Array.from(missionMap.entries()).sort(([a], [b]) => a - b);
                if (missions.length < 2) return null;
                const maxScore = Math.max(...missions.map(([, m]) => m.score), 1);
                const barGrade: Record<string, string> = {
                  A: 'bg-green-500', B: 'bg-blue-500', C: 'bg-yellow-500', D: 'bg-orange-500', F: 'bg-red-500',
                };
                return (
                  <div className="mb-4">
                    <div className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-2">
                      Mission History
                    </div>
                    <div className="flex items-end gap-1.5 h-20">
                      {missions.map(([num, m]) => (
                        <div key={num} className="flex-1 flex flex-col items-center gap-0.5">
                          <span className="text-[8px] text-gray-500 font-medium">{m.score}</span>
                          <div className="w-full flex flex-col justify-end" style={{ height: '48px' }}>
                            <div
                              className={`w-full rounded-t ${barGrade[m.grade] ?? 'bg-gray-400'} transition-all duration-700 ${
                                num === missionNum ? 'ring-2 ring-yellow-400' : ''
                              }`}
                              style={{ height: `${Math.max(4, (m.score / maxScore) * 48)}px` }}
                            />
                          </div>
                          <span className={`text-[8px] font-bold ${num === missionNum ? 'text-yellow-600' : 'text-gray-400'}`}>
                            #{num}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}

              <button
                onClick={handleReset}
                className="w-full py-2.5 bg-cyan-600 hover:bg-cyan-700 text-white font-semibold rounded-lg transition-colors text-sm"
              >
                Reset &amp; Start New Mission
              </button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
