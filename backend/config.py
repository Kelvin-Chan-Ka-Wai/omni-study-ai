from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env from project root regardless of current working directory
ROOT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=True)

class Settings(BaseSettings):
    ACTIVE_LLM_PROVIDER: str = "hybrid_um_first"

    OPEN_WEBUI_BASE_URL: str = "https://chat.genai.um.edu.mo/api"
    OPEN_WEBUI_API_KEY: str = ""
    UMPASS_USERNAME: str = ""
    UMPASS_PASSWORD: str = ""
    OPEN_WEBUI_TEXT_MODEL: str = "deepseek-v4.1-flash-1017"
    OPEN_WEBUI_FAST_MODEL: str = "GLM-Flash-5.3"
    OPEN_WEBUI_OCR_MODEL: str = "GLM-OCR"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_VISION_MODEL: str = "deepseek-v4.1-flash-1017"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-6.1-terra"

    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "qwen2.5:14b"

    VISION_PROVIDER: str = "hybrid_vision"
    USE_FREE_LOCAL_MATH_OCR: bool = True
    SECTION_MASTERY_THRESHOLD: float = 0.80
    WRONG_QUESTION_GRADUATION_STREAK: int = 3
    MIDTERM_FINAL_DURATION_MINUTES: int = 120
    PHOTO_UPLOAD_GRACE_MINUTES: int = 5

    model_config = SettingsConfigDict(env_file=str(ROOT_ENV_PATH), extra="ignore")

settings = Settings()
