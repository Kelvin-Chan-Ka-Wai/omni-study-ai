import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {
  Sparkles,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Eye,
  EyeOff,
  Send,
} from 'lucide-react';
import { WrongQuestionItem } from '../../types/assessment';
import { OmniStudyAPI } from '../../services/api';

interface Props {
  item: WrongQuestionItem;
  onUpdated: () => void;
}

export const WrongQuestionCard: React.FC<Props> = ({ item, onUpdated }) => {
  const [selectedLetters, setSelectedLetters] = useState<string[]>([]);
  const [writtenRetry, setWrittenRetry] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [showSolution, setShowSolution] = useState(false);
  const [feedbackBanner, setFeedbackBanner] = useState<{
    correct: boolean;
    text: string;
  } | null>(null);

  // Safely normalize options whether backend sent an object or a JSON string
  const parsedOptions: Record<string, string> | null = React.useMemo(() => {
    const raw = item.options;
    if (!raw) return null;
    if (typeof raw === 'object' && !Array.isArray(raw)) {
      return raw as Record<string, string>;
    }
    if (typeof raw === 'string') {
      try {
        const obj = JSON.parse(raw);
        return obj && typeof obj === 'object' ? obj : null;
      } catch {
        return null;
      }
    }
    return null;
  }, [item]);

  const isMcq =
    (item.question_type === 'mcq_single' || item.question_type === 'mcq_multi') &&
    parsedOptions !== null;

  const streak = item.consecutive_correct_count ?? 0;
  const required = item.required_streak ?? 3;

  const toggleLetter = (letter: string) => {
    if (item.question_type === 'mcq_single') {
      setSelectedLetters([letter]);
    } else {
      setSelectedLetters((prev) =>
        prev.includes(letter) ? prev.filter((x) => x !== letter) : [...prev, letter]
      );
    }
  };

  const handlePracticeSubmit = async () => {
    const answerPayload = isMcq ? selectedLetters : writtenRetry.trim();
    if ((Array.isArray(answerPayload) && answerPayload.length === 0) || !answerPayload) {
      return;
    }
    setSubmitting(true);
    setFeedbackBanner(null);
    try {
      const res = await OmniStudyAPI.attemptWrongQuestion(item.id, answerPayload);
      setFeedbackBanner({
        correct: Boolean(res.attempt_is_correct),
        text:
          res.attempt_feedback ||
          (res.attempt_is_correct
            ? 'Correct! Streak incremented.'
            : `Incorrect.Streak reset to 0/${required}.`),
      });
      onUpdated();
    } finally {
      setSubmitting(false);
    }
  };

  const handleMutate = async () => {
    setMutating(true);
    setFeedbackBanner(null);
    setSelectedLetters([]);
    setWrittenRetry('');
    try {
      await OmniStudyAPI.mutateWrongQuestion(item.id);
      onUpdated();
    } finally {
      setMutating(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5 space-y-4 shadow-lg">
      {/* Header Row */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-indigo-500/20 border border-indigo-500/40 px-2 py-0.5 text-[11px] font-bold text-indigo-300">
            {item.core_concept_tag || 'Core Concept'}
          </span>
          <span className="text-[11px] text-slate-400">
            {item.slide_reference || 'Slide Scope'} • {(item.question_type || 'mcq').replace('_', ' ').toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`rounded-lg px-2.5 py-1 text-xs font-bold ${
              streak >= required
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
            }`}
          >
            Mastery Streak: {streak}/{required}
          </span>

          <button
            type="button"
            disabled={mutating}
            onClick={handleMutate}
            className="flex items-center gap-1 rounded-lg border border-purple-500/40 bg-purple-500/15 px-2.5 py-1 text-xs font-semibold text-purple-200 hover:bg-purple-500/25 disabled:opacity-50 transition"
            title="Generate an isomorphic twin question testing the exact same concept with new numbers"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${mutating ? 'animate-spin' : ''}`} />
            {mutating ? 'Mutating...' : 'Mutate Twin Question'}
          </button>
        </div>
      </div>

      <div className="text-xs text-slate-400">Next review: {item.next_review_at ? new Date(item.next_review_at).toLocaleString() : 'Ready now'} · Variants: {item.mutation_generation || 0}</div>
      {item.original_question && <details className="text-sm text-slate-300"><summary>Original mistake (preserved)</summary><p>{item.original_question.prompt_markdown}</p></details>}
      {/* Question Prompt */}
      <div className="study-markdown prose prose-invert max-w-none text-sm text-slate-100">
        <ReactMarkdown
          remarkPlugins={[remarkMath]}
          rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
        >
          {item.prompt_markdown || ''}
        </ReactMarkdown>
      </div>

      {/* Interactive Retry Input (MCQ A-E or Written Box) */}
      {isMcq && parsedOptions ? (
        <div className="grid grid-cols-1 gap-2">
          {Object.entries(parsedOptions).map(([letter, text]) => {
            const isSelected = selectedLetters.includes(letter);
            return (
              <button
                key={letter}
                type="button"
                onClick={() => toggleLetter(letter)}
                className={`flex items-start gap-3 rounded-xl border p-3 text-left text-xs transition ${
                  isSelected
                    ? 'border-indigo-500 bg-indigo-600/20 text-white'
                    : 'border-slate-800 bg-slate-950/60 text-slate-300 hover:bg-slate-800/70'
                }`}
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px] font-bold ${
                    isSelected ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {letter}
                </span>
                <div className="prose prose-invert max-w-none flex-1 text-xs">
                  <ReactMarkdown
                    remarkPlugins={[remarkMath]}
                    rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
                  >
                    {String(text || '')}
                  </ReactMarkdown>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <textarea
          rows={3}
          value={writtenRetry}
          onChange={(e) => setWrittenRetry(e.target.value)}
          placeholder="Type your step-by-step retry answer or final numerical value..."
          className="w-full rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-white focus:border-indigo-500 focus:outline-none"
        />
      )}

      {/* Feedback Banner */}
      {feedbackBanner && (
        <div
          className={`flex items-center gap-2 rounded-xl border p-3 text-xs font-medium ${
            feedbackBanner.correct
              ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-200'
              : 'border-rose-500/40 bg-rose-500/15 text-rose-200'
          }`}
        >
          {feedbackBanner.correct ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0 text-rose-400" />
          )}
          <span>{feedbackBanner.text}</span>
        </div>
      )}

      {/* Actions & Solution Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={() => setShowSolution((s) => !s)}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
        >
          {showSolution ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          {showSolution ? 'Hide Diagnosis & Solution' : 'Show Diagnosis & Solution'}
        </button>

        <button
          type="button"
          disabled={submitting}
          onClick={handlePracticeSubmit}
          className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 transition"
        >
          <Send className="h-3.5 w-3.5" />
          {submitting ? 'Checking Answer...' : 'Submit Retry (+1 Streak)'}
        </button>
      </div>

      {showSolution && (
        <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4 space-y-2 text-xs">
          <div className="font-bold text-indigo-300 flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5" />
            Official Answer: {item.correct_answer}
          </div>
          {item.user_wrong_answer && (
            <div className="text-rose-300/90">
              Your Previous Mistake: {item.user_wrong_answer}
            </div>
          )}
          <div className="study-markdown prose prose-invert max-w-none text-xs text-slate-300 pt-1">
            <ReactMarkdown
              remarkPlugins={[remarkMath]}
              rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
            >
              {item.ai_diagnosis_and_solution || '_No additional diagnosis recorded._'}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
};
