from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config import settings
from database import STORAGE_DIR, init_db
from routers import assessment, export, ingestion, settings_router, voice, wrong_bank
from services.llm_harness import HybridLLMHarness

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="OmniStudy AI",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

app.include_router(ingestion.router)
app.include_router(assessment.router)
app.include_router(wrong_bank.router)
app.include_router(export.router)
app.include_router(voice.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health_check():
    um_alive, reason = await HybridLLMHarness.is_um_genai_alive()
    return {
        "status": "online",
        "active_provider_mode": settings.ACTIVE_LLM_PROVIDER,
        "um_genai_connected": um_alive,
        "um_genai_status": reason,
        "um_models": HybridLLMHarness._um_cached_models,
        "scope_mode": "slide_prioritized",
        "mcq_grading": "5_option_partial_credit",
        "graduation_streak": settings.WRONG_QUESTION_GRADUATION_STREAK,
        "mastery_threshold": settings.SECTION_MASTERY_THRESHOLD,
        "hands_free_voice": "enabled",
    }


# Serve production React build for the standalone macOS .app bundle
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
