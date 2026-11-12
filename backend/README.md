# Backend

FastAPI service for slide ingestion, scoped study generation, assessments, voice tutoring, exports, and local SQLite history.

Run from the repository root:

```bash
python -m uvicorn main:app --app-dir backend --reload --port 8000
```

Keep runtime files under `backend/storage/`; they are intentionally excluded from the published source.
