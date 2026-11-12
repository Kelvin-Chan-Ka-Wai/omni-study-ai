import axios from 'axios';
import {
  ActiveExamSession,
  ChapterSummary,
  WrongQuestionItem,
} from '../types/assessment';

export const BACKEND_URL = 'http://localhost:8000';

const api = axios.create({
  baseURL: BACKEND_URL,
});

export const OmniStudyAPI = {
  async syncBrowserToken() {
    const { data } = await api.post("/api/settings/sync-browser-token");
    return data;
  },

  async getSettings() {
    const { data } = await api.get("/api/settings");
    return data;
  },

  async updateSettings(payload: Record<string, any>) {
    const { data } = await api.put("/api/settings", payload);
    return data;
  },

  async getHealth() {
    const { data } = await api.get('/api/health');
    return data;
  },

  async listChapters(): Promise<ChapterSummary[]> {
    const { data } = await api.get('/api/chapters');
    return data;
  },

  async deleteChapter(chapterId: number) {
    const { data } = await api.delete(`/api/chapters/${chapterId}`);
    return data;
  },

  async getChapterDetail(chapterId: number): Promise<ChapterSummary> {
    const { data } = await api.get(`/api/chapters/${chapterId}`);
    return data;
  },

  async onboardChapter(
    courseName: string,
    chapterTitle: string,
    slideFile: File,
    textbookFile?: File | null,
    testbankFile?: File | null
  ) {
    const form = new FormData();
    form.append('course_name', courseName);
    form.append('chapter_title', chapterTitle);
    form.append('slide_file', slideFile);
    if (textbookFile) {
      form.append('textbook_file', textbookFile);
    }
    if (testbankFile) {
      form.append('testbank_file', testbankFile);
    }
    const { data } = await api.post('/api/chapters/onboard', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  async uploadChapterTestbank(chapterId: number, testbankFile: File) {
    const form = new FormData();
    form.append('testbank_file', testbankFile);
    const { data } = await api.post(`/api/chapters/${chapterId}/upload-testbank`, form);
    return data;
  },

  async regenerateChapterNotes(chapterId: number) {
    const { data } = await api.post(`/api/chapters/${chapterId}/regenerate-notes`);
    return data;
  },

  async generateAssessment(
    chapterId: number,
    mode: 'section_quiz' | 'mock_test' | 'midterm' | 'final',
    sectionIds: number[]
  ): Promise<ActiveExamSession> {
    const { data } = await api.post('/api/assessments/generate', {
      chapter_id: chapterId,
      mode,
      section_ids: sectionIds,
    });
    return data;
  },

  async updateExamTimer(
    sessionId: number,
    isPaused: boolean,
    timeSpentSeconds: number,
    enterGraceUpload = false
  ) {
    const { data } = await api.patch(`/api/assessments/${sessionId}/timer`, {
      is_paused: isPaused,
      time_spent_seconds: timeSpentSeconds,
      enter_grace_upload: enterGraceUpload,
    });
    return data;
  },

  async pasteClipboardImage(
    sessionId: number,
    questionId: number,
    imageBase64: string
  ): Promise<{
    question_id: number;
    handwritten_image_path: string;
    preview_url: string;
  }> {
    const { data } = await api.post(
      `/api/assessments/${sessionId}/questions/${questionId}/paste-image`,
      { image_base64: imageBase64 }
    );
    return data;
  },

  async uploadSolutionImageFile(
    sessionId: number,
    questionId: number,
    file: File
  ): Promise<{
    question_id: number;
    handwritten_image_path: string;
    preview_url: string;
  }> {
    const form = new FormData();
    form.append('image_file', file);
    const { data } = await api.post(
      `/api/assessments/${sessionId}/questions/${questionId}/upload-image`,
      form
    );
    return data;
  },

  async submitAssessment(
    sessionId: number,
    timeSpentSeconds: number,
    answers: Array<{
      question_id: number;
      user_answer: string | string[];
      handwritten_image_path?: string;
    }>
  ) {
    const { data } = await api.post(`/api/assessments/${sessionId}/submit`, {
      time_spent_seconds: timeSpentSeconds,
      answers,
    });
    return data;
  },

  async listWrongQuestions(
    chapterId?: number,
    status: 'active' | 'graduated' | 'all' = 'active'
  ): Promise<WrongQuestionItem[]> {
    const { data } = await api.get('/api/wrong-bank', {
      params: { chapter_id: chapterId, status },
    });
    return data;
  },

  async mutateWrongQuestion(wrongId: number): Promise<WrongQuestionItem> {
    const { data } = await api.post(`/api/wrong-bank/${wrongId}/mutate`);
    return data;
  },

  async attemptWrongQuestion(wrongId: number, userAnswer: string | string[]) {
    const { data } = await api.post(`/api/wrong-bank/${wrongId}/attempt`, {
      user_answer: userAnswer,
    });
    return data;
  },

  async transcribeAudio(audioBlob: Blob, voiceLang: string): Promise<{ transcript: string }> {
    const form = new FormData();
    form.append("audio_file", audioBlob, "speech.webm");
    form.append("voice_lang", voiceLang);
    const { data } = await api.post("/api/voice/transcribe", form);
    return data;
  },

  async voiceDiscuss(payload: {
    chapter_id: number;
    section_ids: number[];
    user_transcript: string;
    history: Array<{ role: string; content: string }>;
    voice_lang: string;
  }): Promise<{
    reply_markdown: string;
    audio_base64?: string | null;
    audio_chunks?: string[];
    provider_used: string;
    model_used: string;
  }> {
    const { data } = await api.post('/api/voice/discuss', payload);
    return data;
  },

  getExportUrl(
    type: 'chapter' | 'exam' | 'wrong-bank',
    id: number,
    fmt: 'md' | 'tex' | 'pdf',
    includeSolutions = true
  ) {
    return `${BACKEND_URL}/api/export/${type}/${id}?fmt=${fmt}&include_solutions=${includeSolutions}`;
  },
};
