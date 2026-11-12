import React, { useEffect, useState } from 'react';
import { Clock, Pause, Play, Camera, Send } from 'lucide-react';

interface Props {
  mode: string;
  timeLimitMinutes: number;
  gracePeriodMinutes: number;
  isSubmitted: boolean;
  onTimeUpdate: (spentSeconds: number, isGraceMode: boolean) => void;
  onAutoSubmit: () => void;
}

export const ExamHeaderTimer: React.FC<Props> = ({
  mode,
  timeLimitMinutes,
  gracePeriodMinutes,
  isSubmitted,
  onTimeUpdate,
  onAutoSubmit,
}) => {
  const [remainingSeconds, setRemainingSeconds] = useState(timeLimitMinutes * 60);
  const [spentSeconds, setSpentSeconds] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const [inGracePeriod, setInGracePeriod] = useState(false);
  const [graceRemaining, setGraceRemaining] = useState(gracePeriodMinutes * 60);

  useEffect(() => {
    setRemainingSeconds(timeLimitMinutes * 60);
    setGraceRemaining(gracePeriodMinutes * 60);
    setSpentSeconds(0);
    setIsPaused(false);
    setInGracePeriod(false);
  }, [timeLimitMinutes, gracePeriodMinutes, mode]);

  useEffect(() => {
    if (isSubmitted || isPaused) return;

    const timer = setInterval(() => {
      if (!inGracePeriod) {
        setSpentSeconds((prev) => {
          const next = prev + 1;
          onTimeUpdate(next, false);
          return next;
        });
        setRemainingSeconds((prev) => {
          if (prev <= 1) {
            setInGracePeriod(true);
            return 0;
          }
          return prev - 1;
        });
      } else {
        setGraceRemaining((prev) => {
          if (prev <= 1) {
            clearInterval(timer);
            onAutoSubmit();
            return 0;
          }
          return prev - 1;
        });
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [isSubmitted, isPaused, inGracePeriod]);

  const formatTime = (secs: number) => {
    const hrs = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (hrs > 0) {
      return `${hrs}:${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  return (
    <div className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/95 px-4 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <span className="rounded-lg bg-indigo-500/20 px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-indigo-300 border border-indigo-500/30">
          {mode.replace('_', ' ')}
        </span>

        {!inGracePeriod ? (
          <div className="flex items-center gap-2 text-sm font-mono">
            <Clock className="h-4 w-4 text-emerald-400" />
            <span className="text-slate-300">Exam Timer:</span>
            <span
              className={`text-base font-bold ${
                remainingSeconds < 300 ? 'text-rose-400 animate-pulse' : 'text-emerald-400'
              }`}
            >
              {formatTime(remainingSeconds)}
            </span>
            {isPaused && (
              <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">
                PAUSED
              </span>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 rounded-lg bg-amber-500/20 border border-amber-500/40 px-3 py-1 text-sm font-mono text-amber-200">
            <Camera className="h-4 w-4 text-amber-400 animate-bounce" />
            <span>5-Min Cmd+V Photo Upload Grace Window:</span>
            <span className="font-bold text-amber-300">{formatTime(graceRemaining)}</span>
          </div>
        )}
      </div>

      {!isSubmitted && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsPaused((p) => !p)}
            className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 transition"
          >
            {isPaused ? <Play className="h-3.5 w-3.5 text-emerald-400" /> : <Pause className="h-3.5 w-3.5 text-amber-400" />}
            {isPaused ? 'Resume Timer' : 'Pause Timer'}
          </button>

          {!inGracePeriod && (
            <button
              type="button"
              onClick={() => setInGracePeriod(true)}
              className="flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20 transition"
              title="Finish writing and start the 5-minute grace window to paste (Cmd+V) or AirDrop handwritten calculation photos"
            >
              <Camera className="h-3.5 w-3.5" />
              5-Min Photo Upload Window
            </button>
          )}

          <button
            type="button"
            onClick={onAutoSubmit}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow hover:bg-indigo-500 transition"
          >
            <Send className="h-3.5 w-3.5" />
            Submit & Grade Exam
          </button>
        </div>
      )}
    </div>
  );
};
