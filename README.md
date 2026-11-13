# OmniStudy AI

![OmniStudy AI](docs/assets/banner.svg)

**A local study workspace grounded in your selected lecture slides.**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
![React](https://img.shields.io/badge/React-18-61DAFB)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688)

Generate notes, practice questions, review mistakes, recover an assessment after refresh, and download academic PDFs. Existing API/provider settings and campus login remain configurable locally.

## What changed

- **Exact section scope:** empty or foreign selections are rejected; generation and export never silently expand to every section.
- **Source evidence:** assessments use source-slide text; exact page lists/ranges and source links replace neighboring-page guesses. Long lectures are mapped in bounded batches without silently dropping the end.
- **Note history:** selected regeneration and deletion save earlier versions, which can be restored. Clearing the view is separate from deleting notes.
- **Reliable wrong-question practice:** canonical response fields, five-option partial credit, preserved original mistakes and variants, review dates, and a due-only filter. A grader outage preserves the mastery streak.
- **Recoverable assessments:** local and backend draft saving, resume from History, backend deadlines, explicit practice pauses/photo grace, and repeat-safe grading.
- **Verified papers:** question counts, unique prompts, five options, answer keys, marks, source references, and totals are checked before a paper is saved. Failed batches do not create partial exams.
- **Cancelable generation:** durable job status, cancellation and useful errors. Previously saved notes remain intact when generation fails or is canceled.
- **Actual PDF downloads:** local Markdown/KaTeX rendering and Chromium printing produce PDF files without a CDN dependency.
- **Portable study data:** backup/restore includes the study database and uploaded material, never API credentials or browser sessions. Restore creates a recovery backup first.
- **Local access protection:** an HttpOnly session and origin checks protect API/storage access; only study-upload folders are served, not databases, logs or browser profiles.

## Start locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
npm --prefix frontend ci
cp .env.example .env  # only for a new checkout; never replace an existing .env
```

Fill credentials only in your own local `.env` or the existing Settings panel. Do not put real credentials into source code, screenshots, issues, or commits. No credentials are included in this repository.

```bash
# Terminal 1
source .venv/bin/activate
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000

# Terminal 2
npm --prefix frontend run dev -- --host 127.0.0.1
```

Open **http://127.0.0.1:5173**. Use the same hostname for frontend and backend so local session cookies work. For a single local origin, build with `npm --prefix frontend run build`, then open **http://127.0.0.1:8000** after starting the backend.

Existing users: restart the backend after updating. Additive database upgrades create a private recovery snapshot and retain existing study records. Existing credential/provider configuration and login code have not been migrated or rewritten.

## Layout

```text
backend/
  main.py                    # Local FastAPI app and access boundaries
  database.py, models.py     # SQLite, additive migrations and history
  routers/                   # Chapters, exams, practice, jobs, export, backup
  services/                  # Source scoping, scoring, existing provider routing
  assets/katex/              # Local formula renderer, fonts and upstream license
  tests/                     # Isolated regression checks; providers mocked
frontend/
  src/components/exam/       # Answers, handwriting, recoverable timer
  src/components/layout/     # Settings, note history, backup and recovery UI
  src/components/wrong-bank/ # Spaced practice
  src/services/api.ts        # Session setup and API contracts
  src/types/                 # Shared frontend types
  src/App.tsx                # Workspace coordination
docs/
  assets/banner.svg          # Project artwork
  RELEASE_NOTES.md           # Behavior changes and validation
.env.example                 # Empty credential template
requirements.txt             # Root dependency entrypoint
```

## Credentials and provider behavior

Configure only routes you use. The existing router supports campus GenAI, direct DeepSeek and Ollama according to its current settings. OpenAI settings are present in the existing app, but direct OpenAI fallback is not implemented by that router. A task name is not a guarantee of a model's reasoning effort; the existing integration passes no explicit reasoning-effort control.

**Credential handling and provider routing are intentionally preserved at the owner's request.** The existing local settings API can return configured values to the authenticated local interface, and campus login has its existing behavior. Keep the service on loopback; do not deploy it as a shared public server. API keys, UMPASS credentials, JWT/cookie tokens, `.env`, browser profiles, logs, backups and all user study data are excluded from Git.

## Study workflow

1. Upload lecture slides and optional textbook/testbank.
2. Select exact sections. Generate or regenerate only that selection.
3. Use **View supporting slides & note history** to verify sources or restore earlier notes.
4. For image-only material, add a verified page transcription in the study tools. Automatic diagram understanding is not guaranteed.
5. Open or resume an assessment. Answers autosave; the backend controls time. Practice pause is explicit.
6. Paste/upload handwriting. Use **Read handwriting into editable answer**, correct the text, then submit.
7. Review errors, generate twin questions, and use **Due for review only** for scheduled practice.
8. Download selected notes as PDF/Markdown/LaTeX, or create a private study backup.

## Verification

```bash
python -m pip install -r backend/requirements-dev.txt
python -m playwright install chromium
python -m pytest backend/tests -q
npm --prefix frontend run build
```

Tests use a temporary database and mocked model providers. The older demonstration scripts require an explicit disposable `OMNISTUDY_STORAGE_DIR`; AI integration demos can call your configured provider and incur charges.

## Practical limits

Scope citations and structural checks support review; they do not prove that an AI answer or grade is mathematically correct. Image-only pages need verified transcription. Very large selected sections are rejected instead of silently truncated. Running generation jobs are marked interrupted after a server restart and can be retried. One backend process is supported; do not run multiple workers against this local job runner. Provider credentials, network access, quotas and model availability still determine live AI success.

[Security](SECURITY.md) · [Backend guide](backend/README.md) · [Frontend guide](frontend/README.md)

No distribution license has been selected for the application. Bundled KaTeX retains its upstream license.
