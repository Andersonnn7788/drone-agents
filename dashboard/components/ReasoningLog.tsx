'use client';

import { useEffect, useRef, useState } from 'react';
import { LogEntry, LogType } from '@/lib/api';

const LOG_COLOR: Record<LogType, string> = {
  reasoning: 'text-blue-600',
  tool_call: 'text-green-600',
  result: 'text-gray-500',
  triage: 'text-purple-600',
  narrative: 'text-amber-600',
  system: 'text-cyan-600',
  warning: 'text-orange-600',
  error: 'text-red-600',
  reflection: 'text-pink-600',
};

const LOG_TAG: Record<LogType, string> = {
  reasoning: '[REASONING]',
  tool_call: '[TOOL]',
  result: '[RESULT]',
  triage: '[TRIAGE]',
  narrative: '[NARRATIVE]',
  system: '[SYSTEM]',
  warning: '[WARNING]',
  error: '[ERROR]',
  reflection: '[REFLECTION]',
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toISOString().slice(11, 19);
}

function cleanForSpeech(text: string): string {
  return text
    .replace(/\\n/g, ' ')           // literal \n from JSON
    .replace(/\n/g, '. ')           // real newlines → sentence breaks
    .replace(/[{}\[\]"]/g, '')      // strip JSON syntax
    .replace(/\s{2,}/g, ' ')        // collapse whitespace
    .trim();
}

interface ReasoningLogProps {
  logs: LogEntry[];
  voiceEnabled?: boolean;
}

export default function ReasoningLog({ logs, voiceEnabled = false }: ReasoningLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const prevLogCountRef = useRef(0);
  const keepaliveRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cancel speech when voice is disabled
  useEffect(() => {
    if (!voiceEnabled && typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      if (keepaliveRef.current) {
        clearInterval(keepaliveRef.current);
        keepaliveRef.current = null;
      }
    }
  }, [voiceEnabled]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  // Chrome keepalive — independent of log updates
  useEffect(() => {
    if (!voiceEnabled || typeof window === 'undefined' || !window.speechSynthesis) return;

    keepaliveRef.current = setInterval(() => {
      if (window.speechSynthesis.speaking) {
        window.speechSynthesis.pause();
        window.speechSynthesis.resume();
      }
    }, 5000);

    return () => {
      if (keepaliveRef.current) {
        clearInterval(keepaliveRef.current);
        keepaliveRef.current = null;
      }
    };
  }, [voiceEnabled]);

  // Voice narration for critical entries — no cleanup that touches keepalive
  useEffect(() => {
    if (!voiceEnabled || typeof window === 'undefined' || !window.speechSynthesis) return;

    // Only narrate new entries (not on replay shrink)
    if (logs.length <= prevLogCountRef.current) {
      prevLogCountRef.current = logs.length;
      return;
    }
    const newEntries = logs.slice(prevLogCountRef.current);
    prevLogCountRef.current = logs.length;

    for (const entry of newEntries) {
      if (entry.is_critical && ['reasoning', 'triage', 'narrative', 'system', 'reflection'].includes(entry.type)) {
        try {
          const utterance = new SpeechSynthesisUtterance(cleanForSpeech(entry.message));
          utterance.rate = 1.1;
          utterance.pitch = 0.9;
          window.speechSynthesis.speak(utterance);
        } catch {
          // Speech synthesis unavailable or blocked by browser policy
        }
      }
    }
  }, [logs, voiceEnabled]);

  // Detect if user manually scrolled up — pause auto-scroll
  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
    setAutoScroll(atBottom);
  };

  return (
    <div className="bg-white rounded border border-gray-200 shadow-sm p-2 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-1 flex-shrink-0">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Agent Reasoning Log
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-gray-400">{logs.length} entries</span>
          {!autoScroll && (
            <button
              onClick={() => {
                setAutoScroll(true);
                bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
              }}
              className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-50 text-cyan-700 border border-cyan-200 hover:bg-cyan-100 transition-colors"
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
          <div className="text-gray-400 py-4 text-center text-xs flex items-center justify-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-gray-300 inline-block animate-pulse" />
            Waiting for agent...
          </div>
        )}

        {logs.map((entry, i) => (
          <div
            key={i}
            className={`px-1.5 py-0.5 rounded-sm border-l-2 ${
              entry.type === 'reflection'
                ? 'bg-pink-50 border-pink-500'
                : entry.is_critical
                  ? 'bg-red-50 border-red-500'
                  : 'border-transparent'
            }`}
          >
            <span className="text-gray-400 mr-1.5 select-none">
              s{entry.step}
            </span>
            <span
              className={`mr-1.5 font-semibold ${
                LOG_COLOR[entry.type as LogType] ?? 'text-gray-500'
              }`}
            >
              {LOG_TAG[entry.type as LogType] ?? `[${entry.type}]`}
            </span>
            <span
              className={`break-words whitespace-pre-wrap ${
                LOG_COLOR[entry.type as LogType] ?? 'text-gray-500'
              }`}
            >
              {entry.message}
            </span>
            {voiceEnabled && entry.is_critical && ['reasoning', 'triage', 'narrative', 'system', 'reflection'].includes(entry.type) && (
              <span className="ml-1.5 text-[8px] px-1 py-0.5 rounded bg-yellow-100 text-yellow-700 border border-yellow-200 font-medium">NARR</span>
            )}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
