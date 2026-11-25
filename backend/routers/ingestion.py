import asyncio
import json
from collections import defaultdict
from contextlib import ExitStack
from datetime import timezone
from pathlib import Path
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import STORAGE_DIR, get_db
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, PaperSectionSnapshot, WrongQuestionBank, NoteVersion, SlideTranscription, GenerationJob
from services.documents import DOCUMENT_SUFFIXES, VISUAL_ONLY, DocumentReadError, read_pages, resolve_local_upload
from services.scope import selected_sections, page_numbers, section_order
from services.slide_outline import build_outline, format_slide_pages, review_slides
import uuid
from services.slide_scope_rag import SlideScopeRAG
from services.learning_sources import textbook_index
from services import generation_pacing as pacing

router = APIRouter(prefix="/api/chapters", tags=["Chapters, Slide Scope & Testbank Ingestion"])

UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


MIB = 1024 * 1024
MAX_DOCUMENT_BYTES = 50 * MIB
MAX_TEXTBOOK_BYTES = 200 * MIB


def store_upload(upload: UploadFile, prefix: str, label: str, *, max_bytes: int) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in DOCUMENT_SUFFIXES:
        raise HTTPException(400, f"{label}: choose a PDF, PPTX, Markdown or text document.")
    path = UPLOAD_DIR / f"{prefix}_{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with path.open("wb") as output:
            while chunk := upload.file.read(MIB):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"{label}: documents must be at most {max_bytes / MIB:g} MB.")
                output.write(chunk)
        if not size:
            raise HTTPException(422, f"{label}: the file is empty. Choose a file with content.")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class RegenerateNotesRequest(BaseModel):
    section_ids: list[int] | None = None
    all_sections: bool = False


def _stage_document(cleanup: ExitStack, upload: UploadFile, prefix: str, label: str, *, max_bytes: int) -> Path:
    path = store_upload(upload, prefix, label, max_bytes=max_bytes)
    cleanup.callback(path.unlink, missing_ok=True)
    return path


def _reference_has_text(path: Path, label: str) -> bool:
    try:
        if label == "Textbook":
            return bool(textbook_index(path).entries)
        found_page = found_text = False
        for page in read_pages(path):
            found_page = True
            found_text |= bool(page)
        if not found_page:
            raise DocumentReadError("The document is empty. Choose a file with content.")
        return found_text
    except DocumentReadError as exc:
        raise HTTPException(422, f"{label}: {exc}") from exc


@router.get("")
def list_chapters(db: Session = Depends(get_db)):
    chapters = db.query(Chapter).order_by(Chapter.created_at.desc()).all()
    result = []
    for ch in chapters:
        active_wrong = (
            db.query(WrongQuestionBank)
            .filter(WrongQuestionBank.chapter_id == ch.id, WrongQuestionBank.status == "active")
            .count()
        )
        result.append({
            "id": ch.id,
            "course_name": ch.course_name,
            "chapter_title": ch.chapter_title,
            "slide_file_path": ch.slide_file_path,
            "textbook_file_path": ch.textbook_file_path,
            "testbank_file_path": getattr(ch, "testbank_file_path", None),
            "progress_percentage": ch.progress_percentage,
            "active_wrong_count": active_wrong,
            "created_at": ch.created_at,
            "sections": [
                {
                    "id": s.id,
                    "section_code": s.section_code,
                    "section_title": s.section_title,
                    "slide_pages": s.slide_pages,
                    "best_accuracy": s.best_accuracy,
                    "latest_accuracy": s.latest_accuracy,
                    "quiz_attempts": s.quiz_attempts,
                    "is_mastered": s.is_mastered,
                }
                for s in sorted(ch.sections, key=section_order) if not s.is_archived
            ],
        })
    return result


@router.delete("/{chapter_id}")
def delete_chapter(chapter_id: int, db: Session = Depends(get_db)):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    db.delete(chapter)
    db.commit()
    return {"deleted": True, "chapter_id": chapter_id}


