from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, PlainTextResponse
from services.pdf_renderer import render_pdf
from services.scope import selected_sections
from sqlalchemy.orm import Session
from database import get_db
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, WrongQuestionBank
from services.latex_exporter import AcademicExporter

router = APIRouter(prefix="/api/export", tags=["One-Click PDF, Markdown & LaTeX Export"])


@router.get("/chapter/{chapter_id}")
async def export_chapter_notes(
    chapter_id: int,
    fmt: str = Query("md", pattern="^(md|tex|pdf)$"),
    section_ids: str | None = Query(None, description="Comma-separated section IDs to export"),
    all_sections: bool = False,
    db: Session = Depends(get_db),
):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        ids = [int(x.strip()) for x in section_ids.split(",")] if section_ids else []
    except ValueError:
        raise HTTPException(400, "Invalid section selection")
    sections = selected_sections(db, chapter_id, ids, all_sections)
    content = AcademicExporter.export_chapter_study_guide(chapter, sections, fmt=fmt)
    if fmt == "pdf":
        return Response(content=await render_pdf(content), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="omnistudy.pdf"'})
    ext = "tex" if fmt == "tex" else "md"
    suffix = f"_sections_{section_ids.replace(',', '_')}" if section_ids else "_all"
    headers = {"Content-Disposition": f'attachment; filename="chapter_{chapter_id}{suffix}_notes.{ext}"'}
    return PlainTextResponse(content=content, headers=headers)


@router.get("/exam/{session_id}")
async def export_exam_paper(
    session_id: int,
    fmt: str = Query("md", pattern="^(md|tex|pdf)$"),
    include_solutions: bool = Query(True),
    db: Session = Depends(get_db),
):
    exam = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")
    if include_solutions and exam.status != "completed":
        raise HTTPException(409, "Solutions become available after submission.")
    chapter = db.query(Chapter).filter(Chapter.id == exam.chapter_id).first()
    questions = db.query(QuestionRecord).filter(QuestionRecord.session_id == session_id).all()
    content = AcademicExporter.export_exam_session(
        chapter, exam, questions, include_solutions=include_solutions, fmt=fmt
    )
    if fmt == "pdf":
        return Response(content=await render_pdf(content), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="omnistudy.pdf"'})
    ext = "tex" if fmt == "tex" else "md"
    headers = {"Content-Disposition": f'attachment; filename="exam_{session_id}.{ext}"'}
    return PlainTextResponse(content=content, headers=headers)


@router.get("/wrong-bank/{chapter_id}")
async def export_wrong_bank_sheet(
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
        return Response(content=await render_pdf(content), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="omnistudy.pdf"'})
    ext = "tex" if fmt == "tex" else "md"
    headers = {"Content-Disposition": f'attachment; filename="wrong_bank_ch_{chapter_id}.{ext}"'}
    return PlainTextResponse(content=content, headers=headers)
