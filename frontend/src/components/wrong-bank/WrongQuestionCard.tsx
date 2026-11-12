import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Sparkles, CheckCircle2, Flame, Eye } from 'lucide-react';
import { WrongQuestionItem } from '../../types/assessment';
import { OmniStudyAPI } from '../../services/api';

interface Props {
  item: WrongQuestionItem;
  onUpdated: () => void;
}

const OPTION_KEYS: Array<'A' | 'B' | 'C' | 'D' | 'E'> = ['A', 'B', 'C', 'D', 'E'];

export const WrongQuestionCard: React.FC<Props> = ({ item, onUpdated }) => {
  const [selectedLetters, setSelectedLetters] = useState<string[]>([]);
  const [typedAttempt, setTypedAttempt] = useState('');
  const [mutating, setMutating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showDiagnosis, setShowDiagnosis] = useState(false);
  const [attemptResult, setAttemptResult] = useState<{
    is_correct: boolean;
    badge: string;
    graduated: boolean;
    feedback: string;
  } | null>(null);

  const isMcq = item.question_type === 'mcq_single' || item.question_type === 'mcq_multi';

  const toggleLetter = (letter: string) => {
    if (item.question_type === 'mcq_single') {
      setSelectedLetters([letter]);
    } else {
      setSelectedLetters((prev) =>
        prev.includes(letter) ? prev.filter((l) => l !== letter) : [...prev, letter]
      );
    }
  };

  const handleMutate = async () => {
    setMutating(true);
    setAttemptResult(null);
    setSelectedLetters([]);
    setTypedAttempt('');
    try {
      await OmniStudyAPI.mutateWrongQuestion(item.id);
      onUpdated();
    } finally {
      setMutating(false);
    }
  };

  const handleReviewSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = isMcq ? selectedLetters : typedAttempt;
      const res = await OmniStudyAPI.attemptWrongQuestion(item.id, payload);
      setAttemptResult(res);
      onUpdated();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="flex items-center gap-1 rounded-md bg-amber-500/20 border border-amber-500/40 px-2.5 py-1 text-xs font-bold text-amber-300">
            <Flame className="h-3.5 w-3.5 text-amber-400" />
            Graduation Streak: {item.consecutive_correct_count} / 3
          </span>
          <span className="rounded-md bg-slate-800 px-2.5 py-1 text-xs font-medium text-indigo-300">
            {item.core_concept_tag}
          </span>
          {item.mutation_generation > 0 && (
            <span className="rounded-md bg-purple-500/20 border border-purple-500/40 px-2 py-0.5 text-xs text-purple-300">
              Mutated Twin v{item.mutation_generation}
            </span>
          )}
          <span className="text-xs text-slate-400">({item.slide_reference})</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleMutate}
            disabled={mutating}
            className="flex items-center gap-1.5 rounded-lg border border-purple-500/40 bg-purple-500/15 px-3 py-1.5 text-xs font-semibold text-purple-200 hover:bg-purple-500/25 transition"
            title="Regenerate the exact same concept with new numbers and shuffled A-E options"
          >
            <Sparkles className="h-3.5 w-3.5 text-purple-300" />
            {mutating ? 'Mutating Numbers & Options...' : 'Mutate Similar Question'}
          </button>

          <button
            type="button"
            onClick={() => setShowDiagnosis((s) => !s)}
            className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
          >
            <Eye className="h-3.5 w-3.5" />
            {showDiagnosis ? 'Hide Past Diagnosis' : 'Inspect Past Mistake'}
          </button>
        </div>
      </div>

      <div className="prose prose-invert max-w-none text-sm">
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
          {item.prompt_markdown}
        </ReactMarkdown>
      </div>

      {isMcq && item.options ? (
        <div className="grid gap-2">
          {OPTION_KEYS.map((letter) => {
            const txt = item.options?.[letter];
            if (!txt) return null;
            const picked = selectedLetters.includes(letter);
            return (
              <button
                key={letter}
                type="button"
                onClick={() => toggleLetter(letter)}
                className={`flex items-start gap-3 rounded-lg border p-2.5 text-left text-xs transition ${
                  picked
                    ? 'border-indigo-500 bg-indigo-500/20 text-white'
                    : 'border-slate-800 bg-slate-950/60 text-slate-300 hover:border-slate-700'
                }`}
              >
                <span className="font-bold text-indigo-400">{letter}.</span>
                <div className="prose prose-invert max-w-none text-xs flex-1">
                  <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                    {String(txt)}
                  </ReactMarkdown>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <textarea
          value={typedAttempt}
          onChange={(e) => setTypedAttempt(e.target.value)}
          rows={3}
          placeholder="Enter your derivation / answer to advance your 3-strike graduation streak..."
          className="w-full rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs text-slate-100"
        />
      )}

      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-slate-400">
          Previous wrong pick: <code className="text-rose-400">{item.user_wrong_answer || 'None'}</code>
        </span>
        <button
          type="button"
          disabled={submitting}
          onClick={handleReviewSubmit}
          className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 transition"
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          {submitting ? 'Checking...' : 'Verify & Update Streak'}
        </button>
      </div>

      {attemptResult && (
        <div
          className={`rounded-lg border p-3 text-xs ${
            attemptResult.is_correct
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
              : 'border-rose-500/40 bg-rose-500/10 text-rose-200'
          }`}
        >
          <p className="font-bold">
            {attemptResult.graduated
              ? '🎉 3/3 Consecutive Correct! This question has graduated from your Wrong Question Bank!'
              : attemptResult.is_correct
              ? `✅ Correct! Streak advanced to ${attemptResult.badge}.`
              : `❌ Not quite — Streak reset to ${attemptResult.badge}.`}
          </p>
          <p className="mt-1 text-slate-300">{attemptResult.feedback}</p>
        </div>
      )}

      {showDiagnosis && (
        <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 text-xs space-y-2">
          <div className="font-semibold text-amber-300">
            Official Answer: {item.correct_answer}
          </div>
          <div className="prose prose-invert max-w-none text-xs text-slate-300">
            <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
              {item.ai_diagnosis_and_solution || ''}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
};
