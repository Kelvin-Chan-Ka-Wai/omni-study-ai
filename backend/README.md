# Backend

FastAPI API for selected-source study generation, assessments, wrong-question practice, note versions, cancelable jobs, PDF export and study backup/restore.

Run from the root using `python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000`. Call `/api/session` before authenticated API requests. The frontend does this automatically. `/api/health` reads cached status and does not initiate campus login.

`OMNISTUDY_STORAGE_DIR` selects a separate runtime directory for tests. The default remains `backend/storage`. Never commit its contents. The existing provider and credential configuration is preserved.

Use `python -m pytest backend/tests -q` for isolated regression checks. Install Chromium with `python -m playwright install chromium` for real PDF generation. The job runner supports one backend process.
