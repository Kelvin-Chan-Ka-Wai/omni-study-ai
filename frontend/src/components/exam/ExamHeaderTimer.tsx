import React, { useEffect, useRef, useState } from 'react';
import { ActiveExamSession } from '../../types/assessment';
import { OmniStudyAPI } from '../../services/api';
interface Props { session: ActiveExamSession; isSubmitted: boolean; onSessionChange: (s: ActiveExamSession) => void; onTimeUpdate: (n: number) => void; onAutoSubmit: () => void; }
export function ExamHeaderTimer({ session, isSubmitted, onSessionChange, onTimeUpdate, onAutoSubmit }: Props) {
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const submitRef = useRef(onAutoSubmit); submitRef.current = onAutoSubmit;
  const fired = useRef(false);
  useEffect(() => { fired.current = false; }, [session.session_id]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const deadline = new Date(session.deadline_at || 0).getTime();
  const graceStart = session.grace_started_at ? new Date(session.grace_started_at).getTime() : deadline;
  const grace = session.status === 'grace_upload' || (!session.is_paused && now >= deadline);
  const remaining = session.is_paused ? (session.paused_remaining || 0) : Math.max(0, ((grace ? graceStart + session.grace_period_minutes * 60000 : deadline) - now) / 1000);
  useEffect(() => {
    if (isSubmitted || session.is_paused) return;
    onTimeUpdate(Math.floor(Math.min(session.time_limit_minutes * 60, Math.max(0, session.time_limit_minutes * 60 - (deadline - now) / 1000))));
    if (grace && remaining <= 0 && !fired.current) { fired.current = true; submitRef.current(); }
  }, [now, isSubmitted, session.is_paused]);
  const control = async (pause: boolean, enterGrace = false) => { setBusy(true); try { onSessionChange(await OmniStudyAPI.controlTimer(session.session_id, pause, enterGrace)); } finally { setBusy(false); } };
  return <div className="sticky top-0 z-20 flex flex-wrap justify-between gap-3 rounded-xl bg-slate-900 p-4 border border-slate-700">
    <div><strong>{session.mode.replace(/_/g,' ')}</strong> · {isSubmitted ? 'Completed' : session.is_paused ? 'Paused (practice)' : grace ? 'Photo upload window' : 'Writing time'} {!isSubmitted && <span className="font-mono text-emerald-300">{Math.floor(remaining / 60)}:{String(Math.floor(remaining % 60)).padStart(2,'0')}</span>}</div>
    {!isSubmitted && <div className="flex gap-3"><button disabled={busy || grace} onClick={() => control(!session.is_paused)}>{session.is_paused ? 'Resume' : 'Pause practice'}</button><button disabled={busy || grace} onClick={() => control(false,true)}>Finish writing / upload photos</button><button disabled={busy} onClick={onAutoSubmit}>Submit & grade</button></div>}
  </div>;
}
