import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {
  Mic,
  MicOff,
  Volume2,
  MessageSquare,
  ChevronDown,
  Send,
  Globe,
  Sparkles,
  Hand,
  AlertCircle,
  RotateCcw,
} from 'lucide-react';
import { OmniStudyAPI } from '../../services/api';

interface Props {
  chapterId: number;
  sectionIds: number[];
  chapterTitle: string;
}

interface Turn {
  role: 'user' | 'assistant';
  content: string;
  lang?: string;
}

export const HandsFreeVoiceOrb: React.FC<Props> = ({
  chapterId,
  sectionIds,
  chapterTitle,
}) => {
  const [isHandsFreeActive, setIsHandsFreeActive] = useState(false);
  const [status, setStatus] = useState<
    'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking'
  >('idle');
  const [voiceLang, setVoiceLang] = useState<'en-US' | 'zh-HK' | 'zh-CN'>('en-US');
  const [manualInput, setManualInput] = useState('');
  const [history, setHistory] = useState<Turn[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [activeModelBadge, setActiveModelBadge] = useState('GLM-Flash-5.3 / DeepSeek');
  const [micWarning, setMicWarning] = useState<string | null>(null);
  const [micVolume, setMicVolume] = useState(0);
  const [isUserTalkingNow, setIsUserTalkingNow] = useState(false);

  const activeFlagRef = useRef(false);
  const voiceLangRef = useRef<'en-US' | 'zh-HK' | 'zh-CN'>('en-US');
  const historyRef = useRef<Turn[]>([]);
  const sessionTokenRef = useRef(0);
  const recorderIdRef = useRef(0);

  // STRICT PHASE LOCK:
  // 'idle' | 'listening' -> Mic can record
  // 'locked' -> Mic is physically OFF (Transcribing, Thinking, or AI Speaking). ONLY Spacebar/Interrupt or end-of-speech can unlock it!
  const turnPhaseRef = useRef<string>('idle');

  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const rafRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  activeFlagRef.current = isHandsFreeActive;
  voiceLangRef.current = voiceLang;
  historyRef.current = history;

  const killAllAudioPlayback = () => {
    sessionTokenRef.current += 1;
    if (audioPlayerRef.current) {
      try {
        audioPlayerRef.current.onended = null;
        audioPlayerRef.current.onerror = null;
        audioPlayerRef.current.pause();
        audioPlayerRef.current.src = '';
      } catch {}
      audioPlayerRef.current = null;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
  };

  const stopMicHardware = () => {
    recorderIdRef.current += 1;
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (mediaRecorderRef.current) {
      try {
        mediaRecorderRef.current.ondataavailable = null;
        mediaRecorderRef.current.onstop = null;
        if (mediaRecorderRef.current.state !== 'inactive') {
          mediaRecorderRef.current.stop();
        }
      } catch {}
      mediaRecorderRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => {
        t.enabled = false;
        t.stop();
      });
      mediaStreamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setMicVolume(0);
    setIsUserTalkingNow(false);
  };

  const startNextListeningUtterance = async () => {
    // HARD LOCK CHECK: Never open microphone if phase is 'locked' (transcribing / thinking / speaking)!
    if (!activeFlagRef.current || turnPhaseRef.current === 'locked') return;

    stopMicHardware();
    turnPhaseRef.current = 'listening';
    const myRecorderId = ++recorderIdRef.current;
    const mySessionToken = sessionTokenRef.current;
    setStatus('listening');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      if (
        !activeFlagRef.current ||
        myRecorderId !== recorderIdRef.current ||
        turnPhaseRef.current === 'locked'
      ) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      mediaStreamRef.current = stream;
      setMicWarning(null);

      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const ctx = new AudioCtx();
      if (ctx.state === 'suspended') {
        await ctx.resume().catch(() => {});
      }
      audioCtxRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const timeDomainData = new Uint8Array(analyser.fftSize);

      audioChunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (
          myRecorderId === recorderIdRef.current &&
          turnPhaseRef.current === 'listening' &&
          e.data &&
          e.data.size > 0
        ) {
          audioChunksRef.current.push(e.data);
        }
      };

      let speechFrames = 0;
      let hasConfirmedSpeech = false;
      let silenceStart = 0;
      const speechStartTime = Date.now();

      recorder.onstop = async () => {
        if (myRecorderId !== recorderIdRef.current) return;

        const capturedChunks = [...audioChunksRef.current];
        // Immediately kill all mic hardware tracks so ZERO sound can enter during transcription!
        stopMicHardware();

        if (!activeFlagRef.current) {
          turnPhaseRef.current = 'idle';
          return;
        }

        const blob = new Blob(capturedChunks, { type: 'audio/webm' });

        // Require at least 4 frames of sustained human voice so random clicks/breaths don't trigger Whisper
        if (hasConfirmedSpeech && blob.size > 2000) {
          // ENGAGE HARD LOCK: Mic is 100% locked until AI finishes speaking (or Spacebar is pressed)
          turnPhaseRef.current = 'locked';
          setStatus('transcribing');
          const langAtCapture = voiceLangRef.current;

          try {
            const { transcript } = await OmniStudyAPI.transcribeAudio(blob, langAtCapture);
            if (mySessionToken !== sessionTokenRef.current) return;

            const cleaned = (transcript || '').trim();
            if (cleaned.length >= 2) {
              await sendTranscriptToTutor(cleaned, langAtCapture, mySessionToken);
              return;
            }
          } catch {}

          // If Whisper determined it was just background noise / empty, unlock and resume listening
          if (mySessionToken === sessionTokenRef.current && activeFlagRef.current) {
            turnPhaseRef.current = 'idle';
            startNextListeningUtterance();
          }
        } else {
          // Idle buffer rotation -> reopen cleanly if not locked
          if (activeFlagRef.current && turnPhaseRef.current !== 'locked') {
            startNextListeningUtterance();
          }
        }
      };

      recorder.start(150);

      const monitorLoop = () => {
        if (
          !activeFlagRef.current ||
          myRecorderId !== recorderIdRef.current ||
          turnPhaseRef.current === 'locked'
        ) {
          return;
        }

        analyser.getByteTimeDomainData(timeDomainData);
        let sumSq = 0;
        for (let i = 0; i < timeDomainData.length; i++) {
          const centered = (timeDomainData[i] - 128) / 128.0;
          sumSq += centered * centered;
        }
        const rms = Math.sqrt(sumSq / timeDomainData.length);
        const level = Math.min(100, Math.round(rms * 360));
        setMicVolume(level);

        const now = Date.now();
        if (level >= 11) {
          speechFrames += 1;
          if (speechFrames >= 4 && !hasConfirmedSpeech) {
            hasConfirmedSpeech = true;
            setIsUserTalkingNow(true);
          }
          silenceStart = now;
        } else if (hasConfirmedSpeech && now - silenceStart > 920) {
          // User finished speaking and paused for 0.92s -> lock & transcribe!
          setIsUserTalkingNow(false);
          if (recorder.state === 'recording') {
            recorder.stop();
          }
          return;
        } else if (!hasConfirmedSpeech && now - speechStartTime > 12000) {
          if (recorder.state === 'recording') {
            recorder.stop();
          }
          return;
        }

        rafRef.current = requestAnimationFrame(monitorLoop);
      };

      rafRef.current = requestAnimationFrame(monitorLoop);
    } catch {
      setMicWarning(
        'Microphone access blocked! Please allow Microphone in Chrome / macOS System Settings.'
      );
      setIsHandsFreeActive(false);
      turnPhaseRef.current = 'idle';
      setStatus('idle');
    }
  };

  const forceSendCurrentRecordingNow = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  };

  // Explicit user Spacebar / Button interrupt: the ONLY way to unlock during Transcribing/Thinking/Speaking
  const interruptAiAndListenNow = () => {
    killAllAudioPlayback();
    stopMicHardware();
    turnPhaseRef.current = 'idle';
    if (activeFlagRef.current) {
      setTimeout(() => startNextListeningUtterance(), 150);
    } else {
      setStatus('idle');
    }
  };

  const handleLanguageChange = (newLang: 'en-US' | 'zh-HK' | 'zh-CN') => {
    voiceLangRef.current = newLang;
    setVoiceLang(newLang);
    killAllAudioPlayback();
    stopMicHardware();
    turnPhaseRef.current = 'idle';
    setHistory([]);
    historyRef.current = [];
    if (activeFlagRef.current) {
      setTimeout(() => startNextListeningUtterance(), 180);
    } else {
      setStatus('idle');
    }
  };

  // Global Spacebar interrupt works during Transcribing, Thinking, OR Speaking!
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        isHandsFreeActive &&
        (status === 'speaking' || status === 'thinking' || status === 'transcribing') &&
        e.code === 'Space' &&
        document.activeElement?.tagName !== 'INPUT' &&
        document.activeElement?.tagName !== 'TEXTAREA'
      ) {
        e.preventDefault();
        interruptAiAndListenNow();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isHandsFreeActive, status]);

  const playAudioChunksSequentially = async (chunks: string[], tokenAtStart: number) => {
    // Ensure mic hardware remains 100% OFF & LOCKED throughout playback
    stopMicHardware();
    turnPhaseRef.current = 'locked';
    setStatus('speaking');

    for (const b64 of chunks) {
      if (turnPhaseRef.current !== 'locked' || tokenAtStart !== sessionTokenRef.current) {
        break;
      }
      await new Promise<void>((resolve) => {
        const audio = new Audio(`data:audio/mp3;base64,${b64}`);
        audioPlayerRef.current = audio;
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        audio.play().catch(() => resolve());
      });
    }

    if (tokenAtStart !== sessionTokenRef.current) return;

    // Wait 400ms after the speaker finishes so room echo completely dies out before unlocking the mic!
    setTimeout(() => {
      if (tokenAtStart !== sessionTokenRef.current) return;
      turnPhaseRef.current = 'idle';
      if (activeFlagRef.current) {
        startNextListeningUtterance();
      } else {
        setStatus('idle');
      }
    }, 400);
  };

  const sendTranscriptToTutor = async (
    trimmed: string,
    targetLang = voiceLangRef.current,
    tokenAtStart = sessionTokenRef.current
  ) => {
    // Keep mic hardware strictly OFF & LOCKED while waiting for AI response
    stopMicHardware();
    turnPhaseRef.current = 'locked';
    setStatus('thinking');
    setIsDrawerOpen(true);

    const sameLangHistory = historyRef.current.filter((t) => !t.lang || t.lang === targetLang);
    const updatedHistory: Turn[] = [
      ...sameLangHistory,
      { role: 'user', content: trimmed, lang: targetLang },
    ];
    setHistory(updatedHistory);
    historyRef.current = updatedHistory;

    try {
      const res = await OmniStudyAPI.voiceDiscuss({
        chapter_id: chapterId,
        section_ids: sectionIds,
        user_transcript: trimmed,
        history: updatedHistory.slice(-4).map((h) => ({ role: h.role, content: h.content })),
        voice_lang: targetLang,
      });

      if (tokenAtStart !== sessionTokenRef.current) return;

      if (!res.reply_markdown) {
        turnPhaseRef.current = 'idle';
        if (activeFlagRef.current) startNextListeningUtterance();
        else setStatus('idle');
        return;
      }

      if (res.model_used) {
        setActiveModelBadge(`${res.model_used} (${res.provider_used})`);
      }

      const nextHist: Turn[] = [
        ...updatedHistory,
        {
          role: 'assistant',
          content: res.reply_markdown,
          lang: targetLang,
        },
      ];
      setHistory(nextHist);
      historyRef.current = nextHist;

      const chunks =
        res.audio_chunks && res.audio_chunks.length > 0
          ? res.audio_chunks
          : res.audio_base64
          ? [res.audio_base64]
          : [];

      if (chunks.length > 0) {
        await playAudioChunksSequentially(chunks, tokenAtStart);
      } else {
        turnPhaseRef.current = 'idle';
        if (activeFlagRef.current) startNextListeningUtterance();
        else setStatus('idle');
      }
    } catch {
      if (tokenAtStart === sessionTokenRef.current) {
        turnPhaseRef.current = 'idle';
        if (activeFlagRef.current) startNextListeningUtterance();
        else setStatus('idle');
      }
    }
  };

  useEffect(() => {
    if (isHandsFreeActive) {
      turnPhaseRef.current = 'idle';
      startNextListeningUtterance();
    } else {
      killAllAudioPlayback();
      stopMicHardware();
      turnPhaseRef.current = 'idle';
      setStatus('idle');
    }
    return () => {
      killAllAudioPlayback();
      stopMicHardware();
      turnPhaseRef.current = 'idle';
    };
  }, [isHandsFreeActive]);

  const isMicLockedPhase =
    status === 'transcribing' || status === 'thinking' || status === 'speaking';

  return (
    <div className="fixed bottom-5 right-6 z-40 flex flex-col items-end">
      {isDrawerOpen && (
        <div className="mb-3 flex h-96 w-96 flex-col overflow-hidden rounded-2xl border border-slate-700/80 bg-slate-900/95 shadow-2xl backdrop-blur-md">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-indigo-400" />
              <div>
                <div className="text-xs font-bold text-white">
                  Whisper Hands-Free Voice Tutor
                </div>
                <div className="text-[10px] text-emerald-400 font-mono truncate max-w-[185px]">
                  Model: {activeModelBadge}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <Globe className="h-3.5 w-3.5 text-indigo-400" />
              <select
                value={voiceLang}
                onChange={(e) => handleLanguageChange(e.target.value as any)}
                className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[11px] font-semibold text-slate-100"
              >
                <option value="en-US">English (EN)</option>
                <option value="zh-HK">廣東話 (粵語)</option>
                <option value="zh-CN">普通话 (國語)</option>
              </select>
              <button
                type="button"
                onClick={() => interruptAiAndListenNow()}
                title="Reset Mic & Clear Audio Queue"
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-emerald-400"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setIsDrawerOpen(false)}
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Live Hardware Microphone Status Bar */}
          {isHandsFreeActive && (
            <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/90 px-4 py-2 text-[11px]">
              <div className="flex items-center gap-2 flex-1">
                <span
                  className={`font-semibold shrink-0 ${
                    isMicLockedPhase ? 'text-amber-400' : 'text-emerald-400'
                  }`}
                >
                  {status === 'listening'
                    ? isUserTalkingNow
                      ? 'Recording Speech...'
                      : 'Mic Open:'
                    : status === 'transcribing'
                    ? '🔒 Mic Off (Transcribing...)'
                    : status === 'thinking'
                    ? '🔒 Mic Off (AI Thinking...)'
                    : '🔒 Mic Off (AI Speaking — Press Space to Interrupt)'}
                </span>
                {status === 'listening' && (
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full bg-emerald-500 transition-all duration-75"
                      style={{ width: `${micVolume}%` }}
                    />
                  </div>
                )}
              </div>
              {status === 'listening' && isUserTalkingNow && (
                <button
                  type="button"
                  onClick={forceSendCurrentRecordingNow}
                  className="rounded bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white hover:bg-emerald-500"
                >
                  Send Now
                </button>
              )}
            </div>
          )}

          {micWarning && (
            <div className="flex items-start gap-2 border-b border-rose-500/40 bg-rose-500/15 px-3.5 py-2 text-[11px] text-rose-200">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
              <span>{micWarning}</span>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-3.5 space-y-3 text-xs">
            {history.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center text-slate-400 px-4">
                <Volume2 className="h-8 w-8 text-indigo-400/70 mb-2" />
                <p className="font-medium text-slate-200">
                  {voiceLang === 'zh-HK'
                    ? '廣東話語音導師（防回音鎖定模式）'
                    : voiceLang === 'zh-CN'
                    ? '普通话语音导师（防回音锁定模式）'
                    : 'English Voice Tutor (Strict Mic-Lock Mode)'}
                </p>
                <p className="mt-1 text-[11px]">
                  {voiceLang === 'zh-HK'
                    ? '講完停頓 1 秒即自動發送。處理緊同埋導師講緊嘢嗰陣，咪高峰會完全關閉，按 Spacebar 可隨時打斷！'
                    : voiceLang === 'zh-CN'
                    ? '说完停顿 1 秒自动发送。转录及导师回答期间麦克风完全关闭，按 Spacebar 可随时打断！'
                    : 'Once your voice is sent, the mic stays 100% locked during transcription & AI speech unless you press Spacebar!'}
                </p>
              </div>
            ) : (
              history.map((turn, idx) => (
                <div
                  key={idx}
                  className={`rounded-xl p-3 ${
                    turn.role === 'user'
                      ? 'ml-6 bg-indigo-600/25 border border-indigo-500/40 text-indigo-100'
                      : 'mr-4 bg-slate-800/90 border border-slate-700 text-slate-200'
                  }`}
                >
                  <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    {turn.role === 'user' ? 'You' : `AI Tutor (${turn.lang || voiceLang})`}
                  </div>
                  <div className="prose prose-invert max-w-none text-xs leading-relaxed">
                    <ReactMarkdown
                      remarkPlugins={[remarkMath]}
                      rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
                    >
                      {turn.content}
                    </ReactMarkdown>
                  </div>
                </div>
              ))
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!manualInput.trim()) return;
              const q = manualInput.trim();
              setManualInput('');
              killAllAudioPlayback();
              sendTranscriptToTutor(q, voiceLangRef.current, sessionTokenRef.current);
            }}
            className="flex items-center gap-2 border-t border-slate-800 bg-slate-950 p-2.5"
          >
            <input
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              placeholder={
                voiceLang === 'zh-HK'
                  ? '或者直接打字問導師（用廣東話回答）...'
                  : voiceLang === 'zh-CN'
                  ? '或者直接打字提问（用普通话回答）...'
                  : 'Or type a question to hear spoken explanation...'
              }
              className="flex-1 rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
            />
            <button
              type="submit"
              className="rounded-lg bg-indigo-600 p-1.5 text-white hover:bg-slate-500"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </form>
        </div>
      )}

      <div className="flex items-center gap-2 rounded-full border border-slate-700/80 bg-slate-900/95 p-1.5 shadow-2xl backdrop-blur">
        <button
          type="button"
          onClick={() => {
            const next = !isHandsFreeActive;
            setIsHandsFreeActive(next);
            if (next) setIsDrawerOpen(true);
          }}
          className={`relative flex items-center gap-2.5 rounded-full px-4 py-2 text-xs font-semibold transition ${
            isHandsFreeActive
              ? status === 'speaking'
                ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/30'
                : isMicLockedPhase
                ? 'bg-amber-600 text-white'
                : 'bg-emerald-600 text-white shadow-lg shadow-emerald-500/30'
              : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
          }`}
        >
          {isHandsFreeActive ? (
            <>
              <span className="relative flex h-3 w-3">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" />
                <Mic className="relative h-3.5 w-3.5" />
              </span>
              <span>
                {status === 'listening'
                  ? isUserTalkingNow
                    ? `Recording (${micVolume}%)...`
                    : `Mic Open [${voiceLang}] (${micVolume}%)`
                  : status === 'transcribing'
                  ? `Mic Locked (Transcribing...)`
                  : status === 'thinking'
                  ? 'Mic Locked (Thinking...)'
                  : 'Mic Locked (AI Speaking)'}
              </span>
            </>
          ) : (
            <>
              <MicOff className="h-3.5 w-3.5 text-slate-400" />
              <span>Start Hands-Free Voice Tutor</span>
            </>
          )}
        </button>

        {isHandsFreeActive && isMicLockedPhase && (
          <button
            type="button"
            onClick={interruptAiAndListenNow}
            className="flex items-center gap-1 rounded-full bg-rose-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-rose-500 transition"
            title="Press Spacebar to interrupt and unlock microphone immediately"
          >
            <Hand className="h-3.5 w-3.5" />
            Interrupt (Space)
          </button>
        )}

        <button
          type="button"
          onClick={() => setIsDrawerOpen((o) => !o)}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700"
        >
          <MessageSquare className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
};
