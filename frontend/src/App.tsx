import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {
  BookOpen,
  FileUp,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Download,
  History,
  Columns,
  Play,
  Award,
  Layers,
  PlusCircle,
  Settings,
  Trash2,
  Eraser,
} from 'lucide-react';
import {
  ActiveExamSession,
  ChapterSummary,
  WrongQuestionItem,
} from './types/assessment';
import { BACKEND_URL, OmniStudyAPI, requestError } from './services/api';
import { SectionTools, WorkspaceTools } from './components/layout/StudyTools';
import { ExamHeaderTimer } from './components/exam/ExamHeaderTimer';
import { useChoiceReviews } from './components/exam/ChoiceReviews';
import { McqFiveOptionCard } from './components/exam/McqFiveOptionCard';
import { PasteSolutionBox } from './components/exam/PasteSolutionBox';
import { WrongQuestionCard } from './components/wrong-bank/WrongQuestionCard';
import { HandsFreeVoiceOrb } from './components/voice/HandsFreeVoiceOrb';
import { SettingsModal } from './components/layout/SettingsModal';

// Progress timers and exam autosaves must not typeset unchanged notes again.
const NoteMarkdown = React.memo(function NoteMarkdown({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}>{text}</ReactMarkdown>;
});

export function App() {
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [activeChapter, setActiveChapter] = useState<ChapterSummary | null>(null);
  const [selectedSectionIds, setSelectedSectionIds] = useState<number[]>([]);
  const [activeTab, setActiveTab] = useState<'study' | 'exam' | 'wrong_bank' | 'history'>('study');
  const [showSplitSlide, setShowSplitSlide] = useState(true);
  const [showOnboardModal, setShowOnboardModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  // Onboarding form state
  const [courseName, setCourseName] = useState('');
  const [chapterTitle, setChapterTitle] = useState('');
  const [slideFile, setSlideFile] = useState<File | null>(null);
  const [textbookFile, setTextbookFile] = useState<File | null>(null);
  const [testbankFile, setTestbankFile] = useState<File | null>(null);
  const [onboarding, setOnboarding] = useState(false);
  const [importError, setImportError] = useState('');
  const [documentNotice, setDocumentNotice] = useState<{ chapterId: number; message: string; warnings: string[] } | null>(null);
  const [attachingTestbank, setAttachingTestbank] = useState(false);
  const chapterRequest = useRef(0);

  // Note Regeneration & Cleaning state
  const [regeneratingNotes, setRegeneratingNotes] = useState(false);
  const [regenSeconds, setRegenSeconds] = useState(0);
  const [regenModeLabel, setRegenModeLabel] = useState<'selected' | 'all' | null>(null);
  const [cleaningNotes, setCleaningNotes] = useState(false);

  // Exam state
  const [examMode, setExamMode] = useState<'section_quiz' | 'mock_test' | 'midterm' | 'final'>('section_quiz');
  const [generatingExam, setGeneratingExam] = useState(false);
  const [genSeconds, setGenSeconds] = useState(0);
  const [activeExam, setActiveExam] = useState<ActiveExamSession | null>(null);
  const [mcqSelections, setMcqSelections] = useState<Record<number, string[]>>({});
  const [writtenAnswers, setWrittenAnswers] = useState<Record<number, string>>({});
  const [imagePaths, setImagePaths] = useState<Record<number, string>>({});
  const [timeSpentSeconds, setTimeSpentSeconds] = useState(0);
  const [draftState, setDraftState] = useState('');
  const [isExamSubmitted, setIsExamSubmitted] = useState(false);
  const [submittingExam, setSubmittingExam] = useState(false);
  const submittingRef = useRef(false);

  const lockedPaper = (status?: string) => ['completed','submitted_grading','submitted_retry'].includes(status || '');
  const choiceReviews = useChoiceReviews(activeExam, activeTab === 'exam' && isExamSubmitted);
  const [pollFailed, setPollFailed] = useState(false);
  useEffect(() => {
    if (activeExam?.status !== 'submitted_grading') return;
    let canceled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await OmniStudyAPI.getAssessment(activeExam.session_id);
        if (canceled) return;
        setPollFailed(false);
        if (result.status !== 'submitted_grading') {
          setActiveExam(result);
          if (result.status === 'completed') void refreshChapters(result.chapter_id, selectedSectionIds).catch(() => {});
          return;
        }
      } catch { if (!canceled) setPollFailed(true); }
      if (!canceled) timer = setTimeout(poll, 2500);
    };
    timer = setTimeout(poll, 1000);
    return () => { canceled = true; clearTimeout(timer); };
  }, [activeExam?.session_id, activeExam?.status]);

  const [wrongError, setWrongError] = useState('');
  const [dueOnly, setDueOnly] = useState(false);
  // Wrong Question Bank state
  const [wrongItems, setWrongItems] = useState<WrongQuestionItem[]>([]);
  const [wrongFilter, setWrongFilter] = useState<'active' | 'graduated'>('active');

  // Health status
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        setShowSettingsModal((s) => !s);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!regeneratingNotes) {
      setRegenSeconds(0);
      return;
    }
    const iv = setInterval(() => setRegenSeconds((s) => s + 1), 1000);
    return () => clearInterval(iv);
  }, [regeneratingNotes]);

  useEffect(() => {
    if (!generatingExam) {
      setGenSeconds(0);
      return;
    }
    const iv = setInterval(() => setGenSeconds((s) => s + 1), 1000);
    return () => clearInterval(iv);
  }, [generatingExam]);

  const refreshChapters = async (selectId?: number, preserveSelection?: number[]) => {
    const request = ++chapterRequest.current;
    const list = await OmniStudyAPI.listChapters();
    if (request !== chapterRequest.current) return;
    setChapters(list);
    if (list.length === 0) {
      setActiveChapter(null);
      setSelectedSectionIds([]);
      setShowOnboardModal(true);
      return;
    }
    const targetId = selectId ?? activeChapter?.id ?? list[0].id;
    const exists = list.some((c) => c.id === targetId) ? targetId : list[0].id;
    const detail = await OmniStudyAPI.getChapterDetail(exists);
    if (request !== chapterRequest.current) return;
    setActiveChapter(detail);
    const availableIds = detail.sections.map((section) => section.id);
    setSelectedSectionIds(preserveSelection !== undefined && exists === targetId
      ? preserveSelection.filter((id) => availableIds.includes(id))
      : availableIds);
  };

  useEffect(() => {
    OmniStudyAPI.getHealth().then(setHealth).catch(() => {});
    refreshChapters().catch(() => {});
  }, []);

  useEffect(() => {
    setWrongItems([]);
    setWrongError('');
    if (!activeChapter) return;
    let canceled = false;
    OmniStudyAPI.listWrongQuestions(activeChapter.id, wrongFilter).then((items) => {
      if (!canceled) setWrongItems(items);
    }).catch(() => {
      if (!canceled) setWrongError('Could not load mistakes. Please retry.');
    });
    return () => { canceled = true; };
  }, [wrongFilter, activeChapter]);

  useEffect(() => {
    const id = activeChapter?.id;
    if (!id) return;
    let canceled = false;
    OmniStudyAPI.getActiveAssessment(id).then(exam => {
      if (canceled) return;
      setActiveExam(exam); setIsExamSubmitted(lockedPaper(exam?.status));
      const selections: Record<number,string[]> = {}, written: Record<number,string> = {};
      exam?.draft_answers?.forEach(a => { if (Array.isArray(a.user_answer)) selections[a.question_id]=a.user_answer; else written[a.question_id]=a.user_answer || ''; });
      if (exam) {
        try {
          const cached = JSON.parse(localStorage.getItem(`omnistudy-draft-${exam.session_id}`) || 'null');
          if (cached && (!exam.deadline_at || exam.is_paused || Date.now() < new Date(exam.deadline_at).getTime())) {
            Object.assign(selections, cached.mcq || {}); Object.assign(written, cached.written || {});
          }
        } catch { /* Ignore corrupted optional recovery cache. */ }
      }
      setMcqSelections(selections); setWrittenAnswers(written); setImagePaths({});
      setDraftState(exam ? 'Recovered saved assessment. Open Exam to resume.' : '');
    });
    return () => { canceled = true; };
  }, [activeChapter?.id]);

  const payloadRef = useRef<{question_id:number;user_answer:string|string[];handwritten_image_path?:string}[]>([]);
  payloadRef.current = activeExam?.questions.map(q => ({ question_id:q.id, user_answer:q.question_type.startsWith('mcq') ? mcqSelections[q.id] || [] : writtenAnswers[q.id] || '', handwritten_image_path:imagePaths[q.id] })) || [];
  useEffect(() => {
    if (!activeExam || isExamSubmitted || activeExam.status === 'grading') return;
    if (!activeExam.is_paused && activeExam.deadline_at && Date.now() >= new Date(activeExam.deadline_at).getTime()) return;
    localStorage.setItem(`omnistudy-draft-${activeExam.session_id}`, JSON.stringify({ mcq: mcqSelections, written: writtenAnswers }));
    const timer = setTimeout(() => {
      OmniStudyAPI.saveDraft(activeExam.session_id,payloadRef.current,timeSpentSeconds).then(()=>setDraftState('Answers saved')).catch(()=>setDraftState('Autosave unavailable or writing time ended. Last saved draft is preserved.'));
    }, 650);
    return () => clearTimeout(timer);
  }, [activeExam?.session_id, mcqSelections, writtenAnswers, imagePaths, isExamSubmitted]);

  const handleDeleteChapter = async (
    e: React.MouseEvent,
    chapterId: number,
    title: string
  ) => {
    e.stopPropagation();
    if (!window.confirm(`Remove studied chapter "${title}" and all its history?`)) {
      return;
    }
    await OmniStudyAPI.deleteChapter(chapterId);
    const remaining = chapters.filter((c) => c.id !== chapterId);
    if (remaining.length === 0) {
      ++chapterRequest.current;
      setChapters([]);
      setActiveChapter(null);
      setSelectedSectionIds([]);
      setShowOnboardModal(true);
    } else {
      await refreshChapters(remaining[0].id);
    }
  };

  const generateNotes = async (chapterId: number, ids: number[]) => {
    const result = await OmniStudyAPI.regenerateChapterNotes(chapterId, ids);
    const guides = result.source_guide_section_ids?.length || 0;
    const kept = result.kept_section_ids?.length || 0;
    if (guides || kept) {
      setDocumentNotice({ chapterId, message: 'Some AI lessons reached the time limit.', warnings: [
        ...(guides ? [`${guides} section(s) received a reading guide with source excerpts.`] : []),
        ...(kept ? [`${kept} section(s) kept their existing notes.`] : []),
        'You can regenerate an individual section for a new AI lesson.',
      ] });
    } else {
      setDocumentNotice(null);
    }
  };

  const handleCleanNoteSpace = async () => {
    if (!activeChapter) return;
    const targetCount = selectedSectionIds.length;
    if (targetCount === 0) {
      return;
    }
    if (!window.confirm(`Delete saved notes for ${targetCount} selected sections? You can restore them from note history.`)) return;
    setCleaningNotes(true);
    try {
      await OmniStudyAPI.clearChapterNotes(activeChapter.id, selectedSectionIds);
      await refreshChapters(activeChapter.id, selectedSectionIds);
    } finally {
      setCleaningNotes(false);
    }
  };

  const handleOnboardSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!slideFile || onboarding) return;
    if (!courseName.trim() || !chapterTitle.trim()) {
      setImportError('Enter both the course name and chapter title.');
      return;
    }
    setImportError('');
    setOnboarding(true);
    try {
      const created = await OmniStudyAPI.onboardChapter(
        courseName.trim(), chapterTitle.trim(), slideFile, textbookFile, testbankFile
      );
      setShowOnboardModal(false);
      setCourseName('');
      setChapterTitle('');
      setSlideFile(null);
      setTextbookFile(null);
      setTestbankFile(null);
      setDocumentNotice({
        chapterId: created.chapter_id,
        message: `Imported ${created.total_slides_parsed} source page(s). Select sections to generate notes when you’re ready.`,
        warnings: created.warnings ?? [],
      });
      setActiveTab('study');
      try {
        await refreshChapters(created.chapter_id);
      } catch {
        window.dispatchEvent(new CustomEvent('omnistudy-error', { detail: 'The chapter was saved. Reload the workspace to open it if it does not appear.' }));
      }
    } catch (error) {
      setImportError(requestError(error, 'Could not import the chapter. Try again.'));
    } finally {
      setOnboarding(false);
    }
  };

  const handleStartAssessment = async () => {
    if (!activeChapter || selectedSectionIds.length === 0) return;
    if (activeExam && !isExamSubmitted && !window.confirm('Start a new paper? Your existing assessment remains saved and can be resumed from History.')) return;
    setGeneratingExam(true);
    try {
      const session = await OmniStudyAPI.generateAssessment(
        activeChapter.id,
        examMode,
        selectedSectionIds
      );
      setActiveExam(session);
      setMcqSelections({});
      setWrittenAnswers({});
      setImagePaths({});
      setTimeSpentSeconds(0);
      setIsExamSubmitted(false);
      setActiveTab('exam');
    } finally {
      setGeneratingExam(false);
    }
  };

  const handleToggleMcqOption = (
    qId: number,
    qType: string,
    letter: 'A' | 'B' | 'C' | 'D' | 'E'
  ) => {
    setMcqSelections((prev) => {
      const cur = prev[qId] || [];
      if (qType === 'mcq_single') {
        return { ...prev, [qId]: [letter] };
      }
      return {
        ...prev,
        [qId]: cur.includes(letter) ? cur.filter((x) => x !== letter) : [...cur, letter],
      };
    });
  };

  const handleSubmitExam = async () => {
    if (!activeExam || (isExamSubmitted && activeExam.status !== 'submitted_retry') || submittingRef.current) return;
    submittingRef.current = true;
    setSubmittingExam(true);
    try {
      const answersPayload = activeExam.questions.map((q) => ({
        question_id: q.id,
        user_answer:
          q.question_type === 'mcq_single' || q.question_type === 'mcq_multi'
            ? mcqSelections[q.id] || []
            : writtenAnswers[q.id] || '',
        handwritten_image_path: imagePaths[q.id],
      }));

      const result = await OmniStudyAPI.finishAssessment(activeExam.session_id, timeSpentSeconds, answersPayload);
      setActiveExam(result);
      setIsExamSubmitted(true);
      setPollFailed(false);
      setDraftState('');
      localStorage.removeItem(`omnistudy-draft-${activeExam.session_id}`);
      await refreshChapters(activeChapter?.id, selectedSectionIds);
    } finally {
      setSubmittingExam(false);
      submittingRef.current = false;
    }
  };

  const toggleSectionCheckbox = (secId: number) => {
    setSelectedSectionIds((prev) =>
      prev.includes(secId) ? prev.filter((id) => id !== secId) : [...prev, secId]
    );
  };

  const slidePdfUrl =
    activeChapter?.slide_file_path?.endsWith('.pdf')
      ? `${BACKEND_URL}${activeChapter.slide_file_path}`
      : null;

  const visibleStudySections =
    activeChapter?.sections.filter((s) => selectedSectionIds.includes(s.id)) || [];

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      {/* LEFT SIDEBAR */}
      <aside className="flex w-76 shrink-0 flex-col border-r border-slate-800 bg-slate-900/60">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3.5">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-400" />
            <span className="font-bold tracking-tight text-white">OmniStudy AI</span>
          </div>
          <button
            onClick={() => { setImportError(''); setShowOnboardModal(true); }}
            className="flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-500 transition"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            New Chapter
          </button>
        </div>

        {/* Settings Modal Trigger */}
        <button
          type="button"
          onClick={() => setShowSettingsModal(true)}
          className="border-b border-slate-800/80 bg-slate-950/60 px-4 py-2 text-[11px] text-slate-300 flex items-center justify-between hover:bg-slate-800/70 transition text-left"
          title="Open AI & Token Settings (Cmd + ,)"
        >
          <span className="flex items-center gap-1.5">
            <Settings className="h-3.5 w-3.5 text-indigo-400" />
            <span>AI Engine (Cmd+,):</span>
          </span>
          <span className="font-mono text-emerald-400">
            {health?.active_provider_mode === 'openai'
              ? 'OpenAI (terra-6.1)'
              : health?.active_provider_mode === 'ollama'
              ? 'Local Ollama'
              : health?.um_genai_connected && health?.active_provider_mode !== 'deepseek'
              ? 'UM GenAI (Free)'
              : 'DeepSeek Direct'}
          </span>
        </button>

        {/* Chapters List with Trash Delete Button */}
        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          <div>
            <div className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Studied Chapters ({chapters.length})
            </div>
            <div className="space-y-1.5">
              {chapters.map((ch) => (
                <div
                  key={ch.id}
                  onClick={() => refreshChapters(ch.id)}
                  className={`group relative cursor-pointer w-full rounded-lg p-2.5 text-left transition ${
                    activeChapter?.id === ch.id
                      ? 'bg-indigo-600/20 border border-indigo-500/40 text-white'
                      : 'hover:bg-slate-800/60 border border-transparent text-slate-300'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] font-medium text-indigo-400 truncate">
                        {ch.course_name}
                      </div>
                      <div className="truncate text-xs font-semibold">{ch.chapter_title}</div>
                    </div>

                    <button
                      type="button"
                      onClick={(e) => handleDeleteChapter(e, ch.id, ch.chapter_title)}
                      title="Delete this chapter"
                      className="flex items-center justify-center rounded-md border border-rose-500/30 bg-rose-500/10 p-1.5 text-rose-400 hover:bg-rose-600 hover:text-white transition shrink-0"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                    <span>Mastery (&ge;80% Gate)</span>
                    <span className="font-bold text-emerald-400">{ch.progress_percentage}%</span>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full bg-emerald-500 transition-all"
                      style={{ width: `${Math.min(100, ch.progress_percentage)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Slide-Scoped Sections with All / None Toggles */}
          {activeChapter && (
            <div>
              <div className="flex items-center justify-between px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                <span>
                  Ticked Sections ({selectedSectionIds.length}/{activeChapter.sections.length})
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setSelectedSectionIds(activeChapter.sections.map((s) => s.id))}
                    className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-indigo-300 hover:bg-slate-700"
                    title="Select all sections"
                  >
                    All
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedSectionIds([])}
                    className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-rose-300 hover:bg-slate-700"
                    title="Untick all sections to clear workspace"
                  >
                    None
                  </button>
                </div>
              </div>
              <div className="space-y-1.5">
                {activeChapter.sections.map((sec) => {
                  const checked = selectedSectionIds.includes(sec.id);
                  return (
                    <div
                      key={sec.id}
                      onClick={() => toggleSectionCheckbox(sec.id)}
                      className={`cursor-pointer rounded-lg border p-2.5 text-xs transition ${
                        checked
                          ? 'border-indigo-500/50 bg-indigo-950/30 text-slate-100'
                          : 'border-slate-800/60 bg-slate-950/40 text-slate-500'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => {}}
                            className="rounded border-slate-600 text-indigo-600"
                          />
                          <span className="font-bold text-indigo-300">{sec.section_code}</span>
                        </div>
                        {sec.is_mastered ? (
                          <span className="flex items-center gap-1 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-bold text-emerald-300">
                            <CheckCircle2 className="h-3 w-3" />
                            {(sec.best_accuracy * 100).toFixed(0)}%
                          </span>
                        ) : (
                          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                            {(sec.best_accuracy * 100).toFixed(0)}% / 80%
                          </span>
                        )}
                      </div>
                      <div className="mt-1 pl-5 text-slate-300 line-clamp-1">{sec.section_title}</div>
                      <div className="pl-5 text-[10px] text-slate-400">{sec.slide_pages}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* MAIN WORKSPACE */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-900/80 px-5 py-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTab('study')}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === 'study'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              <BookOpen className="h-3.5 w-3.5" />
              Slide Study Notes
            </button>

            <button
              onClick={() => setActiveTab('exam')}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === 'exam'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              <Award className="h-3.5 w-3.5" />
              Timed Exam & Quiz Canvas
            </button>

            <button
              onClick={() => setActiveTab('wrong_bank')}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === 'wrong_bank'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
              Wrong Question Bank
              <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                {wrongItems.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTab('history')}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === 'history'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              <History className="h-3.5 w-3.5" />
              Study History
            </button>
          </div>

          {activeChapter && (
            <div className="flex items-center gap-2">
              <select
                value={examMode}
                onChange={(e) => setExamMode(e.target.value as any)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-100"
              >
                <option value="section_quiz">Section Quiz (20m • 25 pts)</option>
                <option value="mock_test">Chapter Mock Test (60m • 50 pts)</option>
                <option value="midterm">Midterm Exam (120m • 100 pts)</option>
                <option value="final">Final Exam (120m • 100 pts)</option>
              </select>

              <button
                onClick={handleStartAssessment}
                disabled={generatingExam || selectedSectionIds.length === 0}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 transition"
              >
                <Play className="h-3.5 w-3.5" />
                {generatingExam
                  ? `Parallel Generating (${genSeconds}s)...`
                  : `Generate Quiz/Exam (${selectedSectionIds.length} Sec)`}
              </button>

              <button
                onClick={() => setShowSplitSlide((s) => !s)}
                className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
              >
                <Columns className="h-3.5 w-3.5" />
                Split View
              </button>

              {/* Top Bar Exports strictly export ONLY the currently ticked sections */}
              <a
                href={OmniStudyAPI.getExportUrl(
                  'chapter',
                  activeChapter.id,
                  'pdf',
                  true,
                  selectedSectionIds
                )}
                target="_blank"
                rel="noreferrer"
                className={`flex items-center gap-1 rounded-lg bg-rose-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 transition ${
                  selectedSectionIds.length === 0 ? 'pointer-events-none opacity-40' : ''
                }`}
                title="Download PDF of Selected Sections Only"
              >
                <Download className="h-3.5 w-3.5" />
                Selected .PDF ({selectedSectionIds.length})
              </a>
              <a
                href={OmniStudyAPI.getExportUrl(
                  'chapter',
                  activeChapter.id,
                  'md',
                  true,
                  selectedSectionIds
                )}
                target="_blank"
                rel="noreferrer"
                className={`flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700 ${
                  selectedSectionIds.length === 0 ? 'pointer-events-none opacity-40' : ''
                }`}
                title="Download Markdown of Selected Sections Only"
              >
                <Download className="h-3.5 w-3.5 text-indigo-400" />
                .MD
              </a>
              <a
                href={OmniStudyAPI.getExportUrl(
                  'chapter',
                  activeChapter.id,
                  'tex',
                  true,
                  selectedSectionIds
                )}
                target="_blank"
                rel="noreferrer"
                className={`flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700 ${
                  selectedSectionIds.length === 0 ? 'pointer-events-none opacity-40' : ''
                }`}
                title="Download LaTeX of Selected Sections Only"
              >
                <Download className="h-3.5 w-3.5 text-emerald-400" />
                .TEX
              </a>
            </div>
          )}
        </header>

        {/* SPLIT-SCREEN WORKSPACE */}
        <div className="flex flex-1 overflow-hidden">
          {showSplitSlide && activeChapter && (
            <div className="w-5/12 border-r border-slate-800 bg-slate-950 flex flex-col">
              <div className="border-b border-slate-800 bg-slate-900/50 px-4 py-2 text-xs font-medium text-slate-300 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Layers className="h-3.5 w-3.5 text-indigo-400" />
                  Priority Scope: {activeChapter.chapter_title}
                </span>
                <span className="text-[11px] text-slate-400">
                  Selected: {selectedSectionIds.length}/{activeChapter.sections.length} sections
                </span>
              </div>
              {slidePdfUrl ? (
                <iframe
                  src={slidePdfUrl}
                  title="Lecture Slides PDF"
                  className="h-full w-full flex-1 border-0"
                />
              ) : (
                <div className="flex-1 overflow-y-auto p-5 space-y-4">
                  <div className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 p-3 text-xs text-indigo-200">
                    Click any section in the left sidebar to tick/untick it.
                  </div>
                  {visibleStudySections.map((sec) => (
                    <div
                      key={sec.id}
                      className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-indigo-400">
                          {sec.section_code}: {sec.section_title}
                        </span>
                        <span className="text-[11px] text-slate-400">{sec.slide_pages}</span>
                      </div>
                      <div className="study-markdown prose prose-invert max-w-none text-xs text-slate-300">
                        <NoteMarkdown text={sec.extracted_study_notes || '_Note space is clean. Click Generate Ticked Sections to write notes._'} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* RIGHT PANE */}
          <main className="flex-1 overflow-y-auto p-6">
            {!activeChapter ? (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <BookOpen className="h-12 w-12 text-indigo-400 mb-3" />
                <h2 className="text-lg font-bold">Welcome to OmniStudy AI</h2>
                <p className="mt-1 max-w-md text-xs text-slate-400">
                  Start by selecting the chapter you want to study and uploading your lecture slides.
                </p>
                <button
                  onClick={() => setShowOnboardModal(true)}
                  className="mt-4 rounded-xl bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white hover:bg-indigo-500"
                >
                  Choose First Chapter & Upload Slides
                </button>
              </div>
            ) : activeTab === 'study' ? (
              <div className="mx-auto max-w-4xl space-y-6">
                <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
                  <div>
                    <div className="flex items-center gap-2">
                      <h1 className="text-xl font-bold text-white">
                        {activeChapter.course_name} — {activeChapter.chapter_title}
                      </h1>
                      {activeChapter.testbank_file_path && (
                        <span className="rounded-md bg-purple-500/20 border border-purple-500/40 px-2.5 py-0.5 text-[11px] font-semibold text-purple-300">
                          Testbank Attached
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                      Showing <strong className="text-emerald-400">{selectedSectionIds.length}</strong> of{' '}
                      {activeChapter.sections.length} section(s). Generating or downloading applies{' '}
                      <strong className="text-white">strictly to your ticked sections</strong>.
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {/* Button 1: Generate & Overwrite Notes ONLY for Ticked Sections */}
                    <button
                      type="button"
                      disabled={regeneratingNotes || selectedSectionIds.length === 0}
                      onClick={async () => {
                        const keepSelected = [...selectedSectionIds];
                        setRegeneratingNotes(true);
                        setRegenModeLabel('selected');
                        try {
                          await generateNotes(activeChapter.id, keepSelected);
                          await refreshChapters(activeChapter.id, keepSelected);
                        } finally {
                          setRegeneratingNotes(false);
                          setRegenModeLabel(null);
                        }
                      }}
                      className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-50 transition"
                      title="Generate & overwrite structured LaTeX notes ONLY for the ticked (✓) sections"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      {regeneratingNotes && regenModeLabel === 'selected'
                        ? `Generating Selected (${regenSeconds}s)...`
                        : `Generate Ticked Sections (${selectedSectionIds.length})`}
                    </button>

                    {/* Button 2: Select All & Generate All Sections in Parallel */}
                    <button
                      type="button"
                      disabled={regeneratingNotes}
                      onClick={async () => {
                        const allIds = activeChapter.sections.map((s) => s.id);
                        setSelectedSectionIds(allIds);
                        setRegeneratingNotes(true);
                        setRegenModeLabel('all');
                        try {
                          await generateNotes(activeChapter.id, allIds);
                          await refreshChapters(activeChapter.id, allIds);
                        } finally {
                          setRegeneratingNotes(false);
                          setRegenModeLabel(null);
                        }
                      }}
                      className="flex items-center gap-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/15 px-3 py-1.5 text-xs font-semibold text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-50 transition"
                      title="Select all sections and generate all study notes in parallel"
                    >
                      <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
                      {regeneratingNotes && regenModeLabel === 'all'
                        ? `Generating All (${regenSeconds}s)...`
                        : `Select All & Generate All (${activeChapter.sections.length})`}
                    </button>

                    {/* Button 3: Clean Note Space (Clears the existing note text of ticked sections) */}
                    <button
                      type="button"
                      disabled={cleaningNotes || regeneratingNotes || selectedSectionIds.length === 0}
                      onClick={handleCleanNoteSpace}
                      className="flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50 transition"
                      title="Clean / wipe the existing note text for the ticked sections"
                    >
                      <Eraser className="h-3.5 w-3.5 text-amber-400" />
                      {cleaningNotes
                        ? 'Cleaning...'
                        : `Delete Saved Notes (${selectedSectionIds.length})`}
                    </button>

                    <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-purple-500/40 bg-purple-500/15 px-3 py-1.5 text-xs font-semibold text-purple-200 hover:bg-purple-500/25 transition">
                      <FileUp className="h-3.5 w-3.5 text-purple-300" />
                      <span>
                        {attachingTestbank ? 'Attaching…' : activeChapter.testbank_file_path
                          ? 'Update Testbank' : '+ Attach Testbank'}
                      </span>
                      <input
                        type="file"
                        accept=".pdf,.pptx,.md,.txt"
                        disabled={attachingTestbank}
                        className="hidden"
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          e.currentTarget.value = '';
                          if (!f || attachingTestbank) return;
                          setAttachingTestbank(true);
                          try {
                            const saved = await OmniStudyAPI.uploadChapterTestbank(activeChapter.id, f);
                            setDocumentNotice({ chapterId: activeChapter.id, message: 'Testbank saved.', warnings: saved.warnings ?? [] });
                            await refreshChapters(activeChapter.id, selectedSectionIds);
                          } catch { /* The request error banner shows what to fix. */ }
                          finally { setAttachingTestbank(false); }
                        }}
                      />
                    </label>

                    {/* Button 4: Download PDF for Selected Sections ONLY */}
                    <a
                      href={OmniStudyAPI.getExportUrl(
                        'chapter',
                        activeChapter.id,
                        'pdf',
                        true,
                        selectedSectionIds
                      )}
                      target="_blank"
                      rel="noreferrer"
                      className={`flex items-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 transition ${
                        selectedSectionIds.length === 0 ? 'pointer-events-none opacity-40' : ''
                      }`}
                      title="Download PDF containing ONLY the currently ticked sections"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download Selected ({selectedSectionIds.length}) .PDF
                    </a>
                  </div>
                </div>

                {/* ONLY render the sections that the user has ticked! */}
                {documentNotice?.chapterId === activeChapter.id && (
                  <div role="status" className="mb-3 rounded-xl border border-indigo-500/40 bg-indigo-950/60 px-4 py-3 text-sm text-indigo-100">
                    <button type="button" className="float-right ml-4 underline" onClick={() => setDocumentNotice(null)}>Dismiss</button>
                    <p>{documentNotice.message}</p>
                    {documentNotice.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-200">{warning}</p>)}
                  </div>
                )}
                <WorkspaceTools key={activeChapter.id} chapterId={activeChapter.id} refresh={() => refreshChapters(activeChapter.id, selectedSectionIds)} refreshScope={() => refreshChapters(activeChapter.id)} />
                {!!activeChapter.archived_sections?.length && (
                  <details className="mb-3 rounded-xl border border-slate-800 bg-slate-900/70 p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-indigo-200">Previously generated notes ({activeChapter.archived_sections.length})</summary>
                    <p className="mt-2 text-xs text-slate-400">These notes use the earlier slide ranges. They are kept for reference and are separate from the reviewed sections.</p>
                    {activeChapter.archived_sections.map(sec => (
                      <details key={sec.id} className="mt-3 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                        <summary className="cursor-pointer text-sm font-semibold text-slate-200">{sec.section_code} · {sec.slide_pages}</summary>
                        <div className="mt-3 space-y-3">
                          <SectionTools chapterId={activeChapter.id} section={sec} refresh={() => refreshChapters(activeChapter.id, selectedSectionIds)} />
                          {sec.extracted_study_notes && <a className="text-xs text-indigo-200 underline" href={OmniStudyAPI.getExportUrl('chapter', activeChapter.id, 'pdf', true, [sec.id])}>Download previous note PDF</a>}
                          <div className="study-markdown prose prose-invert max-w-none text-sm leading-relaxed">
                            <NoteMarkdown text={sec.extracted_study_notes || '_No current note saved for this earlier section._'} />
                          </div>
                        </div>
                      </details>
                    ))}
                  </details>
                )}
                {visibleStudySections.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/30 p-12 text-center space-y-3">
                    <Eraser className="mx-auto h-8 w-8 text-slate-500" />
                    <div className="text-sm font-bold text-slate-300">
                      Note Space is Clean (No Sections Ticked)
                    </div>
                    <p className="text-xs text-slate-400 max-w-md mx-auto">
                      Tick (<strong className="text-indigo-400">✓</strong>) the section(s) you want to study in the left sidebar, then click{' '}
                      <strong className="text-emerald-300">Generate Ticked Sections</strong>.
                    </p>
                  </div>
                ) : (
                  visibleStudySections.map((sec) => (
                    <div
                      key={sec.id}
                      className="rounded-2xl border border-slate-800 bg-slate-900/70 p-6 space-y-3"
                    >
                      <SectionTools chapterId={activeChapter.id} section={sec} refresh={() => refreshChapters(activeChapter.id, selectedSectionIds)} />
                      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                        <label className="flex cursor-pointer items-start gap-3">
                          <input
                            type="checkbox"
                            checked={true}
                            onChange={() => toggleSectionCheckbox(sec.id)}
                            title="Untick to hide this section from workspace & PDF export"
                            className="mt-1 h-4 w-4 rounded border-slate-600 text-indigo-600"
                          />
                          <div>
                            <span className="text-xs font-bold uppercase text-indigo-400">
                              {sec.section_code} • {sec.slide_pages}
                            </span>
                            <h2 className="text-base font-bold text-white">{sec.section_title}</h2>
                          </div>
                        </label>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            disabled={regeneratingNotes}
                            onClick={async () => {
                              const keep = [...selectedSectionIds];
                              setRegeneratingNotes(true);
                              setRegenModeLabel('selected');
                              try {
                                await generateNotes(activeChapter.id, [sec.id]);
                                await refreshChapters(activeChapter.id, keep);
                              } finally {
                                setRegeneratingNotes(false);
                                setRegenModeLabel(null);
                              }
                            }}
                            className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-[11px] font-semibold text-indigo-300 hover:bg-indigo-500/20"
                          >
                            Regenerate This Section
                          </button>
                          <span
                            className={`rounded-lg px-3 py-1 text-xs font-bold ${
                              sec.is_mastered
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                                : 'bg-slate-800 text-slate-300'
                            }`}
                          >
                            Best Quiz: {(sec.best_accuracy * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                      <div className="study-markdown prose prose-invert max-w-none text-sm leading-relaxed">
                        {sec.extracted_study_notes ? (
                          <NoteMarkdown text={sec.extracted_study_notes} />
                        ) : (
                          <div className="rounded-xl border border-dashed border-slate-800 bg-slate-950/50 p-6 text-center text-xs text-slate-400">
                            Note space cleaned for <strong>{sec.section_code}</strong>. Click{' '}
                            <strong className="text-emerald-300">Generate Ticked Sections</strong> or{' '}
                            <strong className="text-indigo-300">Regenerate This Section</strong> to write fresh structured notes.
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : activeTab === 'exam' ? (
              <div className="mx-auto max-w-4xl space-y-6">
                {!activeExam ? (
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-10 text-center space-y-3">
                    <Award className="mx-auto h-10 w-10 text-indigo-400" />
                    <h3 className="text-base font-bold">No Active Quiz or Exam Session</h3>
                    <p className="text-xs text-slate-400 max-w-md mx-auto">
                      Check the slide sections you want to test in the left sidebar, pick a mode in the top bar, and click Generate.
                    </p>
                  </div>
                ) : (
                  <>
                    {isExamSubmitted ? <section aria-label="Scoreboard" className="rounded-xl border border-indigo-500/50 bg-slate-900 p-5 space-y-2">
                      <h2 className="text-lg font-bold">Scoreboard</h2>
                      <div className="text-2xl font-bold text-emerald-300">{activeExam.total_score} / {activeExam.max_score} pts</div>
                      <p role="status" className="text-sm text-slate-300">{activeExam.status === 'completed' ? 'Final score' : activeExam.status === 'submitted_retry' ? 'Points earned so far. Written grading was interrupted; your submission is saved.' : 'Points earned so far. Submitted written work is being graded.'}</p>
                      {activeExam.status === 'submitted_grading' && pollFailed && <p>Reconnecting to your saved result…</p>}
                      {activeExam.status === 'submitted_retry' && <button disabled={submittingExam} onClick={handleSubmitExam} className="underline text-indigo-300">Retry written grading</button>}
                      {choiceReviews.failed ? <p className="text-sm">Some choice explanations are unavailable. <button className="underline" onClick={choiceReviews.retry}>Retry explanations</button></p> : activeExam.questions.some(q => q.question_type.startsWith('mcq') && !q.option_explanations && !choiceReviews.items[q.id]) && <p className="text-sm text-slate-400">Preparing explanations for each choice…</p>}
                    </section> : <>
                    <ExamHeaderTimer onBeforeGrace={() => OmniStudyAPI.saveDraft(activeExam.session_id, payloadRef.current, timeSpentSeconds)} session={activeExam} isSubmitted={isExamSubmitted} onSessionChange={next => setActiveExam(prev => prev?.session_id === next.session_id && !lockedPaper(prev.status) ? next : prev)} onTimeUpdate={setTimeSpentSeconds} onAutoSubmit={handleSubmitExam} />
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-500/50 bg-slate-900 p-4">
                      <p className="text-sm text-slate-300">Ready to finish? Photos are optional. Only uploads already attached will be graded.</p>
                      <button disabled={submittingExam} onClick={handleSubmitExam} className="rounded-lg bg-indigo-600 px-5 py-2 font-semibold text-white">{submittingExam ? 'Submitting…' : 'Submit now'}</button>
                    </div>
                    <p role="status" className="text-xs text-slate-400">{draftState}</p></>}

                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-2.5 text-xs">
                      <span className="text-slate-300 font-medium">
                        Paper Export ({activeExam.questions.length} Questions • {activeExam.max_score} pts):
                      </span>
                      <div className="flex items-center gap-2">
                        <a
                          href={OmniStudyAPI.getExportUrl('exam', activeExam.session_id, 'pdf', false)}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 font-semibold text-white hover:bg-rose-500"
                        >
                          <Download className="h-3.5 w-3.5" />
                          Blank Paper (.PDF)
                        </a>
                        <a
                          href={OmniStudyAPI.getExportUrl('exam', activeExam.session_id, 'pdf', true)}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 font-semibold text-white hover:bg-indigo-500"
                        >
                          <Download className="h-3.5 w-3.5" />
                          With Solutions (.PDF)
                        </a>
                        <a
                          href={OmniStudyAPI.getExportUrl('exam', activeExam.session_id, 'tex', true)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-200 hover:bg-slate-700"
                        >
                          .TEX
                        </a>
                      </div>
                    </div>

                    <div className="space-y-5">
                      {activeExam.questions.map((q, idx) =>
                        q.question_type === 'mcq_single' || q.question_type === 'mcq_multi' ? (
                          <McqFiveOptionCard
                            key={q.id}
                            index={idx + 1}
                            question={q}
                            reasons={q.option_explanations || choiceReviews.items[q.id]}
                            selectedOptions={(isExamSubmitted ? q.selected_options : mcqSelections[q.id]) || []}
                            onToggleOption={(letter) =>
                              handleToggleMcqOption(q.id, q.question_type, letter)
                            }
                            isSubmitted={isExamSubmitted}
                          />
                        ) : (
                          <PasteSolutionBox
                            key={q.id}
                            index={idx + 1}
                            sessionId={activeExam.session_id}
                            question={q}
                            typedAnswer={(isExamSubmitted ? q.user_answer : writtenAnswers[q.id]) || ''}
                            onChangeTyped={(val) =>
                              setWrittenAnswers((prev) => ({ ...prev, [q.id]: val }))
                            }
                            onImageAttached={(serverPath) =>
                              setImagePaths((prev) => ({ ...prev, [q.id]: serverPath }))
                            }
                            isSubmitted={isExamSubmitted}
                          />
                        )
                      )}
                    </div>
                  </>
                )}
              </div>
            ) : activeTab === 'wrong_bank' ? (
              <div className="mx-auto max-w-4xl space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
                  <div>
                    <h2 className="text-base font-bold text-white">
                      Wrong Question Collection (錯題本) — Spaced Review
                    </h2>
                    <p className="text-xs text-slate-400">
                      Answer a question (or its mutated twin) correctly 3 times in a row (0/3 &rarr; 3/3) to graduate it automatically.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setWrongFilter('active')}
                      className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                        wrongFilter === 'active'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      Active Mistakes
                    </button>
                    <button
                      onClick={() => setWrongFilter('graduated')}
                      className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                        wrongFilter === 'graduated'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      Graduated (3/3 Mastered)
                    </button>
                    <a
                      href={OmniStudyAPI.getExportUrl('wrong-bank', activeChapter.id, 'pdf')}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download .PDF
                    </a>
                    <a
                      href={OmniStudyAPI.getExportUrl('wrong-bank', activeChapter.id, 'tex')}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700"
                    >
                      Export .TEX
                    </a>
                  </div>
                </div>

                {wrongError ? <div role="alert" className="p-5 text-rose-200">{wrongError} <button onClick={() => refreshChapters(activeChapter.id, selectedSectionIds)}>Retry</button></div> : wrongItems.length === 0 ? (
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-10 text-center text-xs text-slate-400">
                    No {wrongFilter} questions in this chapter yet.
                  </div>
                ) : (
                  wrongItems.filter(item => !dueOnly || !item.next_review_at || new Date(item.next_review_at).getTime() <= Date.now()).map((item) => (
                    <WrongQuestionCard
                      key={item.id}
                      item={item}
                      onUpdated={() => refreshChapters(activeChapter.id, selectedSectionIds)}
                    />
                  ))
                )}
              </div>
            ) : (
              <div className="mx-auto max-w-4xl space-y-4">
                <h2 className="text-base font-bold">Recorded Study & Assessment History</h2>
                {activeChapter.study_history?.map((h) => (
                  <div
                    key={h.session_id}
                    className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-xs"
                  >
                    <div className="space-y-1">
                      <span className="rounded bg-indigo-500/20 px-2 py-0.5 font-bold uppercase text-indigo-300">
                        {h.mode.replace('_', ' ')}
                      </span>
                      <div className="text-slate-400">
                        <button className="underline text-indigo-300 mr-3" onClick={async () => {
                          const exam = await OmniStudyAPI.getAssessment(h.session_id);setActiveExam(exam);setIsExamSubmitted(lockedPaper(exam.status));setDraftState('');
                          const selections: Record<number,string[]> = {}, written: Record<number,string> = {};
                          exam.draft_answers?.forEach(a=>{if(Array.isArray(a.user_answer))selections[a.question_id]=a.user_answer;else written[a.question_id]=a.user_answer || '';});
                          setMcqSelections(selections);setWrittenAnswers(written);setImagePaths({});setActiveTab('exam');
                        }}>{lockedPaper(h.status) ? 'Review results' : 'Open / resume'}</button>
                        Started: {new Date(h.started_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <div className="text-sm font-bold text-emerald-400">
                          {h.status.startsWith('submitted_') ? 'Written grading pending' : `${h.total_score} / ${h.max_score} pts (${h.accuracy_percent}%)`}
                        </div>
                        <div className="text-slate-400">
                          Time Spent: {Math.round(h.time_spent_seconds / 60)} mins
                        </div>
                      </div>
                      <a
                        href={OmniStudyAPI.getExportUrl('exam', h.session_id, 'pdf', true)}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 font-semibold text-white hover:bg-rose-500"
                      >
                        <Download className="h-3.5 w-3.5" />
                        .PDF
                      </a>
                      <a
                        href={OmniStudyAPI.getExportUrl('exam', h.session_id, 'tex', true)}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-lg bg-slate-800 px-3 py-1.5 text-slate-200 hover:bg-slate-700"
                      >
                        .TEX
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </main>
        </div>
      </div>

      <SettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        onSaved={() => OmniStudyAPI.getHealth().then(setHealth)}
      />

      {/* ONBOARDING MODAL */}
      {showOnboardModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <form
            onSubmit={handleOnboardSubmit}
            className="w-full max-w-lg rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white">
                Import a chapter
              </h2>
              {chapters.length > 0 && (
                <button
                  type="button"
                  disabled={onboarding}
                  onClick={() => {
                    setShowOnboardModal(false);
                    setSlideFile(null);
                    setTextbookFile(null);
                    setTestbankFile(null);
                    setImportError('');
                  }}
                  className="text-xs text-slate-400 hover:text-white"
                >
                  Close
                </button>
              )}
            </div>
            <p className="text-xs text-slate-400">
              Import PDF, PPTX, Markdown, or plain text. Textbooks can be up to 200 MB; lecture slides and question banks can be up to 50 MB each. Generate notes separately after import.
            </p>

            <div className="space-y-3">
              <div>
                <label htmlFor="import-course" className="block text-xs font-medium text-slate-300 mb-1">
                  Course Name
                </label>
                <input id="import-course" disabled={onboarding}
                  required
                  value={courseName}
                  onChange={(e) => setCourseName(e.target.value)}
                  placeholder="e.g., Quantitative Risk Management / Corporate Finance"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label htmlFor="import-chapter" className="block text-xs font-medium text-slate-300 mb-1">
                  Chapter Title
                </label>
                <input id="import-chapter" disabled={onboarding}
                  required
                  value={chapterTitle}
                  onChange={(e) => setChapterTitle(e.target.value)}
                  placeholder="e.g., Chapter 11: Return and Risk — The CAPM"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label htmlFor="import-slides" className="block text-xs font-medium text-indigo-300 mb-1">
                  1. Lecture Slides or Notes (Required)
                </label>
                <input id="import-slides" disabled={onboarding}
                  required
                  type="file"
                  accept=".pptx,.pdf,.md,.txt"
                  onChange={(e) => setSlideFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-300"
                />
              </div>

              <div>
                <label htmlFor="import-textbook" className="block text-xs font-medium text-slate-400 mb-1">
                  2. Supplementary Textbook or Article (Optional)
                </label>
                <input id="import-textbook" disabled={onboarding}
                  type="file"
                  accept=".pdf,.pptx,.md,.txt"
                  onChange={(e) => setTextbookFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-300"
                />
              </div>

              <div>
                <label htmlFor="import-testbank" className="block text-xs font-medium text-purple-300 mb-1">
                  3. Question Bank or Past Exam Paper (Optional)
                </label>
                <input id="import-testbank" disabled={onboarding}
                  type="file"
                  accept=".pdf,.pptx,.md,.txt"
                  onChange={(e) => setTestbankFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-300"
                />
              </div>
            </div>

            {importError && <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-950/60 px-3 py-2 text-sm text-rose-100">{importError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="submit"
                disabled={onboarding || !slideFile}
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                <FileUp className="h-4 w-4" />
                {onboarding
                  ? 'Importing files…'
                  : 'Import Chapter'}
              </button>
            </div>
          </form>
        </div>
      )}

      {activeChapter && !(activeTab === 'exam' && activeExam && !isExamSubmitted) && (
        <HandsFreeVoiceOrb
          chapterId={activeChapter.id}
          sectionIds={selectedSectionIds}
          chapterTitle={activeChapter.chapter_title}
        />
      )}
    </div>
  );
}

export default App;