@router.post("/onboard")
def onboard_chapter_with_files(
    course_name: str = Form(...),
    chapter_title: str = Form(...),
    slide_file: UploadFile = File(..., description="Lecture slides or notes: PDF, PPTX, Markdown or text"),
    textbook_file: UploadFile | None = File(None),
    testbank_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    course_name, chapter_title = course_name.strip(), chapter_title.strip()
    if not course_name or not chapter_title:
        raise HTTPException(422, "Enter both the course name and chapter title.")

    # Keep the upload and its chapter/sections together on every handled failure.
    with ExitStack() as cleanup:
        slide_dest = _stage_document(cleanup, slide_file, "slides", "Lecture slides", max_bytes=MAX_DOCUMENT_BYTES)
        try:
            slides_data = SlideScopeRAG.extract_slides_text(slide_dest)
            if not slides_data:
                raise DocumentReadError("The document has no pages or text. Choose a file with content.")
        except DocumentReadError as exc:
            raise HTTPException(422, f"Lecture slides: {exc}") from exc

        warnings = []
        reviewed = review_slides(slides_data)
        outline = build_outline(reviewed)
        if not outline:
            raise HTTPException(422, "No study slides found. The file only contains opening, closing or other non-study pages.")
        omitted = [item["slide_number"] for item in reviewed if item["excluded_reason"]]
        if omitted:
            warnings.append(f"Excluded {format_slide_pages(omitted).lower()} as non-study material. See Review slide scope for details.")
        visual_pages = [item["slide_number"] for item in reviewed if item["text"] == VISUAL_ONLY]
        if visual_pages:
            warnings.append(f"{len(visual_pages)} slide page(s) have no readable text. Add a verified transcription in Study Tools before generating from those pages.")
        references = {}
        for upload, field, label, limit in (
            (textbook_file, "textbook", "Textbook", MAX_TEXTBOOK_BYTES),
            (testbank_file, "testbank", "Testbank", MAX_DOCUMENT_BYTES),
        ):
            if upload and upload.filename:
                path = _stage_document(cleanup, upload, field, label, max_bytes=limit)
                if not _reference_has_text(path, label):
                    warnings.append(f"{label} saved, but it has no readable text. It will not be used as an AI reference.")
                references[field] = f"/storage/uploads/{path.name}"

        chapter = Chapter(
            course_name=course_name,
            chapter_title=chapter_title,
            slide_file_path=f"/storage/uploads/{slide_dest.name}",
            textbook_file_path=references.get("textbook"),
            testbank_file_path=references.get("testbank"),
            progress_percentage=0.0,
            sections=[ChapterSection(**section, extracted_study_notes="")
                      for section in outline],
        )
        db.add(chapter)
        db.flush()
        result = {
            "chapter_id": chapter.id,
            "course_name": chapter.course_name,
            "chapter_title": chapter.chapter_title,
            "slide_url": chapter.slide_file_path,
            "testbank_url": chapter.testbank_file_path,
            "total_slides_parsed": len(slides_data),
            "warnings": warnings,
            "sections": [
                {"id": s.id, "section_code": s.section_code, "section_title": s.section_title,
                 "slide_pages": s.slide_pages, "extracted_study_notes": s.extracted_study_notes,
                 "best_accuracy": s.best_accuracy, "is_mastered": s.is_mastered}
                for s in chapter.sections
            ],
        }
        db.commit()
        cleanup.pop_all()
        return result


@router.post("/{chapter_id}/upload-testbank")
def attach_testbank_to_existing_chapter(
    chapter_id: int,
    testbank_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    with ExitStack() as cleanup:
        path = _stage_document(cleanup, testbank_file, f"testbank_ch{chapter_id}", "Testbank", max_bytes=MAX_DOCUMENT_BYTES)
        has_text = _reference_has_text(path, "Testbank")
        chapter.testbank_file_path = f"/storage/uploads/{path.name}"
        result = {
            "chapter_id": chapter.id,
            "testbank_file_path": chapter.testbank_file_path,
            "warnings": [] if has_text else ["Testbank saved, but it has no readable text. It will not be used as an AI reference."],
        }
        db.commit()
        cleanup.pop_all()
        return result


@router.post("/{chapter_id}/regenerate-notes")
async def regenerate_structured_study_notes(
    chapter_id: int,
    payload: RegenerateNotesRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """Regenerate only selected sections, unless all sections was requested explicitly."""
    deadline = asyncio.get_running_loop().time() + pacing.NOTE_AI_SECONDS
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    target_sections = selected_sections(db, chapter_id, payload.section_ids if payload else None, payload.all_sections if payload else False)
    slides_data = _review_chapter_source(db, chapter)
    tb_disk_path = resolve_local_upload(STORAGE_DIR, chapter.textbook_file_path)
    book = textbook_index(tb_disk_path) if tb_disk_path else None
    chapter_outline = ' → '.join(s.section_title for s in sorted(chapter.sections, key=section_order) if not s.is_archived)[:2500]

    gate = asyncio.Semaphore(pacing.NOTE_WORKERS)

    async def generate(sec):
        page_ref, evidence = SlideScopeRAG.scoped_slide_evidence(slides_data, sec.slide_pages)
        if len(evidence) > 24000:
            raise ValueError("Section is too large; divide it into smaller page ranges.")
        excerpt = book.excerpt(sec.section_title, evidence) if book else ''
        # Includes the semaphore wait and any citation-repair request, not a new budget per section.
        timer = asyncio.timeout_at(deadline)
        try:
            async with timer, gate:
                note = await SlideScopeRAG.generate_single_section_note_fast(
                    course_name=chapter.course_name, chapter_title=chapter.chapter_title,
                    section_code=sec.section_code, section_title=sec.section_title, slide_pages=page_ref,
                    section_slides_text=evidence, textbook_excerpt=excerpt, chapter_outline=chapter_outline)
            if not note:
                raise ValueError("The AI provider returned no notes. Your saved notes are unchanged.")
            return sec, note, 'lesson'
        except TimeoutError:
            if not timer.expired():
                raise
            if (sec.extracted_study_notes or '').strip():
                return sec, None, 'kept'
            guide = pacing.source_reading_guide(sec.section_title, evidence, excerpt)
            return sec, SlideScopeRAG.sanitize_markdown_latex_notes(guide), 'guide'

    with pacing.generation_batch():
        tasks = [asyncio.create_task(generate(sec)) for sec in target_sections]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    updated, guides, kept = [], [], []
    for sec, note, kind in results:
        if kind == 'kept':
            kept.append(sec.id)
            continue
        db.add(NoteVersion(section_id=sec.id, content=sec.extracted_study_notes or "", reason="regenerate"))
        sec.extracted_study_notes = note
        updated.append(sec.id)
        if kind == 'guide':
            guides.append(sec.id)
    db.commit()
    return {"status": "upgraded", "chapter_id": chapter_id, "regenerated_section_ids": updated,
            "regenerated_count": len(updated), "source_guide_section_ids": guides, "kept_section_ids": kept}



@router.post("/{chapter_id}/clear-notes")
def clear_study_notes(
    chapter_id: int,
    payload: RegenerateNotesRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """Archives and clears notes for an explicit selection."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    sections = selected_sections(db, chapter_id, payload.section_ids if payload else None, payload.all_sections if payload else False)
    cleared_ids = []
    for sec in sections:
        db.add(NoteVersion(section_id=sec.id, content=sec.extracted_study_notes or "", reason="clear"))
        sec.extracted_study_notes = ""
        cleared_ids.append(sec.id)

    db.commit()
    return {"status": "cleared", "chapter_id": chapter_id, "cleared_section_ids": cleared_ids}


def _history_sections(db, chapter, history):
    """Reconstruct older papers without rewriting them; newer papers keep their original labels."""
    current = {s.id: {k: getattr(s, k) for k in ("id", "section_code", "section_title", "slide_pages")}
               for s in sorted(chapter.sections, key=section_order)}
    snapshots = dict(db.query(PaperSectionSnapshot.session_id, PaperSectionSnapshot.sections_json)
                     .join(ExamSession, ExamSession.id == PaperSectionSnapshot.session_id)
                     .filter(ExamSession.chapter_id == chapter.id).all())
    def has_answer(value):
        if isinstance(value, list):
            return any(has_answer(v) for v in value)
        return isinstance(value, str) and value.strip().casefold() not in ('', '[]', '(no answer submitted)')

    drafts = {h.id: {a['question_id'] for a in json.loads(h.draft_json or '[]')
                     if has_answer(a.get('user_answer')) or has_answer(a.get('corrected_transcription'))} for h in history}
    counts = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    rows = (db.query(QuestionRecord.session_id, QuestionRecord.section_id, QuestionRecord.id,
                     QuestionRecord.user_answer, QuestionRecord.handwritten_image_path.is_not(None))
            .join(ExamSession).filter(ExamSession.chapter_id == chapter.id))
    for session, sid, qid, answer, uploaded in rows:
        pair = counts[session][sid]
        pair[0] += 1
        pair[1] += int(uploaded or qid in drafts[session] or has_answer(answer))
    result = {}
    for h in history:
        meta = current.copy()
        meta.update({s['id']: s for s in json.loads(snapshots.get(h.id, '[]'))})
        selected = json.loads(h.selected_section_ids_json or '[]')
        linked = counts[h.id]
        ordered = dict.fromkeys([*selected, *(sid for sid in meta if sid in linked), *linked])
        result[h.id] = []
        for sid in ordered:
            count, answered = counts[h.id].get(sid, (0, 0))
            section = meta.get(sid, {'id': sid, 'section_code': None, 'section_title': None, 'slide_pages': None})
            result[h.id].append({**section, 'question_count': count, 'answered_count': answered})
    return result


@router.get("/{chapter_id}")
def get_chapter_detail(chapter_id: int, db: Session = Depends(get_db)):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    history = (
        db.query(ExamSession)
        .filter(ExamSession.chapter_id == chapter_id)
        .order_by(ExamSession.started_at.desc())
        .all()
    )

    history_sections = _history_sections(db, chapter, history) if history else {}
    archived_ids = [s.id for s in chapter.sections if s.is_archived]
    archived_with_history = {row[0] for row in db.query(NoteVersion.section_id).filter(
        NoteVersion.section_id.in_(archived_ids)).distinct()} if archived_ids else set()

    def section_data(s):
        return {
            "id": s.id,
            "section_code": s.section_code,
            "section_title": s.section_title,
            "slide_pages": s.slide_pages,
            "extracted_study_notes": SlideScopeRAG.sanitize_markdown_latex_notes(s.extracted_study_notes or ""),
            "best_accuracy": s.best_accuracy,
            "latest_accuracy": s.latest_accuracy,
            "quiz_attempts": s.quiz_attempts,
            "is_mastered": s.is_mastered,
        }

    return {
        "id": chapter.id,
        "course_name": chapter.course_name,
        "chapter_title": chapter.chapter_title,
        "slide_file_path": chapter.slide_file_path,
        "textbook_file_path": chapter.textbook_file_path,
        "testbank_file_path": getattr(chapter, "testbank_file_path", None),
        "progress_percentage": chapter.progress_percentage,
        "sections": [section_data(s) for s in sorted(chapter.sections, key=section_order) if not s.is_archived],
        "archived_sections": [section_data(s) for s in sorted(chapter.sections, key=lambda s: s.id)
                              if s.is_archived and (s.extracted_study_notes or s.quiz_attempts or s.id in archived_with_history)],
        "study_history": [
            {
                "session_id": h.id,
                "sections": history_sections[h.id],
                "mode": h.mode,
                "status": h.status,
                "total_score": h.total_score,
                "max_score": h.max_score,
                "accuracy_percent": round(h.accuracy * 100, 1),
                "time_spent_seconds": h.time_spent_seconds,
                "started_at": h.started_at,
                "completed_at": h.completed_at,
            }
            for h in history
        ],
    }


def _review_chapter_source(db: Session, chapter: Chapter):
    path = resolve_local_upload(STORAGE_DIR, chapter.slide_file_path)
    if not path:
        raise HTTPException(400, "Source slides are missing. Upload the lecture again.")
    slides = SlideScopeRAG.extract_slides_text(path)
    overrides = {row.page: row.text for row in db.query(SlideTranscription).filter_by(chapter_id=chapter.id)}
    return review_slides([{**slide, "text": overrides.get(slide["slide_number"], slide["text"]),
                          "verified": slide["slide_number"] in overrides} for slide in slides])


def _outline_preview(db, chapter_id):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    reviewed = _review_chapter_source(db, chapter)
    outline = build_outline(reviewed)
    active = sorted((s for s in chapter.sections if not s.is_archived), key=section_order)
    current = [{key: getattr(s, key) for key in ("section_code", "section_title", "slide_pages")} for s in active]
    return chapter, active, {
        "sections": outline,
        "excluded": [{"page": p["slide_number"], "title": p["title"], "reason": p["excluded_reason"]}
                     for p in reviewed if p["excluded_reason"]],
        "visual_pages": [p["slide_number"] for p in reviewed if p["text"] == VISUAL_ONLY],
        "file_url": chapter.slide_file_path,
        "can_apply": bool(outline and outline != current),
    }


@router.get("/{chapter_id}/slide-outline")
def get_slide_outline(chapter_id: int, db: Session = Depends(get_db)):
    return _outline_preview(db, chapter_id)[2]


@router.post("/{chapter_id}/slide-outline")
def apply_slide_outline(chapter_id: int, db: Session = Depends(get_db)):
    chapter, active, preview = _outline_preview(db, chapter_id)
    if not preview["can_apply"]:
        return preview
    if db.query(GenerationJob).filter(GenerationJob.chapter_id == chapter_id,
                                      GenerationJob.status.in_(("running", "queued"))).first():
        raise HTTPException(409, "Finish or cancel generation before updating the slide scope.")
    active_by_pages = {tuple(page_numbers(s.slide_pages)): s for s in active if s.slide_pages}
    for s in active:
        s.is_archived = True
    kept = []
    for item in preview["sections"]:
        existing = active_by_pages.pop(tuple(page_numbers(item["slide_pages"])), None)
        if existing is None:
            existing = ChapterSection(chapter_id=chapter_id, **item, extracted_study_notes="")
            db.add(existing)
        else:
            existing.is_archived = False
            existing.section_code = item["section_code"]
            existing.section_title = item["section_title"]
            existing.slide_pages = item["slide_pages"]
        kept.append(existing)
    chapter.progress_percentage = round(100 * sum(bool(s.is_mastered) for s in kept) / len(kept), 1)
    db.commit()
    return {**preview, "can_apply": False}


@router.get("/{chapter_id}/sections/{section_id}/versions")
def list_note_versions(chapter_id: int, section_id: int, db: Session = Depends(get_db)):
    selected_sections(db, chapter_id, [section_id], include_archived=True)
    return [{"id": v.id, "reason": v.reason, "created_at": v.created_at.replace(tzinfo=timezone.utc)} for v in db.query(NoteVersion).filter_by(section_id=section_id).order_by(NoteVersion.id.desc()).limit(30)]


@router.post("/{chapter_id}/sections/{section_id}/restore/{version_id}")
def restore_note_version(chapter_id: int, section_id: int, version_id: int, db: Session = Depends(get_db)):
    sec = selected_sections(db, chapter_id, [section_id], include_archived=True)[0]
    version = db.query(NoteVersion).filter_by(id=version_id, section_id=section_id).first()
    if not version: raise HTTPException(404, "Note version not found")
    db.add(NoteVersion(section_id=sec.id, content=sec.extracted_study_notes or "", reason="restore"))
    sec.extracted_study_notes = version.content
    db.commit()
    return {"restored": True}


class TranscriptionRequest(BaseModel):
    page: int
    text: str


@router.get("/{chapter_id}/sections/{section_id}/sources")
def get_section_sources(chapter_id: int, section_id: int, db: Session = Depends(get_db)):
    section = selected_sections(db, chapter_id, [section_id], include_archived=True)[0]
    chapter = db.get(Chapter, chapter_id)
    pages = page_numbers(section.slide_pages)
    return {"pages": pages, "file_url": chapter.slide_file_path, "citations": [{"page": p, "url": f"{chapter.slide_file_path}#page={p}"} for p in pages]}


@router.put("/{chapter_id}/transcription")
def save_slide_transcription(chapter_id: int, req: TranscriptionRequest, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter: raise HTTPException(404, "Chapter not found")
    path = resolve_local_upload(STORAGE_DIR, chapter.slide_file_path)
    slides = SlideScopeRAG.extract_slides_text(path) if path else []
    if req.page not in {s["slide_number"] for s in slides} or not req.text.strip():
        raise HTTPException(400, "Choose a valid page and enter a verified transcription.")
    row = db.query(SlideTranscription).filter_by(chapter_id=chapter_id, page=req.page).first()
    if row: row.text = req.text.strip()
    else: db.add(SlideTranscription(chapter_id=chapter_id, page=req.page, text=req.text.strip()))
    db.commit()
    return {"saved": True, "page": req.page}
