import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from database import STORAGE_DIR, get_db
from models import Chapter, ChapterSection, ExamSession, WrongQuestionBank
from services.slide_scope_rag import SlideScopeRAG

router = APIRouter(prefix="/api/chapters", tags=["Chapters, Slide Scope & Testbank Ingestion"])

UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_local_storage_path(url_path: str | None) -> Path | None:
    if not url_path:
        return None
    clean = url_path.replace("/storage/", "", 1).lstrip("/")
    candidate = STORAGE_DIR / clean
    return candidate if candidate.exists() else None


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
    """Deletes a studied chapter and all associated sections, exam history, and wrong questions."""
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
    slide_dest = UPLOAD_DIR / f"slides_{slide_file.filename}"
    with slide_dest.open("wb") as f:
        shutil.copyfileobj(slide_file.file, f)

    tb_dest_str = None
    tb_chunks = []
    if textbook_file and textbook_file.filename:
        tb_dest = UPLOAD_DIR / f"textbook_{textbook_file.filename}"
        with tb_dest.open("wb") as f:
            shutil.copyfileobj(textbook_file.file, f)
        tb_dest_str = f"/storage/uploads/{tb_dest.name}"
        tb_chunks = SlideScopeRAG.extract_textbook_chunks(tb_dest)

    testbank_dest_str = None
    if testbank_file and testbank_file.filename:
        testbank_dest = UPLOAD_DIR / f"testbank_{testbank_file.filename}"
        with testbank_dest.open("wb") as f:
            shutil.copyfileobj(testbank_file.file, f)
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

    testbank_dest = UPLOAD_DIR / f"testbank_ch{chapter_id}_{testbank_file.filename}"
    with testbank_dest.open("wb") as f:
        shutil.copyfileobj(testbank_file.file, f)

    chapter.testbank_file_path = f"/storage/uploads/{testbank_dest.name}"
    db.commit()
    return {
        "chapter_id": chapter.id,
        "testbank_file_path": chapter.testbank_file_path,
    }


@router.post("/{chapter_id}/regenerate-notes")
async def regenerate_structured_study_notes(
    chapter_id: int,
    db: Session = Depends(get_db),
):
    """Rebuilds study notes into clean 4-part Markdown + LaTeX and strips any raw PDF textbook artifacts."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    slide_disk_path = _resolve_local_storage_path(chapter.slide_file_path)
    if slide_disk_path:
        slides_data = SlideScopeRAG.extract_slides_text(slide_disk_path)
        tb_disk_path = _resolve_local_storage_path(chapter.textbook_file_path)
        tb_chunks = SlideScopeRAG.extract_textbook_chunks(tb_disk_path) if tb_disk_path else []
    else:
        slides_data = [
            {
                "slide_number": idx,
                "text": f"{s.section_code}: {s.section_title} ({s.slide_pages})\n"
                + SlideScopeRAG._sanitize_pdf_extracted_text(
                    (s.extracted_study_notes or "").split("[Textbook Context")[0]
                ),
            }
            for idx, s in enumerate(chapter.sections, start=1)
        ]
        tb_chunks = []

    mapped = await SlideScopeRAG.map_slide_sections(
        course_name=chapter.course_name,
        chapter_title=chapter.chapter_title,
        slides_data=slides_data,
        textbook_chunks=tb_chunks,
    )

    existing_sections = db.query(ChapterSection).filter(ChapterSection.chapter_id == chapter.id).all()
    for idx, sec_data in enumerate(mapped):
        notes = SlideScopeRAG.sanitize_markdown_latex_notes(sec_data.get("extracted_study_notes", ""))
        if idx < len(existing_sections):
            existing_sections[idx].section_code = sec_data.get("section_code", existing_sections[idx].section_code)
            existing_sections[idx].section_title = sec_data.get("section_title", existing_sections[idx].section_title)
            existing_sections[idx].slide_pages = sec_data.get("slide_pages", existing_sections[idx].slide_pages)
            existing_sections[idx].extracted_study_notes = notes
        else:
            db.add(
                ChapterSection(
                    chapter_id=chapter.id,
                    section_code=sec_data.get("section_code", f"Sec {idx+1}"),
                    section_title=sec_data.get("section_title", "Slide Section"),
                    slide_pages=sec_data.get("slide_pages", "Slides"),
                    extracted_study_notes=notes,
                )
            )

    db.commit()
    return {"status": "upgraded", "chapter_id": chapter.id}


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
                "extracted_study_notes": s.extracted_study_notes,
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
