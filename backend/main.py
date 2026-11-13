import os
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
from routers import jobs, backup
from security import LocalAccessMiddleware, ALLOWED_ORIGINS

FRONTEND_DIST = Path(os.environ.get("OMNISTUDY_FRONTEND_DIST", Path(__file__).resolve().parent.parent / "frontend" / "dist"))


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
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LocalAccessMiddleware)
# Never mount the database, credential backups or persistent browser profile.
for folder in ("uploads", "handwritten_snaps"):
    directory = STORAGE_DIR / folder
    directory.mkdir(exist_ok=True)
    app.mount(f"/storage/{folder}", StaticFiles(directory=str(directory), follow_symlink=False), name=folder)

app.include_router(backup.router)
app.include_router(jobs.router)
app.include_router(ingestion.router)
app.include_router(assessment.router)
app.include_router(wrong_bank.router)
app.include_router(export.router)
app.include_router(voice.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health_check():
    um_alive, reason = HybridLLMHarness._last_alive_state, HybridLLMHarness._last_reason
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
        candidate = (FRONTEND_DIST / full_path).resolve()
        if not candidate.is_relative_to(FRONTEND_DIST.resolve()) or full_path.startswith(("api/", "storage/")):
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
