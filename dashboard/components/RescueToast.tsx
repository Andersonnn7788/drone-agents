'use client';

import { RescueToast, Severity } from '@/lib/api';

const SEVERITY_STYLES: Record<Severity, { bg: string; border: string; label: string; icon: string }> = {
  CRITICAL: { bg: 'bg-red-600',    border: 'border-red-500',    label: 'text-red-100',   icon: '🚨' },
  MODERATE: { bg: 'bg-orange-500', border: 'border-orange-400', label: 'text-orange-100', icon: '⚠️' },
  STABLE:   { bg: 'bg-green-600',  border: 'border-green-500',  label: 'text-green-100', icon: '✅' },
};

interface Props {
  toast: RescueToast;
}

export default function RescueToastItem({ toast }: Props) {
  const s = SEVERITY_STYLES[toast.severity];
  const healthPct = Math.round(toast.healthAtRescue * 100);
  const bonus = Math.round(toast.healthAtRescue * 50);
  const base = toast.points - bonus;

  return (
    <div
      className={`
        ${toast.dismissing ? 'toast-slide-out' : 'toast-slide-in'}
        ${s.bg} ${s.border}
        border-2 rounded-xl shadow-2xl px-4 py-3 min-w-[220px] max-w-[260px]
        pointer-events-auto select-none
      `}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="text-base leading-none">{s.icon}</span>
          <span className={`text-xs font-black ${s.label} uppercase tracking-wider`}>
            #{toast.survivorId} Rescued!
          </span>
        </div>
        <span className="text-white text-sm font-black tabular-nums">
          +{toast.points}
          <span className="text-[10px] font-semibold opacity-80 ml-0.5">pts</span>
        </span>
      </div>

      {/* Health bar */}
      <div className="mt-2 h-1.5 rounded-full bg-black/25">
        <div
          className="h-full rounded-full bg-white/70 transition-none"
          style={{ width: `${healthPct}%` }}
        />
      </div>

      {/* Footer row */}
      <div className="flex items-center justify-between mt-1.5">
        <span className={`text-[10px] ${s.label} opacity-80 font-medium`}>
          {toast.severity} · {healthPct}% health
        </span>
        <span className={`text-[9px] ${s.label} opacity-60`}>
          {base} + {bonus} bonus
        </span>
      </div>
    </div>
  );
}
