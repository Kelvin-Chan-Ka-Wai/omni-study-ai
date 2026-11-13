import axios from 'axios';
import {
  ActiveExamSession,
  ChapterSummary,
  WrongQuestionItem,
} from '../types/assessment';

export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || `http://${window.location.hostname || '127.0.0.1'}:8000`;

const api = axios.create({
  baseURL: BACKEND_URL,
  timeout: 120000,
  withCredentials: true,
});

let session: Promise<unknown> | null = null;
api.interceptors.request.use(async (config) => {
  if (!session) session = axios.get(`${BACKEND_URL}/api/session`, { withCredentials: true }).catch((error) => { session = null; throw error; });
  await session;
  return config;
});
api.interceptors.response.use((response) => response, (error) => {
  if (error.response?.status === 401) session = null;
  window.dispatchEvent(new CustomEvent('omnistudy-error', { detail: error.response?.data?.detail || error.message || 'Request failed. Please retry.' }));
  return Promise.reject(error);
});

let currentJob: string | null = null;
async function generateJob(payload: object) {
  const { data } = await api.post('/api/jobs', payload);
  currentJob = data.job_id;
  window.dispatchEvent(new CustomEvent('omnistudy-job', { detail: true }));
  try {
    while (true) {
      const { data: job } = await api.get(`/api/jobs/${data.job_id}`);
      if (job.status === 'completed') return job.result;
      if (job.status === 'failed' || job.status === 'canceled') {
        const message = job.message || 'Generation canceled';
        window.dispatchEvent(new CustomEvent('omnistudy-error', { detail: message }));
        throw new Error(message);
      }
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
  } finally {
    currentJob = null;
    window.dispatchEvent(new CustomEvent('omnistudy-job', { detail: false }));
  }
}

export const OmniStudyAPI = {
  async restoreBackup(form: FormData) { return (await api.post('/api/backup/restore', form)).data; },
  async cancelGeneration() { if (currentJob) await api.delete(`/api/jobs/${currentJob}`); },
  async getActiveAssessment(id: number): Promise<ActiveExamSession | null> { return (await api.get(`/api/assessments/active/${id}`)).data; },
  async getAssessment(id: number): Promise<ActiveExamSession> { return (await api.get(`/api/assessments/${id}`)).data; },
  async saveDraft(id: number, answers: object[], time: number) { return (await api.put(`/api/assessments/${id}/draft`, { answers, time_spent_seconds: time })).data; },
  async controlTimer(id: number, isPaused: boolean, grace = false): Promise<ActiveExamSession> { return (await api.patch(`/api/assessments/${id}/timer`, { is_paused: isPaused, time_spent_seconds: 0, enter_grace_upload: grace })).data; },
  async noteVersions(chapter: number, section: number): Promise<{ id: number; reason: string; created_at: string }[]> { return (await api.get(`/api/chapters/${chapter}/sections/${section}/versions`)).data; },
  async restoreNote(chapter: number, section: number, version: number) { return (await api.post(`/api/chapters/${chapter}/sections/${section}/restore/${version}`)).data; },
  async sources(chapter: number, section: number): Promise<{ pages: number[]; citations: {page: number; url: string}[] }> { return (await api.get(`/api/chapters/${chapter}/sections/${section}/sources`)).data; },
  async transcribeImage(session: number, question: number) { return (await api.post(`/api/assessments/${session}/questions/${question}/transcribe`)).data; },
  async saveSlideText(chapter: number, page: number, text: string) { return (await api.put(`/api/chapters/${chapter}/transcription`, { page, text })).data; },
  async getHealth() {
    const { data } = await api.get('/api/health');
    return data;
  },

  async getSettings() {
    const { data } = await api.get('/api/settings');
    return data;
  },

  async updateSettings(payload: any) {
    const { data } = await api.put('/api/settings', payload);
    return data;
  },

  async syncBrowserToken() {
    const { data } = await api.post('/api/settings/sync-browser-token');
    return data;
  },

  async listChapters(): Promise<ChapterSummary[]> {
    const { data } = await api.get('/api/chapters');
    return data;
  },

  async getChapterDetail(chapterId: number): Promise<ChapterSummary> {
    const { data } = await api.get(`/api/chapters/${chapterId}`);
    return data;
  },

  async deleteChapter(chapterId: number) {
    const { data } = await api.delete(`/api/chapters/${chapterId}`);
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
    if (textbookFile) form.append('textbook_file', textbookFile);
    if (testbankFile) form.append('testbank_file', testbankFile);
    const { data } = await api.post('/api/chapters/onboard', form);
    return data;
  },

  async uploadChapterTestbank(chapterId: number, testbankFile: File) {
    const form = new FormData();
    form.append('testbank_file', testbankFile);
    const { data } = await api.post(`/api/chapters/${chapterId}/upload-testbank`, form);
    return data;
  },

  async clearChapterNotes(chapterId: number, sectionIds?: number[]) {
    const { data } = await api.post(`/api/chapters/${chapterId}/clear-notes`, {
      section_ids: sectionIds || [],
    });
    return data;
  },

  async regenerateChapterNotes(chapterId: number, sectionIds?: number[]) {
    return generateJob({ kind: 'notes', chapter_id: chapterId, section_ids: sectionIds || [] });
  },

  async generateAssessment(chapterId: number, mode: 'section_quiz' | 'mock_test' | 'midterm' | 'final', sectionIds: number[]): Promise<ActiveExamSession> {
    return generateJob({ kind: 'assessment', chapter_id: chapterId, mode, section_ids: sectionIds });
  },

  async pasteClipboardImage(sessionId: number, questionId: number, imageBase64: string) {
    const { data } = await api.post(`/api/assessments/${sessionId}/questions/${questionId}/paste-image`, {
      image_base64: imageBase64,
    });
    return data;
  },

  async uploadSolutionImageFile(sessionId: number, questionId: number, file: File) {
    const form = new FormData();
    form.append('session_id', String(sessionId));
    form.append('question_id', String(questionId));
    form.append('image_file', file);
    const { data } = await api.post(`/api/assessments/${sessionId}/questions/${questionId}/upload-image`, form);
    return data;
  },

  async uploadHandwrittenImage(sessionId: number, questionId: number, imageBlob: Blob) {
    const form = new FormData();
    form.append('session_id', String(sessionId));
    form.append('question_id', String(questionId));
    form.append('image_file', imageBlob, 'paste_solution.png');
    const { data } = await api.post(`/api/assessments/${sessionId}/questions/${questionId}/upload-image`, form);
    return data;
  },

  async submitAssessment(sessionId: number, timeSpentSeconds: number, answers: any[]) {
    const { data } = await api.post(`/api/assessments/${sessionId}/submit`, {
      time_spent_seconds: timeSpentSeconds,
      answers,
    });
    return data;
  },

  async listWrongQuestions(
    chapterId: number,
    status: 'active' | 'graduated' = 'active'
  ): Promise<WrongQuestionItem[]> {
    const { data } = await api.get(`/api/wrong-bank/${chapterId}`, {
      params: { status },
    });
    return data;
  },

  async attemptWrongQuestion(wrongId: number, userAnswer: string | string[]) {
    const { data } = await api.post(`/api/wrong-bank/${wrongId}/attempt`, {
      user_answer: userAnswer,
    });
    return data;
  },

  async mutateWrongQuestion(wrongId: number) {
    const { data } = await api.post(`/api/wrong-bank/${wrongId}/mutate`);
    return data;
  },

  async transcribeAudio(audioBlob: Blob, voiceLang: string): Promise<{ transcript: string }> {
    const form = new FormData();
    form.append('audio_file', audioBlob, 'speech.webm');
    form.append('voice_lang', voiceLang);
    const { data } = await api.post('/api/voice/transcribe', form);
    return data;
  },

  async voiceDiscuss(payload: {
    chapter_id: number;
    section_ids: number[];
    user_transcript: string;
    history: { role: string; content: string }[];
    voice_lang: string;
  }) {
    const { data } = await api.post('/api/voice/discuss', payload);
    return data;
  },

  getExportUrl(
    type: 'chapter' | 'exam' | 'wrong-bank',
    id: number,
    fmt: 'md' | 'tex' | 'pdf',
    includeSolutions: boolean = true,
    sectionIds?: number[]
  ) {
    if (type === 'exam') {
      return `${BACKEND_URL}/api/export/exam/${id}?fmt=${fmt}&include_solutions=${includeSolutions}`;
    }
    if (type === 'chapter') {
      return `${BACKEND_URL}/api/export/chapter/${id}?fmt=${fmt}&section_ids=${(sectionIds || []).join(',')}`;
    }
    return `${BACKEND_URL}/api/export/${type}/${id}?fmt=${fmt}`;
  },
};
