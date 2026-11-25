export interface SlideSection {
  id: number;
  section_code: string;
  section_title: string;
  slide_pages: string;
  extracted_study_notes?: string;
  best_accuracy: number;
  latest_accuracy?: number;
  quiz_attempts?: number;
  is_mastered: boolean;
}

export interface HistorySection {
  id: number | null;
  section_code: string | null;
  section_title: string | null;
  slide_pages: string | null;
  question_count: number;
  answered_count: number;
}

export interface StudyHistoryItem {
  sections?: HistorySection[];
  session_id: number;
  mode: 'section_quiz' | 'mock_test' | 'midterm' | 'final';
  status: string;
  total_score: number;
  max_score: number;
  accuracy_percent: number;
  time_spent_seconds: number;
  started_at: string;
  completed_at?: string;
}

export interface ChapterSummary {
  id: number;
  course_name: string;
  chapter_title: string;
  slide_file_path?: string;
  textbook_file_path?: string;
  testbank_file_path?: string;
  progress_percentage: number;
  active_wrong_count?: number;
  sections: SlideSection[];
  archived_sections?: SlideSection[];
  study_history?: StudyHistoryItem[];
}

export interface SlideOutline {
  sections: Pick<SlideSection, 'section_code' | 'section_title' | 'slide_pages'>[];
  excluded: { page: number; title: string; reason: string }[];
  visual_pages: number[];
  file_url: string;
  can_apply: boolean;
}

export interface AssessmentQuestion {
  id: number;
  section_id: number;
  question_type: 'mcq_single' | 'mcq_multi' | 'short_answer' | 'calculation';
  core_concept_tag: string;
  slide_reference: string;
  testbank_reference?: string | null;
  prompt_markdown: string;
  options?: Record<'A' | 'B' | 'C' | 'D' | 'E', string> | null;
  max_points: number;
  // Populated after grading
  user_answer?: string;
  correct_answer?: string;
  correct_options?: string[];
  selected_options?: string[];
  option_explanations?: Record<string, string>;
  grading_pending?: boolean;
  score_awarded?: number;
  is_flagged_wrong?: boolean;
  ai_feedback_and_solution?: string;
  preview_url?: string;
  handwritten_image_path?: string;
}

export interface ActiveExamSession {
  session_id: number;
  chapter_id: number;
  mode: 'section_quiz' | 'mock_test' | 'midterm' | 'final';
  time_limit_minutes: number;
  grace_period_minutes: number;
  max_score: number;
  total_score?: number;
  provider_used?: string;
  model_used?: string;
  status?: string;
  deadline_at?: string;
  is_paused?: boolean;
  paused_remaining?: number;
  grace_started_at?: string;
  server_now?: string;
  draft_answers?: { question_id: number; user_answer: string | string[]; corrected_transcription?: string }[];
  questions: AssessmentQuestion[];
}

export interface WrongQuestionItem {
  id: number;
  chapter_id: number;
  section_id?: number;
  question_type: 'mcq_single' | 'mcq_multi' | 'short_answer' | 'calculation';
  core_concept_tag: string;
  slide_reference: string;
  prompt_markdown: string;
  options?: Record<'A' | 'B' | 'C' | 'D' | 'E', string> | null;
  correct_answer: string;
  user_wrong_answer?: string;
  ai_diagnosis_and_solution?: string;
  consecutive_correct_count: number;
  badge: string;
  mutation_generation: number;
  status: 'active' | 'graduated';
  last_reviewed_at: string;
  next_review_at?: string;
  required_streak?: number;
  original_question?: { prompt_markdown: string; options_json?: string; correct_answer: string };
}
