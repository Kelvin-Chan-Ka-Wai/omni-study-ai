from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, WrongQuestionBank
from services.latex_exporter import AcademicExporter

router = APIRouter(prefix="/api/export", tags=["One-Click PDF, Markdown & LaTeX Export"])


@router.get("/chapter/{chapter_id}")
def export_chapter_notes(
    chapter_id: int,
    fmt: str = Query("md", pattern="^(md|tex|pdf)$"),
    db: Session = Depends(get_db),
):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    sections = db.query(ChapterSection).filter(ChapterSection.chapter_id == chapter_id).all()
    content = AcademicExporter.export_chapter_study_guide(chapter, sections, fmt=fmt)
    if fmt == "pdf":
        return HTMLResponse(content=content)
    ext = "tex" if fmt == "tex" else "md"
    headers = {"Content-Disposition": f'attachment; filename="chapter_{chapter_id}_notes.{ext}"'}
    return PlainTextResponse(content=content, headers=headers)


@router.get("/exam/{session_id}")
def export_exam_paper(
    session_id: int,
    fmt: str = Query("md", pattern="^(md|tex|pdf)$"),
    include_solutions: bool = Query(True),
    db: Session = Depends(get_db),
):
    exam = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")
    chapter = db.query(Chapter).filter(Chapter.id == exam.chapter_id).first()
    questions = db.query(QuestionRecord).filter(QuestionRecord.session_id == session_id).all()
    content = AcademicExporter.export_exam_session(
        chapter, exam, questions, include_solutions=include_solutions, fmt=fmt
    )
    if fmt == "pdf":
        return HTMLResponse(content=content)
    ext = "tex" if fmt == "tex" else "md"
    headers = {"Content-Disposition": f'attachment; filename="exam_{session_id}.{ext}"'}
    return PlainTextResponse(content=content, headers=headers)


@router.get("/wrong-bank/{chapter_id}")
def export_wrong_bank_sheet(
    chapter_id: int,
    fmt: str = Query("md", pattern="^(md|tex|pdf)$"),
    db: Session = Depends(get_db),
):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    items = (
        db.query(WrongQuestionBank)
        .filter(WrongQuestionBank.chapter_id == chapter_id)
        .all()
    )
    content = AcademicExporter.export_wrong_question_bank(chapter, items, fmt=fmt)
    if fmt == "pdf":
        return HTMLResponse(content=content)
    ext = "tex" if fmt == "tex" else "md"
    headers = {"Content-Disposition": f'attachment; filename="wrong_bank_ch_{chapter_id}.{ext}"'}
    return PlainTextResponse(content=content, headers=headers)
