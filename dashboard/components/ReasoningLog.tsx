'use client';

import { useEffect, useRef, useState } from 'react';
import { LogEntry, LogType } from '@/lib/api';

const LOG_COLOR: Record<LogType, string> = {
  reasoning: 'text-blue-300',
  tool_call: 'text-green-400',
  result: 'text-gray-400',
  triage: 'text-purple-300',
  system: 'text-cyan-400',
  warning: 'text-orange-400',
  error: 'text-red-400',
};

const LOG_TAG: Record<LogType, string> = {
  reasoning: '[RSN]',
  tool_call: '[TOOL]',
  result: '[RES]',
  triage: '[TRIAGE]',
  system: '[SYS]',
  warning: '[WARN]',
  error: '[ERR]',
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toISOString().slice(11, 19);
}

interface ReasoningLogProps {
  logs: LogEntry[];
}

export default function ReasoningLog({ logs }: ReasoningLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  // Detect if user manually scrolled up — pause auto-scroll
  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
    setAutoScroll(atBottom);
  };

  return (
    <div className="bg-gray-900 rounded border border-gray-800 p-2 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-1 flex-shrink-0">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Agent Reasoning Log
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-gray-600">{logs.length} entries</span>
          {!autoScroll && (
            <button
              onClick={() => {
                setAutoScroll(true);
                bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
              }}
              className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-900 text-cyan-300 hover:bg-cyan-800 transition-colors"
            >
              Resume scroll
            </button>
          )}
        </div>
      </div>

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto log-scroll font-mono text-[10px] leading-relaxed space-y-px"
      >
        {logs.length === 0 && (
          <div className="text-gray-700 py-4 text-center text-xs">
            Waiting for agent...
          </div>
        )}

        {logs.map((entry, i) => (
          <div
            key={i}
            className={`px-1.5 py-0.5 rounded-sm border-l-2 ${
              entry.is_critical
                ? 'bg-red-950/25 border-red-600'
                : 'border-transparent'
            }`}
          >
            <span className="text-gray-700 mr-1.5 select-none">
              s{entry.step}
            </span>
            <span
              className={`mr-1.5 font-semibold ${
                LOG_COLOR[entry.type as LogType] ?? 'text-gray-400'
              }`}
            >
              {LOG_TAG[entry.type as LogType] ?? `[${entry.type}]`}
            </span>
            <span
              className={`break-words whitespace-pre-wrap ${
                LOG_COLOR[entry.type as LogType] ?? 'text-gray-400'
              }`}
            >
              {entry.message}
            </span>
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
