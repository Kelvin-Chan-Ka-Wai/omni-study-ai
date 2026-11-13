import asyncio
from datetime import timezone
import shutil
from pathlib import Path
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import STORAGE_DIR, get_db
from models import Chapter, ChapterSection, ExamSession, WrongQuestionBank, NoteVersion, SlideTranscription
from services.scope import selected_sections, page_numbers
import uuid
from services.slide_scope_rag import SlideScopeRAG

router = APIRouter(prefix="/api/chapters", tags=["Chapters, Slide Scope & Testbank Ingestion"])

UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


def store_upload(upload, prefix):
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in (".pdf", ".pptx", ".md", ".txt"):
        raise HTTPException(400, "Choose a PDF, PPTX, Markdown or text document")
    path = UPLOAD_DIR / f"{prefix}_{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with path.open("wb") as output:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES: raise HTTPException(413, "Documents must be smaller than 50 MB")
                output.write(chunk)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class RegenerateNotesRequest(BaseModel):
    section_ids: list[int] | None = None
    all_sections: bool = False


def _resolve_local_storage_path(url_path: str | None) -> Path | None:
    if not url_path:
        return None
    clean = url_path.replace("/storage/", "", 1).lstrip("/")
    candidate = (STORAGE_DIR / clean).resolve()
    return candidate if candidate.is_relative_to(STORAGE_DIR) and candidate.is_file() else None


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
                for s in ch.sections
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
async def onboard_chapter_with_files(
    course_name: str = Form(...),
    chapter_title: str = Form(...),
    slide_file: UploadFile = File(..., description="Priority PPTX/PDF/MD lecture slides"),
    textbook_file: UploadFile | None = File(None, description="Optional textbook PDF/MD"),
    testbank_file: UploadFile | None = File(None, description="Optional course testbank / past paper PDF/PPTX/MD"),
    db: Session = Depends(get_db),
):
    slide_dest = store_upload(slide_file, "slides")

    tb_dest_str = None
    tb_chunks = []
    if textbook_file and textbook_file.filename:
        tb_dest = store_upload(textbook_file, "textbook")
        tb_dest_str = f"/storage/uploads/{tb_dest.name}"
        tb_chunks = SlideScopeRAG.extract_textbook_chunks(tb_dest)

    testbank_dest_str = None
    if testbank_file and testbank_file.filename:
        testbank_dest = store_upload(testbank_file, "testbank")
        testbank_dest_str = f"/storage/uploads/{testbank_dest.name}"

    slides_data = SlideScopeRAG.extract_slides_text(slide_dest)
    mapped_sections = await SlideScopeRAG.map_slide_sections(
        course_name=course_name,
        chapter_title=chapter_title,
        slides_data=slides_data,
        textbook_chunks=tb_chunks,
    )

    chapter = Chapter(
        course_name=course_name,
        chapter_title=chapter_title,
        slide_file_path=f"/storage/uploads/{slide_dest.name}",
        textbook_file_path=tb_dest_str,
        testbank_file_path=testbank_dest_str,
        progress_percentage=0.0,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)

    created_sections = []
    for sec in mapped_sections:
        notes = SlideScopeRAG.sanitize_markdown_latex_notes(sec.get("extracted_study_notes", ""))
        db_sec = ChapterSection(
            chapter_id=chapter.id,
            section_code=sec.get("section_code", "Sec"),
            section_title=sec.get("section_title", "Slide Section"),
            slide_pages=sec.get("slide_pages", "Slides"),
            extracted_study_notes=notes,
        )
        db.add(db_sec)
        created_sections.append(db_sec)

    db.commit()
    for s in created_sections:
        db.refresh(s)

    return {
        "chapter_id": chapter.id,
        "course_name": chapter.course_name,
        "chapter_title": chapter.chapter_title,
        "slide_url": chapter.slide_file_path,
        "testbank_url": chapter.testbank_file_path,
        "total_slides_parsed": len(slides_data),
        "sections": [
            {
                "id": s.id,
                "section_code": s.section_code,
                "section_title": s.section_title,
                "slide_pages": s.slide_pages,
                "extracted_study_notes": s.extracted_study_notes,
                "best_accuracy": s.best_accuracy,
                "is_mastered": s.is_mastered,
            }
            for s in created_sections
        ],
    }


