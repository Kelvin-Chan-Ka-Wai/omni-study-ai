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

export interface StudyHistoryItem {
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
  study_history?: StudyHistoryItem[];
}

export interface AssessmentQuestion {
  id: number;
  section_id: number;
  question_type: 'mcq_single' | 'mcq_multi' | 'short_answer' | 'calculation';
  core_concept_tag: string;
  slide_reference: string;
  prompt_markdown: string;
  options?: Record<'A' | 'B' | 'C' | 'D' | 'E', string> | null;
  max_points: number;
  // Populated after grading
  user_answer?: string;
  correct_answer?: string;
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
  provider_used?: string;
  model_used?: string;
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
}
