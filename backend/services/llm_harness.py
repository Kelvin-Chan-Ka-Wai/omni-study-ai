import time
import httpx
from openai import AsyncOpenAI
from config import settings
from services.um_token_keeper import UMTokenKeeper


class HybridLLMHarness:
    """
    High-Speed Zero-Lag Router:
    Eliminates multi-retry delays so parallel micro-batches complete in <20 seconds.
    """
    _um_cached_models: list[str] = []
    _last_check_time: float = 0.0
    _last_alive_state: bool = False
    _last_reason: str = "Not checked yet"

    @classmethod
    async def _probe_models_endpoint(cls, token: str) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "Cookie": f"token={token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=2.0, trust_env=False, verify=False) as client:
            return await client.get(f"{settings.OPEN_WEBUI_BASE_URL}/models", headers=headers)

    @classmethod
    async def is_um_genai_alive(cls, force: bool = False) -> tuple[bool, str]:
        now = time.time()
        if not force and (now - cls._last_check_time) < 60.0:
            return cls._last_alive_state, cls._last_reason

        try:
            if settings.OPEN_WEBUI_API_KEY:
                resp = await cls._probe_models_endpoint(settings.OPEN_WEBUI_API_KEY)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    cls._um_cached_models = [m.get("id") for m in data if m.get("id")]
                    cls._last_check_time = now
                    cls._last_alive_state = True
                    cls._last_reason = f"Connected! Found {len(cls._um_cached_models)} models"
                    return True, cls._last_reason

            if await UMTokenKeeper.is_um_campus_reachable():
                healed_token, heal_msg = await UMTokenKeeper.auto_heal_token()
                if healed_token:
                    resp2 = await cls._probe_models_endpoint(healed_token)
                    if resp2.status_code == 200:
                        data = resp2.json().get("data", [])
                        cls._um_cached_models = [m.get("id") for m in data if m.get("id")]
                        cls._last_check_time = now
                        cls._last_alive_state = True
                        cls._last_reason = f"Connected ({heal_msg}) • {len(cls._um_cached_models)} models"
                        return True, cls._last_reason

            cls._last_check_time = now
            cls._last_alive_state = False
            cls._last_reason = "UM Token expired or off-campus (Using Fast DeepSeek Fallback)"
            return False, cls._last_reason
        except Exception as e:
            cls._last_check_time = now
            cls._last_alive_state = False
            cls._last_reason = f"Off-campus / Unreachable ({type(e).__name__})"
            return False, cls._last_reason

    @classmethod
    def _match_um_model(cls, preferred: str) -> str:
        if not cls._um_cached_models:
            return preferred
        if preferred in cls._um_cached_models:
            return preferred
        pref_lower = preferred.lower()
        for m in cls._um_cached_models:
            if pref_lower in m.lower() or m.lower() in pref_lower:
                return m
        if "terra" in pref_lower:
            for m in cls._um_cached_models:
                if "terra" in m.lower() or "gpt" in m.lower():
                    return m
        if "glm" in pref_lower:
            for m in cls._um_cached_models:
                if "glm" in m.lower():
                    return m
        for m in cls._um_cached_models:
            if "deepseek" in m.lower() or "flash" in m.lower():
                return m
        return cls._um_cached_models[0]

    @classmethod
    def _build_um_client(cls, target_model: str) -> tuple[AsyncOpenAI, str, str]:
        http_client = httpx.AsyncClient(timeout=35.0, trust_env=False, verify=False)
        client = AsyncOpenAI(
            base_url=settings.OPEN_WEBUI_BASE_URL,
            api_key=settings.OPEN_WEBUI_API_KEY,
            default_headers={"Cookie": f"token={settings.OPEN_WEBUI_API_KEY}"},
            http_client=http_client,
        )
        return client, cls._match_um_model(target_model), "um_genai"

    @classmethod
    def _build_deepseek_client(cls) -> tuple[AsyncOpenAI, str, str]:
        http_client = httpx.AsyncClient(timeout=35.0, trust_env=False)
        client = AsyncOpenAI(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            http_client=http_client,
        )
        return client, settings.DEEPSEEK_MODEL or "deepseek-chat", "deepseek_api"

    @classmethod
    async def get_client_and_model(cls, task: str = "reasoning") -> tuple[AsyncOpenAI, str, str]:
        mode = settings.ACTIVE_LLM_PROVIDER
        alive, _ = await cls.is_um_genai_alive()

        # If user selected OpenAI (terra-6.1), check if UM GenAI hosts terra/gpt first!
        if mode == "openai":
            if alive:
                return cls._build_um_client(getattr(settings, "OPENAI_MODEL", "gpt-6.1-terra"))
            if settings.DEEPSEEK_API_KEY:
                return cls._build_deepseek_client()

        if mode == "deepseek" and settings.DEEPSEEK_API_KEY:
            return cls._build_deepseek_client()

        if mode == "ollama":
            http_client = httpx.AsyncClient(timeout=35.0, trust_env=False)
            client = AsyncOpenAI(
                base_url=settings.OLLAMA_BASE_URL,
                api_key="ollama",
                http_client=http_client,
            )
            return client, settings.OLLAMA_MODEL, "local_ollama"

        if alive and mode in ("hybrid_um_first", "open_webui"):
            raw_target = (
                settings.OPEN_WEBUI_FAST_MODEL if task == "fast"
                else settings.OPEN_WEBUI_OCR_MODEL if task == "vision"
                else settings.OPEN_WEBUI_TEXT_MODEL
            )
            return cls._build_um_client(raw_target)

        if settings.DEEPSEEK_API_KEY:
            return cls._build_deepseek_client()

        http_client = httpx.AsyncClient(timeout=35.0, trust_env=False)
        client = AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL,
            api_key="ollama",
            http_client=http_client,
        )
        return client, settings.OLLAMA_MODEL, "local_ollama"

    @classmethod
    async def chat(
        cls,
        messages: list[dict],
        task: str = "reasoning",
        temperature: float = 0.2,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> dict:
        client, model, provider = await cls.get_client_and_model(task=task)
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode and provider == "deepseek_api":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await client.chat.completions.create(**kwargs)
            return {
                "content": resp.choices[0].message.content,
                "provider_used": provider,
                "model_used": model,
            }
        except Exception as first_err:
            # Instant 1-hop fallback to Direct DeepSeek API
            if settings.DEEPSEEK_API_KEY and provider != "deepseek_api":
                ds_client, ds_model, _ = cls._build_deepseek_client()
                kwargs["model"] = ds_model
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = await ds_client.chat.completions.create(**kwargs)
                return {
                    "content": resp.choices[0].message.content,
                    "provider_used": "deepseek_api",
                    "model_used": ds_model,
                }
            raise first_err
