import { useEffect, useRef, useState } from 'react';
import type { ChapterSummary, CourseProgress, ScoreAverage } from '../types/assessment';

const labels = {section_quiz:'Section quizzes', mock_test:'Chapter tests', midterm:'Midterms', final:'Finals'} as const;
const modes = Object.keys(labels) as (keyof typeof labels)[];
function Result({s}:{s:ScoreAverage}) {
  const pending = [s.in_progress && `${s.in_progress} in progress`, s.awaiting_grade && `${s.awaiting_grade} awaiting grades`].filter(Boolean).join(' · ');
  if (!s.attempts) return <span className="text-slate-400">{pending || 'Not attempted'}</span>;
  return <><b className={s.mastered ? 'text-emerald-300' : 'text-amber-200'}>{s.mastered ? 'Mastered' : 'Needs practice'} · {s.average_percent}%</b><br/>{s.average_earned} / {s.average_possible} pts avg · {s.attempts} {s.attempts === 1 ? 'attempt' : 'attempts'}{pending && <span className="block text-slate-400">{pending}</span>}</>;
}
export function ProgressPanel({data,course,chapterId}:{data:CourseProgress;course:string;chapterId:number}) {
  return <section aria-label="Course mastery" className="space-y-3 rounded-xl border border-slate-700 bg-slate-900 p-4 text-xs">
    <h3 className="text-base font-bold">{course} · Mastery by assessment</h3>
    <p className="text-slate-300">Each completed attempt counts once. Above 80% is mastered; exactly 80% needs practice. Drafts and papers awaiting grades are excluded.</p>
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">{modes.map(m=><div key={m} className="rounded-lg bg-slate-800 p-2"><strong>{labels[m]}</strong><div className="mt-1"><Result s={data.modes[m]}/></div></div>)}</div>
    {data.chapters.map(c=><details key={c.id} open={c.id===chapterId} className="rounded-lg border border-slate-700 p-2"><summary className="cursor-pointer font-semibold">{c.title} · {c.sections.length} sections</summary>
      <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[650px] text-left"><caption className="pb-2 text-left text-slate-400">Only points from this chapter or section count in its row.</caption><thead><tr><th>Coverage</th>{modes.map(m=><th key={m} className="p-2">{labels[m]}</th>)}</tr></thead><tbody>
        <tr className="border-t border-slate-700"><th className="p-2">Whole chapter</th>{modes.map(m=><td key={m} className="p-2"><Result s={c.modes[m]}/></td>)}</tr>
        {c.sections.map(s=><tr key={s.id} className="border-t border-slate-700"><th scope="row" className="p-2">{s.label}{s.archived?' (archived)':''}<span className="block font-normal text-slate-400">{s.pages}</span><span className="block font-normal"><Result s={s.overall}/></span></th>{modes.map(m=><td key={m} className="p-2"><Result s={s.modes[m]}/></td>)}</tr>)}
      </tbody></table></div></details>)}
  </section>;
}

type Selection = Record<number,string>;
export const courseKey=(name:string)=>name.trim().toLowerCase().replace(/\s+/g,' ');
function numbers(raw:string) {
  const set=new Set<number>();
  for (const part of raw.replace(/\b(?:slides?|pages?)\b/gi,'').trim().split(/[,;]/)) {
    const m=/^\s*(\d+)\s*(?:[-–—]\s*(\d+))?\s*$/.exec(part); if(!m) return null;
    const a=Number(m[1]), b=Number(m[2]??m[1]); if(a<1||a>b||b>10000)return null;
    for(let i=a;i<=b;i++)set.add(i);
  }
  return set;
}
export function ExamScopePicker({mode,active,chapters,initial,onClose,onGenerate}:{mode:'midterm'|'final';active:ChapterSummary;chapters:ChapterSummary[];initial:number[];onClose:()=>void;onGenerate:(pages:Selection)=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const decks=chapters.filter(c=>(c.course_key??courseKey(c.course_name))===(active.course_key??courseKey(active.course_name)));
  const all=decks.flatMap(c=>c.sections), key=`omnistudy-exam-slides:${active.course_key??courseKey(active.course_name)}:${mode}`;
  const [pages,setPages]=useState<Selection>(()=>{
    try{const stored=JSON.parse(localStorage.getItem(key)??'null');if(stored && typeof stored==='object')return Object.fromEntries(all.filter(s=>typeof stored[s.id]==='string').map(s=>[s.id,stored[s.id]]));}catch{/* optional preference */}
    return Object.fromEntries(active.sections.filter(s=>initial.includes(s.id)).map(s=>[s.id,s.slide_pages]));
  });
  useEffect(()=>{const d=dialog.current;d?.showModal();return ()=>d?.close();},[]);
  const n=Object.keys(pages).length;
  const invalid=all.find(s=>{if(!(s.id in pages))return false;const p=numbers(pages[s.id]), allowed=numbers(s.slide_pages);return !p||!allowed||[...p].some(i=>!allowed.has(i));});
  const error=!n?'Select at least one section.':n>29?'Select at most 29 sections for this 29-question exam.':invalid?`Choose pages within ${invalid.section_code} (${invalid.slide_pages}).`:'';
  const toggle=(ids:number[],checked:boolean)=>setPages(prev=>{const next={...prev};all.filter(s=>ids.includes(s.id)).forEach(s=>{if(checked)next[s.id]=prev[s.id]??s.slide_pages;else delete next[s.id]});return next});
  return <dialog ref={dialog} onCancel={onClose} aria-labelledby="scope-title" className="max-h-[80vh] w-full max-w-xl space-y-4 overflow-auto rounded-xl border border-slate-600 bg-slate-900 p-5 text-slate-100 backdrop:bg-black/70">
    <h2 id="scope-title" className="text-lg font-bold">Choose {mode} slides · {active.course_name}</h2><p className="text-sm text-slate-300">Select uploaded decks or individual sections. To narrow a section, enter slide numbers such as 8–10, 12. Your note selections stay as they are.</p>
    {decks.map(c=><fieldset key={c.id} className="space-y-2 rounded-lg border border-slate-700 p-3"><legend><label><input type="checkbox" checked={!!c.sections.length&&c.sections.every(s=>s.id in pages)} onChange={e=>toggle(c.sections.map(s=>s.id),e.target.checked)}/> {c.chapter_title} · all sections</label></legend>
      {c.sections.map(s=><div key={s.id} className="flex flex-wrap items-center justify-between gap-2 text-sm"><label><input type="checkbox" checked={s.id in pages} onChange={e=>toggle([s.id],e.target.checked)}/> {s.section_code} · {s.section_title} <span className="text-slate-400">({s.slide_pages})</span></label>{s.id in pages&&<input aria-label={`Pages for ${c.chapter_title} ${s.section_code}`} className="w-32 rounded bg-slate-800 px-2 py-1" value={pages[s.id]} onChange={e=>setPages({...pages,[s.id]:e.target.value})}/>}</div>)}
    </fieldset>)}<div aria-live="polite" className="text-sm">{error||`${n} section${n===1?'':'s'} selected · 29 questions · 100 points`}</div><div className="flex justify-end gap-4"><button onClick={onClose}>Cancel</button><button disabled={!!error} className="rounded bg-emerald-600 px-3 py-2 disabled:opacity-40" onClick={()=>{try{localStorage.setItem(key,JSON.stringify(pages))}catch{/* optional preference */}onGenerate(pages)}}>Generate {mode}</button></div>
  </dialog>;
}
