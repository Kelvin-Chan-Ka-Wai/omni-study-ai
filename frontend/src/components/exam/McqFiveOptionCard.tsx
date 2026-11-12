import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { CheckCircle2, AlertTriangle } from 'lucide-react';
import { AssessmentQuestion } from '../../types/assessment';

interface Props {
  index: number;
  question: AssessmentQuestion;
  selectedOptions: string[];
  onToggleOption: (letter: 'A' | 'B' | 'C' | 'D' | 'E') => void;
  isSubmitted: boolean;
}

const OPTION_KEYS: Array<'A' | 'B' | 'C' | 'D' | 'E'> = ['A', 'B', 'C', 'D', 'E'];

export const McqFiveOptionCard: React.FC<Props> = ({
  index,
  question,
  selectedOptions,
  onToggleOption,
  isSubmitted,
}) => {
  const isMulti = question.question_type === 'mcq_multi';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="rounded-md bg-slate-800 px-2.5 py-1 text-xs font-bold text-indigo-400">
            Q{index} • {question.max_points} pts
          </span>
          <span
            className={`rounded-md px-2.5 py-1 text-xs font-medium border ${
              isMulti
                ? 'bg-purple-500/15 text-purple-300 border-purple-500/30'
                : 'bg-sky-500/15 text-sky-300 border-sky-500/30'
            }`}
          >
            {isMulti
              ? '5-Option Multi-Select (Partial Credit | 0 if Wrong Pick)'
              : '5-Option Single Choice (A–E)'}
          </span>
          <span className="text-xs text-slate-400">
            [{question.slide_reference} • {question.core_concept_tag}]
          </span>
        </div>

        {isSubmitted && question.score_awarded !== undefined && (
          <span
            className={`rounded-lg px-3 py-1 text-xs font-bold ${
              question.score_awarded === question.max_points
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                : question.score_awarded > 0
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
            }`}
          >
            Score: {question.score_awarded} / {question.max_points} pts
          </span>
        )}
      </div>

      <div className="prose prose-invert max-w-none text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
          {question.prompt_markdown}
        </ReactMarkdown>
      </div>

      <div className="grid gap-2.5 pt-1">
        {OPTION_KEYS.map((letter) => {
          const optText = question.options?.[letter] ?? `Option ${letter}`;
          const isPicked = selectedOptions.includes(letter);
          const isCorrectChoice =
            isSubmitted &&
            question.correct_answer?.toUpperCase().includes(letter);

          let borderStyle = 'border-slate-800 bg-slate-950/60 hover:border-slate-700';
          if (isPicked && !isSubmitted) {
            borderStyle = 'border-indigo-500 bg-indigo-500/15 text-indigo-100';
          } else if (isSubmitted) {
            if (isCorrectChoice && isPicked) {
              borderStyle = 'border-emerald-500 bg-emerald-500/15 text-emerald-100';
            } else if (isCorrectChoice && !isPicked) {
              borderStyle = 'border-amber-500/70 bg-amber-500/10 text-amber-100';
            } else if (!isCorrectChoice && isPicked) {
              borderStyle = 'border-rose-500 bg-rose-500/15 text-rose-200';
            }
          }

          return (
            <button
              key={letter}
              type="button"
              disabled={isSubmitted}
              onClick={() => onToggleOption(letter)}
              className={`flex items-start gap-3 rounded-lg border p-3 text-left text-sm transition ${borderStyle}`}
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-bold ${
                  isPicked
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800 text-slate-300'
                }`}
              >
                {letter}
              </span>
              <div className="prose prose-invert max-w-none text-sm leading-snug flex-1">
                <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {String(optText)}
                </ReactMarkdown>
              </div>
            </button>
          );
        })}
      </div>

      {isSubmitted && question.ai_feedback_and_solution && (
        <div className="mt-4 rounded-lg border border-slate-700/80 bg-slate-950/90 p-4 text-xs space-y-2">
          <div className="flex items-center gap-2 font-semibold text-indigo-300">
            {question.is_flagged_wrong ? (
              <>
                <AlertTriangle className="h-4 w-4 text-amber-400" />
                <span>Added to Wrong Question Collection (0/3 Streak) • AI Solution:</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                <span>Full Credit • Official Explanation:</span>
              </>
            )}
          </div>
          <div className="prose prose-invert max-w-none text-xs text-slate-300">
            <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
              {question.ai_feedback_and_solution}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
};
