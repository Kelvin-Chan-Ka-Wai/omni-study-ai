import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { ClipboardPaste, Upload, CheckCircle2, AlertTriangle, Image as ImageIcon } from 'lucide-react';
import { AssessmentQuestion } from '../../types/assessment';
import { BACKEND_URL, OmniStudyAPI } from '../../services/api';

interface Props {
  index: number;
  sessionId: number;
  question: AssessmentQuestion;
  typedAnswer: string;
  onChangeTyped: (val: string) => void;
  onImageAttached: (serverPath: string, previewUrl: string) => void;
  isSubmitted: boolean;
}

export const PasteSolutionBox: React.FC<Props> = ({
  index,
  sessionId,
  question,
  typedAnswer,
  onChangeTyped,
  onImageAttached,
  isSubmitted,
}) => {
  const [uploading, setUploading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(question.preview_url || null);

  const handlePaste = async (e: React.ClipboardEvent<HTMLDivElement>) => {
    if (isSubmitted) return;
    const items = e.clipboardData?.items;
    if (!items) return;

    for (const item of Array.from(items)) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const blob = item.getAsFile();
        if (!blob) continue;

        setUploading(true);
        const reader = new FileReader();
        reader.onload = async () => {
          try {
            const b64 = reader.result as string;
            const res = await OmniStudyAPI.pasteClipboardImage(sessionId, question.id, b64);
            const fullPreview = `${BACKEND_URL}${res.preview_url}`;
            setPreviewUrl(fullPreview);
            onImageAttached(res.handwritten_image_path, fullPreview);
          } finally {
            setUploading(false);
          }
        };
        reader.readAsDataURL(blob);
        break;
      }
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await OmniStudyAPI.uploadSolutionImageFile(sessionId, question.id, file);
      const fullPreview = `${BACKEND_URL}${res.preview_url}`;
      setPreviewUrl(fullPreview);
      onImageAttached(res.handwritten_image_path, fullPreview);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      onPaste={handlePaste}
      className="rounded-xl border border-slate-800 bg-slate-900/70 p-5 space-y-4 focus-within:border-indigo-500/60 transition"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="rounded-md bg-slate-800 px-2.5 py-1 text-xs font-bold text-indigo-400">
            Q{index} • {question.max_points} pts
          </span>
          <span className="rounded-md bg-emerald-500/15 px-2.5 py-1 text-xs font-medium text-emerald-300 border border-emerald-500/30 uppercase">
            {question.question_type.replace('_', ' ')} (AI Vision Step-by-Step Rubric)
          </span>
          <span className="text-xs text-slate-400">
            [{question.slide_reference} • {question.core_concept_tag}]
          </span>
        </div>

        {isSubmitted && question.score_awarded !== undefined && (
          <span className="rounded-lg bg-indigo-500/20 border border-indigo-500/40 px-3 py-1 text-xs font-bold text-indigo-200">
            Score: {question.score_awarded} / {question.max_points} pts
          </span>
        )}
      </div>

      <div className="prose prose-invert max-w-none text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
          {question.prompt_markdown}
        </ReactMarkdown>
      </div>

      <textarea
        disabled={isSubmitted}
        value={typedAnswer}
        onChange={(e) => onChangeTyped(e.target.value)}
        placeholder="Type your solution / LaTeX steps here, OR click inside this card and press Cmd + V to paste a screenshot / iPad handwritten photo..."
        rows={3}
        className="w-full rounded-lg border border-slate-800 bg-slate-950 p-3 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
      />

      {/* Cmd+V Paste & Continuity Camera Dropzone */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-slate-700 bg-slate-950/60 px-4 py-3">
        <div className="flex items-center gap-2.5 text-xs text-slate-300">
          <ClipboardPaste className="h-4 w-4 text-indigo-400" />
          <span>
            Press <kbd className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-indigo-300">Cmd + V</kbd> anywhere in this box to paste a handwritten calculation screenshot
          </span>
        </div>

        {!isSubmitted && (
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 transition">
            <Upload className="h-3.5 w-3.5 text-indigo-400" />
            <span>{uploading ? 'Uploading...' : 'Attach Photo / Continuity Camera'}</span>
            <input
              type="file"
              accept="image/*"
              onChange={handleFileChange}
              className="hidden"
            />
          </label>
        )}
      </div>

      {previewUrl && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-400">
            <ImageIcon className="h-3.5 w-3.5" />
            <span>Handwritten Solution Attached (Ready for GLM-OCR & DeepSeek Step Grader):</span>
          </div>
          <img
            src={previewUrl}
            alt="Handwritten Solution Preview"
            className="max-h-64 rounded-lg border border-slate-700 object-contain bg-white p-1"
          />
        </div>
      )}

      {isSubmitted && question.ai_feedback_and_solution && (
        <div className="mt-4 rounded-lg border border-slate-700/80 bg-slate-950/90 p-4 text-xs space-y-2">
          <div className="flex items-center gap-2 font-semibold text-indigo-300">
            {question.is_flagged_wrong ? (
              <>
                <AlertTriangle className="h-4 w-4 text-amber-400" />
                <span>Below 80% Mastery — Added to Wrong Question Bank • Step-by-Step Rubric Breakdown:</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                <span>Mastered (&ge;80%) • Step-by-Step Rubric Breakdown:</span>
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
