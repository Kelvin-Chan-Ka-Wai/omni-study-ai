from dotenv import load_dotenv
from fastapi import APIRouter
from pydantic import BaseModel
from config import ROOT_ENV_PATH, settings
from services.llm_harness import HybridLLMHarness
from services.um_token_keeper import UMTokenKeeper

router = APIRouter(prefix="/api/settings", tags=["In-App AI & Study Settings"])


class UpdateSettingsRequest(BaseModel):
    active_llm_provider: str | None = None
    open_webui_base_url: str | None = None
    open_webui_api_key: str | None = None
    umpass_username: str | None = None
    umpass_password: str | None = None
    open_webui_text_model: str | None = None
    open_webui_fast_model: str | None = None
    open_webui_ocr_model: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    section_mastery_threshold: float | None = None
    wrong_question_graduation_streak: int | None = None
    midterm_final_duration_minutes: int | None = None
    photo_upload_grace_minutes: int | None = None


@router.get("")
async def get_current_settings():
    load_dotenv(dotenv_path=ROOT_ENV_PATH, override=True)
    um_alive, reason = await HybridLLMHarness.is_um_genai_alive(force=True)
    return {
        "active_llm_provider": settings.ACTIVE_LLM_PROVIDER,
        "open_webui_base_url": settings.OPEN_WEBUI_BASE_URL,
        "open_webui_api_key": settings.OPEN_WEBUI_API_KEY,
        "umpass_username": settings.UMPASS_USERNAME,
        "umpass_password": settings.UMPASS_PASSWORD,
        "open_webui_text_model": settings.OPEN_WEBUI_TEXT_MODEL,
        "open_webui_fast_model": settings.OPEN_WEBUI_FAST_MODEL,
        "open_webui_ocr_model": settings.OPEN_WEBUI_OCR_MODEL,
        "deepseek_api_key": settings.DEEPSEEK_API_KEY,
        "deepseek_model": settings.DEEPSEEK_MODEL,
        "openai_api_key": settings.OPENAI_API_KEY,
        "openai_model": getattr(settings, "OPENAI_MODEL", "terra-6.1"),
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "ollama_model": settings.OLLAMA_MODEL,
        "section_mastery_threshold": settings.SECTION_MASTERY_THRESHOLD,
        "wrong_question_graduation_streak": settings.WRONG_QUESTION_GRADUATION_STREAK,
        "midterm_final_duration_minutes": settings.MIDTERM_FINAL_DURATION_MINUTES,
        "photo_upload_grace_minutes": settings.PHOTO_UPLOAD_GRACE_MINUTES,
        "um_genai_connected": um_alive,
        "um_genai_status": reason,
        "um_detected_models": HybridLLMHarness._um_cached_models,
    }


@router.post("/sync-browser-token")
async def sync_um_token_from_browser_or_umpass():
    token, msg = await UMTokenKeeper.auto_heal_token()
    if token:
        um_alive, reason = await HybridLLMHarness.is_um_genai_alive(force=True)
        return {
            "synced": True,
            "token": token,
            "reason": msg,
            "um_genai_connected": um_alive,
            "um_genai_status": reason,
            "um_detected_models": HybridLLMHarness._um_cached_models,
        }
    return {"synced": False, "reason": msg}


@router.put("")
async def update_settings(req: UpdateSettingsRequest):
    mapping = {
        "ACTIVE_LLM_PROVIDER": req.active_llm_provider,
        "OPEN_WEBUI_BASE_URL": req.open_webui_base_url,
        "OPEN_WEBUI_API_KEY": req.open_webui_api_key,
        "UMPASS_USERNAME": req.umpass_username,
        "UMPASS_PASSWORD": req.umpass_password,
        "OPEN_WEBUI_TEXT_MODEL": req.open_webui_text_model,
        "OPEN_WEBUI_FAST_MODEL": req.open_webui_fast_model,
        "OPEN_WEBUI_OCR_MODEL": req.open_webui_ocr_model,
        "DEEPSEEK_API_KEY": req.deepseek_api_key,
        "DEEPSEEK_MODEL": req.deepseek_model,
        "OPENAI_API_KEY": req.openai_api_key,
        "OPENAI_MODEL": req.openai_model,
        "OLLAMA_BASE_URL": req.ollama_base_url,
        "OLLAMA_MODEL": req.ollama_model,
        "SECTION_MASTERY_THRESHOLD": req.section_mastery_threshold,
        "WRONG_QUESTION_GRADUATION_STREAK": req.wrong_question_graduation_streak,
        "MIDTERM_FINAL_DURATION_MINUTES": req.midterm_final_duration_minutes,
        "PHOTO_UPLOAD_GRACE_MINUTES": req.photo_upload_grace_minutes,
    }

    secret_keys = {"OPEN_WEBUI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "UMPASS_PASSWORD"}

    for env_key, val in mapping.items():
        if val is None:
            continue
        if env_key in secret_keys and str(val).strip() == "":
            continue
        setattr(settings, env_key, val)
        UMTokenKeeper.persist_env_key(env_key, str(val).strip())

    um_alive, reason = await HybridLLMHarness.is_um_genai_alive(force=True)
    return {
        "saved": True,
        "active_llm_provider": settings.ACTIVE_LLM_PROVIDER,
        "um_genai_connected": um_alive,
        "um_genai_status": reason,
        "um_detected_models": HybridLLMHarness._um_cached_models,
    }
