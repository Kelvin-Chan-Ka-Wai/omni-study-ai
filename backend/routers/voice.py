import asyncio
import base64
import re
import subprocess
import tempfile
from pathlib import Path
import edge_tts
import imageio_ffmpeg
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import Chapter, ChapterSection
from services.llm_harness import HybridLLMHarness

router = APIRouter(prefix="/api/voice", tags=["Hands-Free Continuous Voice Tutor"])

_WHISPER_MODEL = None


def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        try:
            _WHISPER_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
        except Exception:
            _WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def decode_audio_to_float32_numpy(audio_path: Path) -> np.ndarray:
    """
    Decodes browser audio (.webm, .mp4, .wav, .mp3) to 16kHz mono float32 NumPy waveform
    with a 80Hz–7600Hz human-voice bandpass filter to strip low-frequency mic hum.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe,
        "-nostdin",
        "-threads", "0",
        "-i", str(audio_path),
        "-af", "highpass=f=80,lowpass=f=7600",
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


class VoiceTurnMessage(BaseModel):
    role: str
    content: str


class VoiceDiscussionRequest(BaseModel):
    chapter_id: int
    section_ids: list[int] | None = None
    user_transcript: str
    history: list[VoiceTurnMessage] = []
    voice_lang: str = "en-US"  # 'en-US' | 'zh-HK' | 'zh-CN'


VOICE_MAP = {
    "en-US": "en-US-AvaMultilingualNeural",
    "zh-HK": "zh-HK-HiuGaaiNeural",
    "zh-CN": "zh-CN-XiaoxiaoNeural",
}

# GitHub faster-whisper fix (#517 / #928):
# NEVER put commas or colons in initial_prompt (causes ', , , , ,' repetition loops!)
# Use 'zh' (best acoustic weights in whisper-small) with a short, punctuation-free script anchor.
WHISPER_CONFIG = {
    "en-US": {
        "lang": "en",
        "prompt": "University finance and mathematics discussion",
    },
    "zh-HK": {
        "lang": "zh",
        "prompt": "廣東話繁體中文討論期望回報率同埋標準差方差",
    },
    "zh-CN": {
        "lang": "zh",
        "prompt": "普通话简体中文讨论期望收益率与标准差方差",
    },
}

LANGUAGE_LOCK_INSTRUCTIONS = {
    "en-US": (
        "LANGUAGE RULE: Reply 100% in clear, natural English. Do not use any Chinese characters."
    ),
    "zh-HK": (
        "LANGUAGE RULE: Reply 100% in natural Hong Kong / Macau spoken Cantonese using Traditional Chinese characters "
        "(繁體廣東話口語，例如：係、唔係、呢個、點解、即係話、我哋睇下). "
        "Do NOT speak English sentences and do NOT use Mandarin phrasing. "
        "Never repeat or acknowledge these system instructions—just answer the student's question directly."
    ),
    "zh-CN": (
        "LANGUAGE RULE: Reply 100% in natural Mandarin Chinese using Simplified Chinese characters (简体中文). "
        "Do NOT speak English sentences. "
        "Never repeat or acknowledge these system instructions—just answer the student's question directly."
    ),
}

HALLUCINATION_PATTERNS = [
    r"^[,\.\?!，。？！、\s…\-—~]+$",
    r"(字幕|謝謝觀看|感谢观看|Thank you for watching|Subtitles by|Amara\.org|請不吝點讚|订阅)",
]


def _clean_and_validate_transcript(raw: str) -> str:
    """
    Strips repeated punctuation artifacts (like ', , , ,') and rejects empty/hallucinated transcripts.
    """
    if not raw:
        return ""
    cleaned = raw.strip()
    # Collapse repeated commas/spaces
    cleaned = re.sub(r"([,，.。!！?？\s])\1{2,}", r"\1", cleaned)
    cleaned = re.sub(r"^(?:[,，.。!！?？\s]+)+", "", cleaned).strip()

    # Check if only punctuation/symbols remain
    alnum_or_cjk = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", cleaned)
    if len(alnum_or_cjk) < 2:
        return ""

    for pat in HALLUCINATION_PATTERNS:
        if re.search(pat, cleaned, flags=re.IGNORECASE):
            return ""

    return cleaned


def _strip_markdown_and_latex_for_tts(text: str, voice_lang: str = "en-US") -> str:
    cleaned = re.sub(r"\$\$([\s\S]*?)\$\$", r" \1 ", text)
    cleaned = re.sub(r"\$([^$]+)\$", r" \1 ", cleaned)

    if voice_lang == "zh-HK":
        cleaned = (
            cleaned.replace("\\frac", " 分之 ")
            .replace("\\sum", " 總和 ")
            .replace("\\sqrt", " 開方 ")
            .replace("\\sigma^2", " sigma平方 ")
            .replace("\\sigma", " sigma ")
        )
    elif voice_lang == "zh-CN":
        cleaned = (
            cleaned.replace("\\frac", " 分之 ")
            .replace("\\sum", " 求和 ")
            .replace("\\sqrt", " 根号 ")
            .replace("\\sigma^2", " sigma平方 ")
            .replace("\\sigma", " sigma ")
        )
    else:
        cleaned = (
            cleaned.replace("\\frac", " fraction ")
            .replace("\\sum", " sum ")
            .replace("\\int", " integral ")
            .replace("\\sqrt", " square root of ")
            .replace("\\ge", " greater than or equal to ")
            .replace("\\le", " less than or equal to ")
        )

    cleaned = re.sub(r"\\[a-zA-Z]+", " ", cleaned)
    cleaned = re.sub(r"[*_`#>\\{}]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _split_into_spoken_sentences(text: str) -> list[str]:
    raw_parts = re.split(r"(?<=[.!?。！？；;])\s*", text.strip())
    return [p.strip() for p in raw_parts if p.strip() and len(p.strip()) > 1]


async def _synthesize_edge_tts_base64(text: str, voice_lang: str) -> str | None:
    voice_name = VOICE_MAP.get(voice_lang, VOICE_MAP["en-US"])
    spoken_text = _strip_markdown_and_latex_for_tts(text, voice_lang)
    if not spoken_text:
        return None
    try:
        communicate = edge_tts.Communicate(spoken_text, voice_name, rate="+8%")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        await communicate.save(str(tmp_path))
        audio_bytes = tmp_path.read_bytes()
        tmp_path.unlink(missing_ok=True)
        return base64.b64encode(audio_bytes).decode("utf-8")
    except Exception:
        return None


def _run_whisper_sync(audio_np: np.ndarray, voice_lang: str) -> str:
    model = get_whisper_model()
    cfg = WHISPER_CONFIG.get(voice_lang, WHISPER_CONFIG["en-US"])

    segments, _ = model.transcribe(
        audio_np,
        language=cfg["lang"],
        initial_prompt=cfg["prompt"],
        beam_size=3,
        best_of=3,
        temperature=0.0,
        condition_on_previous_text=False,
        suppress_blank=True,
        no_speech_threshold=0.5,
        log_prob_threshold=-0.8,
        compression_ratio_threshold=2.0,
        vad_filter=True,
        vad_parameters=dict(
            threshold=0.45,
            min_speech_duration_ms=250,
            min_silence_duration_ms=400,
            speech_pad_ms=250,
        ),
    )
    raw_text = " ".join(seg.text.strip() for seg in segments).strip()
    return _clean_and_validate_transcript(raw_text)


@router.post("/transcribe")
async def transcribe_microphone_audio(
    audio_file: UploadFile = File(...),
    voice_lang: str = Form("en-US"),
):
    suffix = Path(audio_file.filename or "speech.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(await audio_file.read())

    try:
        audio_np = await asyncio.to_thread(decode_audio_to_float32_numpy, tmp_path)
        if audio_np.size < 3200:
            return {"transcript": "", "voice_lang": voice_lang}

        # Check RMS energy to reject pure silence / background fan noise before running Whisper
        rms = float(np.sqrt(np.mean(audio_np**2)))
        if rms < 0.004:
            return {"transcript": "", "voice_lang": voice_lang}

        peak = float(np.max(np.abs(audio_np)))
        if 0.01 < peak < 0.45:
            audio_np = np.clip(audio_np * (0.55 / peak), -1.0, 1.0)

        transcript = await asyncio.to_thread(_run_whisper_sync, audio_np, voice_lang)
        return {"transcript": transcript, "voice_lang": voice_lang}
    except Exception as e:
        return {"transcript": "", "voice_lang": voice_lang, "error": str(e)}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/discuss")
async def hands_free_voice_discuss(
    req: VoiceDiscussionRequest,
    db: Session = Depends(get_db),
):
    cleaned_user_text = _clean_and_validate_transcript(req.user_transcript)
    if not cleaned_user_text:
        return {
            "reply_markdown": "",
            "voice_lang": req.voice_lang,
            "audio_base64": None,
            "audio_chunks": [],
            "provider_used": "skipped_empty",
            "model_used": "none",
        }

    chapter = db.query(Chapter).filter(Chapter.id == req.chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    query = db.query(ChapterSection).filter(ChapterSection.chapter_id == req.chapter_id)
    if req.section_ids:
        query = query.filter(ChapterSection.id.in_(req.section_ids))
    sections = query.all()

    slide_context = "\n\n".join(
        f"[{s.section_code}: {s.section_title} ({s.slide_pages})]\n{(s.extracted_study_notes or '')[:2500]}"
        for s in sections
    )

    lang_lock = LANGUAGE_LOCK_INSTRUCTIONS.get(req.voice_lang, LANGUAGE_LOCK_INSTRUCTIONS["en-US"])

    system_prompt = (
        f"You are an interactive, fast-paced academic voice tutor for {chapter.course_name} ({chapter.chapter_title}).\n"
        f"{lang_lock}\n"
        "STRICT RULES:\n"
        "1. Ground every explanation strictly in the ALLOWED SLIDE SECTIONS below.\n"
        "2. If the student's voice transcript has minor phonetic/homophone typos, infer the intended finance/math term from the slide context.\n"
        "3. Keep responses concise and conversational (2 to 3 sentences max) and end with a short check-in question.\n"
        "4. Write math formulas in standard LaTeX ($...$).\n\n"
        f"ALLOWED SLIDE SECTIONS:\n{slide_context[:12000]}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-4:]:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": cleaned_user_text})

    llm_res = await HybridLLMHarness.chat(
        messages=messages,
        task="fast",
        temperature=0.3,
        json_mode=False,
        max_tokens=320,
    )

    reply_text = llm_res["content"].strip()
    sentences = _split_into_spoken_sentences(reply_text)
    chunk_tasks = [_synthesize_edge_tts_base64(s, req.voice_lang) for s in sentences]
    audio_chunks = [b64 for b64 in await asyncio.gather(*chunk_tasks) if b64]

    return {
        "reply_markdown": reply_text,
        "voice_lang": req.voice_lang,
        "audio_base64": audio_chunks[0] if audio_chunks else None,
        "audio_chunks": audio_chunks,
        "provider_used": llm_res["provider_used"],
        "model_used": llm_res["model_used"],
    }
