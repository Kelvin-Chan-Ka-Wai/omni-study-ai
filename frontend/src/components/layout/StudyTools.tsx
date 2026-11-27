import React, { useState } from 'react';
import { BACKEND_URL, OmniStudyAPI, requestError } from '../../services/api';
import { SlideOutline, SlideSection } from '../../types/assessment';
export function SectionTools({ chapterId, section, refresh }: { chapterId: number; section: SlideSection; refresh: () => Promise<void> }) {
  const [versions, setVersions] = useState<{id:number;reason:string;created_at:string}[]>([]);
  const [citations, setCitations] = useState<{page:number;url:string}[]>([]);
  const [open,setOpen] = useState(false);
  const load = async () => { const [sources,history] = await Promise.all([OmniStudyAPI.sources(chapterId,section.id),OmniStudyAPI.noteVersions(chapterId,section.id)]);setCitations(sources.citations);setVersions(history);setOpen(true); };
  return <div className="text-xs text-indigo-200 space-y-2"><button className="underline" onClick={load}>View supporting slides & note history</button>{open && <div className="rounded-lg bg-slate-950 p-3 space-y-2"><div className="flex gap-2 flex-wrap">{citations.map(c => <a key={c.page} className="underline" target="_blank" rel="noreferrer" href={`${BACKEND_URL}${c.url}`}>Slide {c.page}</a>)}</div><div>Saved versions: {versions.length}</div>{versions.map(v => <button className="block underline" key={v.id} onClick={async () => { await OmniStudyAPI.restoreNote(chapterId, section.id,v.id);await refresh();await load(); }}>Restore {new Date(v.created_at).toLocaleString()} ({v.reason})</button>)}</div>}</div>;
}
export function WorkspaceTools({ chapterId, refresh, refreshScope }: { chapterId: number; refresh: () => Promise<void>; refreshScope: () => Promise<void> }) {
  const [page,setPage] = useState(1);const [text,setText] = useState('');const [open,setOpen] = useState(false);
  const [outline, setOutline] = useState<SlideOutline | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const review = async (apply = false) => {
    setReviewing(true);
    setReviewError('');
    try {
      setOutline(await OmniStudyAPI.reviewSlideOutline(chapterId, apply));
      if (apply) await refreshScope();
    } catch (error) {
      setReviewError(requestError(error, 'Could not review the slide scope.'));
    } finally {
      setReviewing(false);
    }
  };
  return <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-xs space-y-3">
    <div className="flex gap-4 flex-wrap"><a className="underline" href={`${BACKEND_URL}/api/backup`}>Download study-data backup</a><label className="underline cursor-pointer">Restore study backup<input className="hidden" type="file" accept=".zip" onChange={async e => { const file=e.target.files?.[0];if(!file || !window.confirm('Restore this backup? Current study data will be replaced. A recovery backup is created first. API credentials and campus login are excluded.'))return;const form=new FormData();form.append('backup',file);await OmniStudyAPI.restoreBackup(form);window.location.reload(); }}/></label><button className="underline" onClick={()=>setOpen(!open)}>Add verified slide transcription</button><button className="font-semibold text-indigo-300 underline" aria-expanded={!!outline} disabled={reviewing} onClick={() => outline ? setOutline(null) : void review()}>Review slide scope</button></div>
    {reviewError && <p role="alert" className="text-rose-200">{reviewError}</p>}
    {outline && <div className="space-y-3 rounded-lg bg-slate-950 p-3">
      <p className="font-semibold text-indigo-200">Sections for notes and quizzes</p>
      <ul className="space-y-1 text-slate-300">{outline.sections.map(section => <li key={section.section_code}><strong>{section.section_title}</strong> · {section.slide_pages}</li>)}</ul>
      {outline.excluded.length > 0 && <div className="space-y-1 text-slate-300">
        <p className="font-semibold text-slate-200">Excluded from study</p>
        <ul>{outline.excluded.map(item => <li key={item.page}>
          <a href={`${BACKEND_URL}${outline.file_url}#page=${item.page}`} target="_blank" rel="noreferrer" className="underline">Slide {item.page}</a> · {item.reason}{item.title ? `: ${item.title}` : ''}
        </li>)}</ul>
        <p>If an excluded slide has study material, add a verified slide transcription and review the scope again.</p>
      </div>}
      {outline.visual_pages.length > 0 && <p className="text-amber-200">Slides kept for transcription: {outline.visual_pages.join(', ')}.</p>}
      {outline.can_apply && <div className="space-y-2">
        <p>Applying this outline keeps your old notes and quiz history. Sections with changed page ranges start with an empty note.</p>
        <button type="button" disabled={reviewing} onClick={() => void review(true)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-white">Apply reviewed sections</button>
      </div>}
    </div>}
    {open && <div className="space-y-2"><p>Type or paste a verified transcription for a visual slide or an excluded slide with study material. This becomes source evidence for future generation.</p><label>Slide page <input aria-label="Slide page" className="bg-slate-800 p-1 w-20" type="number" min={1} value={page} onChange={e=>setPage(Number(e.target.value))}/></label><textarea aria-label="Verified slide transcription" className="w-full bg-slate-800 p-2" value={text} onChange={e=>setText(e.target.value)} /><button onClick={async()=>{await OmniStudyAPI.saveSlideText(chapterId,page,text);setText('');await refresh();if (outline) await review();}}>Save verified transcription</button></div>}
  </div>;
}
