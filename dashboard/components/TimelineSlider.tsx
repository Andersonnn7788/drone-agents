'use client';

import { HistoryResponse } from '@/lib/api';

interface TimelineSliderProps {
  history: HistoryResponse;
  replayStep: number | null;
  currentStep: number;
  onStepChange: (step: number) => void;
  onGoLive: () => void;
}

export default function TimelineSlider({
  history,
  replayStep,
  currentStep,
  onStepChange,
  onGoLive,
}: TimelineSliderProps) {
  const totalSteps = Math.max(history.total_steps, currentStep);
  const isLive = replayStep === null;
  const sliderValue = isLive ? currentStep : replayStep;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = Number(e.target.value);
    if (v >= currentStep) {
      onGoLive();
    } else {
      onStepChange(v);
    }
  };

  return (
    <div className="bg-white rounded border border-gray-200 shadow-sm px-3 py-2 flex items-center gap-3 flex-shrink-0">
      <span className="text-[10px] text-gray-600 uppercase tracking-wider whitespace-nowrap font-medium">
        Timeline
      </span>

      <input
        type="range"
        min={0}
        max={totalSteps > 0 ? totalSteps : 1}
        value={sliderValue ?? 0}
        onChange={handleChange}
        disabled={totalSteps === 0}
        className="flex-1 accent-cyan-600 cursor-pointer disabled:opacity-30"
      />

      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-[10px] w-24 text-center">
          {isLive ? (
            <span className="text-green-600 font-medium">LIVE s{currentStep}</span>
          ) : (
            <span className="text-amber-700">Replay s{replayStep}</span>
          )}
        </span>

        {!isLive && (
          <button
            onClick={onGoLive}
            className="text-[10px] px-2 py-0.5 rounded bg-green-50 hover:bg-green-100
              text-green-700 font-medium whitespace-nowrap transition-colors border border-green-300"
          >
            Go Live
          </button>
        )}

        <span className="text-[10px] text-gray-400 whitespace-nowrap">
          {history.snapshots.length} snapshots
        </span>
      </div>
    </div>
  );
}
