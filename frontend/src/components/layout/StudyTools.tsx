import React, { useState } from 'react';
import { BACKEND_URL, OmniStudyAPI } from '../../services/api';
import { SlideSection } from '../../types/assessment';
export function SectionTools({ chapterId, section, refresh }: { chapterId: number; section: SlideSection; refresh: () => Promise<void> }) {
  const [versions, setVersions] = useState<{id:number;reason:string;created_at:string}[]>([]);
  const [citations, setCitations] = useState<{page:number;url:string}[]>([]);
  const [open,setOpen] = useState(false);
  const load = async () => { const [sources,history] = await Promise.all([OmniStudyAPI.sources(chapterId,section.id),OmniStudyAPI.noteVersions(chapterId,section.id)]);setCitations(sources.citations);setVersions(history);setOpen(true); };
  return <div className="text-xs text-indigo-200 space-y-2"><button className="underline" onClick={load}>View supporting slides & note history</button>{open && <div className="rounded-lg bg-slate-950 p-3 space-y-2"><div className="flex gap-2 flex-wrap">{citations.map(c => <a key={c.page} className="underline" target="_blank" rel="noreferrer" href={`${BACKEND_URL}${c.url}`}>Slide {c.page}</a>)}</div><div>Saved versions: {versions.length}</div>{versions.map(v => <button className="block underline" key={v.id} onClick={async () => { await OmniStudyAPI.restoreNote(chapterId, section.id,v.id);await refresh();await load(); }}>Restore {new Date(v.created_at).toLocaleString()} ({v.reason})</button>)}</div>}</div>;
}
export function WorkspaceTools({ chapterId, refresh }: { chapterId: number; refresh: () => Promise<void> }) {
  const [page,setPage] = useState(1);const [text,setText] = useState('');const [open,setOpen] = useState(false);
  return <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-xs space-y-3">
    <div className="flex gap-4 flex-wrap"><a className="underline" href={`${BACKEND_URL}/api/backup`}>Download study-data backup</a><label className="underline cursor-pointer">Restore study backup<input className="hidden" type="file" accept=".zip" onChange={async e => { const file=e.target.files?.[0];if(!file || !window.confirm('Restore this backup? Current study data will be replaced. A recovery backup is created first. API credentials and campus login are excluded.'))return;const form=new FormData();form.append('backup',file);await OmniStudyAPI.restoreBackup(form);window.location.reload(); }}/></label><button className="underline" onClick={()=>setOpen(!open)}>Add verified slide transcription</button></div>
    {open && <div className="space-y-2"><p>For image-only slides, type or paste a verified transcription. This becomes source evidence for future generation.</p><label>Slide page <input aria-label="Slide page" className="bg-slate-800 p-1 w-20" type="number" min={1} value={page} onChange={e=>setPage(Number(e.target.value))}/></label><textarea aria-label="Verified slide transcription" className="w-full bg-slate-800 p-2" value={text} onChange={e=>setText(e.target.value)} /><button onClick={async()=>{await OmniStudyAPI.saveSlideText(chapterId,page,text);setText('');await refresh();}}>Save verified transcription</button></div>}
  </div>;
}
