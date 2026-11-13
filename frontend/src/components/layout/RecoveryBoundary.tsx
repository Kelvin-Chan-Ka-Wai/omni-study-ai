import React from 'react';
import { OmniStudyAPI } from '../../services/api';
export class RecoveryBoundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <main role="alert" className="p-10 bg-slate-950 text-white min-h-screen"><h1>We could not display this workspace</h1><p>Your saved notes and assessments are safe.</p><button onClick={() => window.location.reload()}>Reload workspace</button></main>;
    return this.props.children;
  }
}
export function RequestStatus() {
  const [message, setMessage] = React.useState('');
  const [running, setRunning] = React.useState(false);
  React.useEffect(() => {
    const error = (e: Event) => setMessage(String((e as CustomEvent).detail));
    const job = (e: Event) => setRunning(Boolean((e as CustomEvent).detail));
    const rejection = (e: PromiseRejectionEvent) => { e.preventDefault(); setMessage(e.reason?.message || 'Request failed. Please retry.'); };
    window.addEventListener('omnistudy-error', error); window.addEventListener('omnistudy-job', job); window.addEventListener('unhandledrejection', rejection);
    return () => { window.removeEventListener('omnistudy-error', error); window.removeEventListener('omnistudy-job', job); window.removeEventListener('unhandledrejection', rejection); };
  }, []);
  return <div className="fixed bottom-4 right-4 z-[100] max-w-md space-y-2" aria-live="polite">
    {running && <div className="rounded-xl bg-indigo-950 text-white p-4">Generating selected content… <button className="underline" onClick={() => OmniStudyAPI.cancelGeneration()}>Cancel generation</button></div>}
    {message && <div role="alert" className="rounded-xl bg-rose-950 text-white p-4">{message} <button className="underline" onClick={() => setMessage('')}>Dismiss</button></div>}
  </div>;
}