@router.post("/{chapter_id}/upload-testbank")
async def attach_testbank_to_existing_chapter(
    chapter_id: int,
    testbank_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    testbank_dest = store_upload(testbank_file, f"testbank_ch{chapter_id}")

    chapter.testbank_file_path = f"/storage/uploads/{testbank_dest.name}"
    db.commit()
    return {
        "chapter_id": chapter.id,
        "testbank_file_path": chapter.testbank_file_path,
    }


@router.post("/{chapter_id}/regenerate-notes")
async def regenerate_structured_study_notes(
    chapter_id: int,
    payload: RegenerateNotesRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """
    Fast Per-Section Parallel Note Regenerator:
    - If payload.section_ids is provided, ONLY regenerates those ticked sections in parallel.
    - If payload.section_ids is None/empty, regenerates ALL sections in parallel.
    - Each section runs in its own parallel worker (<15s per section) using raw Markdown + LaTeX.
    """
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    all_sections = (
        db.query(ChapterSection)
        .filter(ChapterSection.chapter_id == chapter.id)
        .order_by(ChapterSection.id.asc())
        .all()
    )
    if not all_sections:
        raise HTTPException(status_code=400, detail="No sections found in chapter")

    target_sections = selected_sections(db, chapter_id, payload.section_ids if payload else None, payload.all_sections if payload else False)

    slide_disk_path = _resolve_local_storage_path(chapter.slide_file_path)
    slides_data = (
        SlideScopeRAG.extract_slides_text(slide_disk_path)
        if slide_disk_path
        else []
    )
    overrides = {row.page: row.text for row in db.query(SlideTranscription).filter_by(chapter_id=chapter_id)}
    slides_data = [{**slide, "text": overrides.get(slide["slide_number"], slide["text"])} for slide in slides_data]
    tb_disk_path = _resolve_local_storage_path(chapter.textbook_file_path)
    tb_chunks = (
        SlideScopeRAG.extract_textbook_chunks(tb_disk_path)
        if tb_disk_path
        else []
    )

    async def _regen_one(sec: ChapterSection) -> tuple[int, str]:
        if slides_data:
            sec_slide_text = SlideScopeRAG._filter_slides_for_page_range(
                slides_data, sec.slide_pages
            )
        else:
            raise HTTPException(400, "Source slides are missing; upload them before regenerating.")

        tb_excerpt = ""
        if tb_chunks:
            tb_excerpt = SlideScopeRAG.filter_textbook_for_slide_section(
                sec.section_title, sec_slide_text[:3000], tb_chunks, top_k=2
            )

        clean_md = await SlideScopeRAG.generate_single_section_note_fast(
            course_name=chapter.course_name,
            chapter_title=chapter.chapter_title,
            section_code=sec.section_code,
            section_title=sec.section_title,
            slide_pages=sec.slide_pages,
            section_slides_text=sec_slide_text,
            textbook_excerpt=tb_excerpt,
        )
        return sec.id, clean_md

    gate = asyncio.Semaphore(3)
    async def limited(sec):
        async with gate: return await _regen_one(sec)
    tasks = [asyncio.create_task(limited(sec)) for sec in target_sections]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    notes_by_id = dict(results)

    for sec in target_sections:
        if sec.id in notes_by_id and notes_by_id[sec.id]:
            db.add(NoteVersion(section_id=sec.id, content=sec.extracted_study_notes or "", reason="regenerate"))
            sec.extracted_study_notes = notes_by_id[sec.id]

    db.commit()
    return {
        "status": "upgraded",
        "chapter_id": chapter.id,
        "regenerated_section_ids": list(notes_by_id.keys()),
        "regenerated_count": len(notes_by_id),
    }


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

    return {
        "id": chapter.id,
        "course_name": chapter.course_name,
        "chapter_title": chapter.chapter_title,
        "slide_file_path": chapter.slide_file_path,
        "textbook_file_path": chapter.textbook_file_path,
        "testbank_file_path": getattr(chapter, "testbank_file_path", None),
        "progress_percentage": chapter.progress_percentage,
        "sections": [
            {
                "id": s.id,
                "section_code": s.section_code,
                "section_title": s.section_title,
                "slide_pages": s.slide_pages,
                "extracted_study_notes": SlideScopeRAG.sanitize_markdown_latex_notes(
                    s.extracted_study_notes or ""
                ),
                "best_accuracy": s.best_accuracy,
                "latest_accuracy": s.latest_accuracy,
                "quiz_attempts": s.quiz_attempts,
                "is_mastered": s.is_mastered,
            }
            for s in chapter.sections
        ],
        "study_history": [
            {
                "session_id": h.id,
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


@router.get("/{chapter_id}/sections/{section_id}/versions")
def list_note_versions(chapter_id: int, section_id: int, db: Session = Depends(get_db)):
    selected_sections(db, chapter_id, [section_id])
    return [{"id": v.id, "reason": v.reason, "created_at": v.created_at.replace(tzinfo=timezone.utc)} for v in db.query(NoteVersion).filter_by(section_id=section_id).order_by(NoteVersion.id.desc()).limit(30)]


@router.post("/{chapter_id}/sections/{section_id}/restore/{version_id}")
def restore_note_version(chapter_id: int, section_id: int, version_id: int, db: Session = Depends(get_db)):
    sec = selected_sections(db, chapter_id, [section_id])[0]
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
    section = selected_sections(db, chapter_id, [section_id])[0]
    chapter = db.get(Chapter, chapter_id)
    pages = page_numbers(section.slide_pages)
    return {"pages": pages, "file_url": chapter.slide_file_path, "citations": [{"page": p, "url": f"{chapter.slide_file_path}#page={p}"} for p in pages]}


@router.put("/{chapter_id}/transcription")
def save_slide_transcription(chapter_id: int, req: TranscriptionRequest, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter: raise HTTPException(404, "Chapter not found")
    path = _resolve_local_storage_path(chapter.slide_file_path)
    slides = SlideScopeRAG.extract_slides_text(path) if path else []
    if req.page not in {s["slide_number"] for s in slides} or not req.text.strip():
        raise HTTPException(400, "Choose a valid page and enter a verified transcription.")
    row = db.query(SlideTranscription).filter_by(chapter_id=chapter_id, page=req.page).first()
    if row: row.text = req.text.strip()
    else: db.add(SlideTranscription(chapter_id=chapter_id, page=req.page, text=req.text.strip()))
    db.commit()
    return {"saved": True, "page": req.page}
