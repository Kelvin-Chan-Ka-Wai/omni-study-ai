import React, { useEffect, useState } from 'react';
import {
  Settings,
  CheckCircle2,
  Wifi,
  Save,
  X,
  KeyRound,
  Cpu,
  Eye,
  EyeOff,
  RefreshCw,
  ExternalLink,
} from 'lucide-react';
import { OmniStudyAPI } from '../../services/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export const SettingsModal: React.FC<Props> = ({ isOpen, onClose, onSaved }) => {
  const [form, setForm] = useState<any>({
    active_llm_provider: 'hybrid_um_first',
    open_webui_base_url: 'https://chat.genai.um.edu.mo/api',
    open_webui_api_key: '',
    umpass_username: '',
    umpass_password: '',
    open_webui_text_model: 'deepseek-v4.1-flash-1017',
    open_webui_fast_model: 'GLM-Flash-5.3',
    open_webui_ocr_model: 'GLM-OCR',
    deepseek_api_key: '',
    deepseek_model: 'deepseek-chat',
    openai_api_key: '',
    openai_model: 'terra-6.1',
    ollama_base_url: 'http://localhost:11434/v1',
    ollama_model: 'qwen2.5:14b',
    section_mastery_threshold: 0.8,
    wrong_question_graduation_streak: 3,
    midterm_final_duration_minutes: 120,
    photo_upload_grace_minutes: 5,
  });

  const [status, setStatus] = useState<{
    um_genai_connected?: boolean;
    um_genai_status?: string;
    um_detected_models?: string[];
  }>({});
  const [showSecrets, setShowSecrets] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncingToken, setSyncingToken] = useState(false);
  const [savedBanner, setSavedBanner] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setSavedBanner(null);
    OmniStudyAPI.getSettings()
      .then((data) => {
        setForm({
          ...data,
          openai_model: data.openai_model || 'terra-6.1',
        });
        setStatus({
          um_genai_connected: data.um_genai_connected,
          um_genai_status: data.um_genai_status,
          um_detected_models: data.um_detected_models,
        });
      })
      .catch(() => {
        setStatus({
          um_genai_connected: false,
          um_genai_status:
            'Backend server on port 8000 is stopped. Run the start command in terminal or relaunch OmniStudy AI.app.',
        });
      });
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSyncFromBrowser = async () => {
    setSyncingToken(true);
    setSavedBanner(null);
    try {
      const res = await OmniStudyAPI.syncBrowserToken();
      if (res.synced) {
        setForm((prev: any) => ({ ...prev, open_webui_api_key: res.token }));
        setStatus({
          um_genai_connected: res.um_genai_connected,
          um_genai_status: res.um_genai_status,
          um_detected_models: res.um_detected_models,
        });
        setSavedBanner(res.reason || 'Synced fresh UM GenAI token!');
        onSaved();
      } else {
        setSavedBanner(res.reason || 'Could not auto-read token.');
      }
    } finally {
      setSyncingToken(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSavedBanner(null);
    try {
      const res = await OmniStudyAPI.updateSettings(form);
      setStatus({
        um_genai_connected: res.um_genai_connected,
        um_genai_status: res.um_genai_status,
        um_detected_models: res.um_detected_models,
      });
      setSavedBanner('Settings saved & AI routing updated!');
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <form
        onSubmit={handleSave}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <Settings className="h-5 w-5 text-indigo-400" />
            <div>
              <h2 className="text-base font-bold text-white">
                AI Routing, UM GenAI Token & Backup Models
              </h2>
              <p className="text-[11px] text-slate-400">
                Shortcut: <kbd className="rounded bg-slate-800 px-1.5 py-0.5 font-mono">Cmd + ,</kbd> • Saved directly to local .env
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowSecrets((s) => !s)}
              className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-700"
            >
              {showSecrets ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {showSecrets ? 'Hide Keys' : 'Show Keys'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-5 text-xs">
          <div
            className={`flex items-center justify-between rounded-xl border p-3.5 ${
              status.um_genai_connected
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <Wifi className="h-4 w-4 shrink-0" />
              <div>
                <div className="font-bold">
                  {status.um_genai_connected
                    ? 'UM GenAI (chat.genai.um.edu.mo) Connected — 100% Free Mode Active'
                    : 'UM GenAI Token Expired or Off-Campus — Auto-Routing to DeepSeek / OpenAI (terra-6.1)'}
                </div>
                <div className="text-[11px] opacity-80">
                  {status.um_genai_status || 'Backup engines (DeepSeek & OpenAI terra-6.1) are active.'}
                </div>
              </div>
            </div>
          </div>

          {/* 1. Primary AI Routing Mode Dropdown */}
          <div className="space-y-2">
            <label className="flex items-center gap-1.5 font-semibold text-indigo-300">
              <Cpu className="h-3.5 w-3.5" />
              Primary AI Routing Mode
            </label>
            <select
              value={form.active_llm_provider}
              onChange={(e) => setForm({ ...form, active_llm_provider: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
            >
              <option value="hybrid_um_first">
                Hybrid Auto-Switch: UM GenAI Free &rarr; DeepSeek API &rarr; OpenAI (terra-6.1) (Recommended)
              </option>
              <option value="open_webui">UM GenAI / Open WebUI Only (Campus Free)</option>
              <option value="deepseek">Direct DeepSeek API Only (Worldwide Zero-VPN)</option>
              <option value="openai">OpenAI Backup Only (terra-6.1)</option>
              <option value="ollama">Local Ollama Only (100% Offline Apple Silicon)</option>
            </select>
          </div>

          {/* 2. UM GenAI Session & Auto-Login */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 font-semibold text-white">
                <KeyRound className="h-3.5 w-3.5 text-emerald-400" />
                UM GenAI (chat.genai.um.edu.mo) Session & UMPASS Auto-Login
              </span>

              <div className="flex items-center gap-2">
                <a
                  href="https://chat.genai.um.edu.mo"
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-[11px] text-slate-200 hover:bg-slate-700"
                >
                  <ExternalLink className="h-3 w-3 text-indigo-400" />
                  1. Open UM GenAI
                </a>
                <button
                  type="button"
                  disabled={syncingToken}
                  onClick={handleSyncFromBrowser}
                  className="flex items-center gap-1 rounded-lg bg-emerald-600/90 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-500"
                >
                  <RefreshCw className={`h-3 w-3 ${syncingToken ? 'animate-spin' : ''}`} />
                  {syncingToken ? 'Refreshing Token...' : '2. Auto-Catch UM Token'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
              <div>
                <label className="block text-[11px] font-medium text-emerald-300 mb-1">
                  Auto-Login UMPASS ID (Local .env)
                </label>
                <input
                  value={form.umpass_username || ''}
                  onChange={(e) => setForm({ ...form, umpass_username: e.target.value })}
                  placeholder="e.g. mc12345"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-emerald-300 mb-1">
                  Auto-Login UMPASS Password (Local .env)
                </label>
                <input
                  type={showSecrets ? 'text' : 'password'}
                  value={form.umpass_password || ''}
                  onChange={(e) => setForm({ ...form, umpass_password: e.target.value })}
                  placeholder="••••••••"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
                />
              </div>
            </div>

            <div>
              <label className="block text-[11px] text-slate-400 mb-1">
                UMPASS JWT Bearer / Cookie Token
              </label>
              <input
                type={showSecrets ? 'text' : 'password'}
                value={form.open_webui_api_key || ''}
                onChange={(e) => setForm({ ...form, open_webui_api_key: e.target.value })}
                placeholder="Click Auto-Catch above or paste your token"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-emerald-300"
              />
            </div>

            <div className="grid grid-cols-3 gap-2.5">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Reasoning Model</label>
                <input
                  value={form.open_webui_text_model || ''}
                  onChange={(e) => setForm({ ...form, open_webui_text_model: e.target.value })}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Fast / Mutator Model</label>
                <input
                  value={form.open_webui_fast_model || ''}
                  onChange={(e) => setForm({ ...form, open_webui_fast_model: e.target.value })}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Handwritten OCR Model</label>
                <input
                  value={form.open_webui_ocr_model || ''}
                  onChange={(e) => setForm({ ...form, open_webui_ocr_model: e.target.value })}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
                />
              </div>
            </div>
          </div>

          {/* 3. Backup APIs: DeepSeek + OpenAI (terra-6.1) + Local Ollama */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-white">DeepSeek API</span>
                <span className="text-[10px] text-emerald-400 font-mono">
                  {form.deepseek_api_key ? 'Active' : 'Missing'}
                </span>
              </div>
              <input
                type={showSecrets ? 'text' : 'password'}
                value={form.deepseek_api_key || ''}
                onChange={(e) => setForm({ ...form, deepseek_api_key: e.target.value })}
                placeholder="sk-..."
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-indigo-300"
              />
              <input
                value={form.deepseek_model || 'deepseek-chat'}
                onChange={(e) => setForm({ ...form, deepseek_model: e.target.value })}
                placeholder="deepseek-chat"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 font-mono text-[11px] text-slate-300"
              />
            </div>

            <div className="rounded-xl border border-purple-500/30 bg-purple-500/5 p-3.5 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-purple-200">OpenAI Backup</span>
                <span className="text-[10px] text-purple-300 font-mono">
                  {form.openai_api_key ? 'Active' : 'Missing'}
                </span>
              </div>
              <input
                type={showSecrets ? 'text' : 'password'}
                value={form.openai_api_key || ''}
                onChange={(e) => setForm({ ...form, openai_api_key: e.target.value })}
                placeholder="sk-..."
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-purple-300"
              />
              <input
                value={form.openai_model || 'terra-6.1'}
                onChange={(e) => setForm({ ...form, openai_model: e.target.value })}
                placeholder="terra-6.1"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 font-mono text-[11px] text-purple-200"
              />
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-2">
              <div className="font-semibold text-white">Local Ollama</div>
              <input
                value={form.ollama_model || ''}
                onChange={(e) => setForm({ ...form, ollama_model: e.target.value })}
                placeholder="qwen2.5:14b"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white"
              />
              <div className="text-[10px] text-slate-400">100% Offline Apple Silicon</div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-slate-800 bg-slate-950 px-6 py-3.5">
          {savedBanner ? (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
              <CheckCircle2 className="h-4 w-4" />
              {savedBanner}
            </span>
          ) : (
            <span className="text-[11px] text-slate-400">
              Fallback Chain: UM GenAI &rarr; DeepSeek &rarr; OpenAI (terra-6.1)
            </span>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs text-slate-300 hover:bg-slate-700"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              <Save className="h-3.5 w-3.5" />
              {saving ? 'Testing & Saving...' : 'Save & Test Connection'}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};
