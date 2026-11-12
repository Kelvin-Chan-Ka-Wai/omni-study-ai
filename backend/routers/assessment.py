import base64
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import STORAGE_DIR, get_db
from models import Chapter, ChapterSection, ExamSession, QuestionRecord
from services.scoring_engine import ScoringEngine
from services.slide_scope_rag import SlideScopeRAG
from services.vision_grader import VisionSolutionGrader

router = APIRouter(prefix="/api/assessments", tags=["Quizzes, Mock Tests & 2-Hr Exams"])

SNAP_DIR = STORAGE_DIR / "handwritten_snaps"
SNAP_DIR.mkdir(parents=True, exist_ok=True)


class GenerateAssessmentRequest(BaseModel):
    chapter_id: int
    mode: str = "section_quiz"  # 'section_quiz' | 'mock_test' | 'midterm' | 'final'
    section_ids: list[int] | None = None  # Specific slide sections selected by user


class TimerStateUpdate(BaseModel):
    is_paused: bool
    time_spent_seconds: int
    enter_grace_upload: bool = False


class PasteBase64ImageRequest(BaseModel):
    image_base64: str  # Supports Cmd+V data:image/png;base64,...


class QuestionSubmissionItem(BaseModel):
    question_id: int
    user_answer: str | list[str] | None = None
    handwritten_image_path: str | None = None


class SubmitAssessmentRequest(BaseModel):
    time_spent_seconds: int = 0
    answers: list[QuestionSubmissionItem]


@router.post("/generate")
async def generate_assessment(req: GenerateAssessmentRequest, db: Session = Depends(get_db)):
    """
    Generates a slide-scoped assessment (5-Option A-E Single/Multi MCQs, Short Answer, Calculations)
    only from the user-selected slide sections.
    """
    chapter = db.query(Chapter).filter(Chapter.id == req.chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    query = db.query(ChapterSection).filter(ChapterSection.chapter_id == req.chapter_id)
    if req.section_ids:
        query = query.filter(ChapterSection.id.in_(req.section_ids))
    sections = query.all()

    if not sections:
        raise HTTPException(status_code=400, detail="No slide sections found for the selected scope.")

    scoped_dicts = [
        {
            "id": s.id,
            "section_code": s.section_code,
            "section_title": s.section_title,
            "slide_pages": s.slide_pages,
            "extracted_study_notes": s.extracted_study_notes,
        }
        for s in sections
    ]

    tb_path = None
    if getattr(chapter, "testbank_file_path", None):
        clean_rel = chapter.testbank_file_path.replace("/storage/", "", 1).lstrip("/")
        cand = STORAGE_DIR / clean_rel
        if cand.exists():
            tb_path = cand

    generated = await SlideScopeRAG.generate_scoped_assessment(
        course_name=chapter.course_name,
        chapter_title=chapter.chapter_title,
        scoped_sections=scoped_dicts,
        mode=req.mode,
        testbank_file_path=tb_path,
    )

    blueprint = generated["blueprint"]
    exam = ExamSession(
        chapter_id=chapter.id,
        mode=req.mode,
        selected_section_ids_json=json.dumps([s.id for s in sections]),
        time_limit_minutes=blueprint["time_limit_minutes"],
        grace_period_minutes=blueprint["grace_period_minutes"],
        max_score=blueprint["total_points"],
        status="in_progress",
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)

    # Map section_code -> section.id so mastery updates link back to exact slide sections
    code_to_sec_id = {s.section_code.lower(): s.id for s in sections}
    default_sec_id = sections[0].id

    saved_questions = []
    for q in generated["questions"]:
        sec_code = str(q.get("section_code", "")).lower()
        matched_sec_id = code_to_sec_id.get(sec_code, default_sec_id)
        opts = q.get("options")
        opts_json = json.dumps(opts) if isinstance(opts, dict) else None

        q_rec = QuestionRecord(
            session_id=exam.id,
            section_id=matched_sec_id,
            question_type=q.get("question_type", "mcq_single"),
            core_concept_tag=q.get("core_concept_tag", "Slide Concept"),
            slide_reference=q.get("slide_reference", "Lecture Slides"),
            prompt_markdown=q.get("prompt_markdown", ""),
            options_json=opts_json,
            correct_answer=str(q.get("correct_answer", "")),
            max_points=float(q.get("max_points", 2.0)),
            ai_feedback_and_solution=q.get("solution_explanation", ""),
        )
        db.add(q_rec)
        saved_questions.append(q_rec)

    db.commit()
    for qr in saved_questions:
        db.refresh(qr)

    return {
        "session_id": exam.id,
        "chapter_id": chapter.id,
        "mode": exam.mode,
        "time_limit_minutes": exam.time_limit_minutes,
        "grace_period_minutes": exam.grace_period_minutes,
        "max_score": exam.max_score,
        "provider_used": generated["provider_used"],
        "model_used": generated["model_used"],
        "questions": [
            {
                "id": qr.id,
                "section_id": qr.section_id,
                "question_type": qr.question_type,
                "core_concept_tag": qr.core_concept_tag,
                "slide_reference": qr.slide_reference,
                "prompt_markdown": qr.prompt_markdown,
                "options": json.loads(qr.options_json) if qr.options_json else None,
                "max_points": qr.max_points,
            }
            for qr in saved_questions
        ],
    }


@router.patch("/{session_id}/timer")
def update_exam_timer(session_id: int, state: TimerStateUpdate, db: Session = Depends(get_db)):
    """Handles Pausable Timer state and triggers the 5-minute Photo Upload Grace Window."""
    exam = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")

    exam.is_paused = state.is_paused
    exam.time_spent_seconds = state.time_spent_seconds
    if state.enter_grace_upload and exam.status == "in_progress":
        exam.status = "grace_upload"

    db.commit()
    return {
        "session_id": exam.id,
        "is_paused": exam.is_paused,
        "time_spent_seconds": exam.time_spent_seconds,
        "status": exam.status,
        "grace_period_minutes": exam.grace_period_minutes,
    }


@router.post("/{session_id}/questions/{question_id}/paste-image")
def paste_clipboard_solution_image(
    session_id: int,
    question_id: int,
    payload: PasteBase64ImageRequest,
    db: Session = Depends(get_db),
):
    """
    Saves a Cmd+V pasted screenshot or Continuity Camera image directly to
    backend/storage/handwritten_snaps/ and links it to the question record.
    """
    q_rec = (
        db.query(QuestionRecord)
        .filter(QuestionRecord.id == question_id, QuestionRecord.session_id == session_id)
        .first()
    )
    if not q_rec:
        raise HTTPException(status_code=404, detail="Question not found in this session")

    raw_b64 = payload.image_base64
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    img_bytes = base64.b64decode(raw_b64)
    file_name = f"session_{session_id}_q_{question_id}_{uuid.uuid4().hex[:6]}.png"
    file_path = SNAP_DIR / file_name
    file_path.write_bytes(img_bytes)

    q_rec.handwritten_image_path = str(file_path)
    db.commit()

    return {
        "question_id": q_rec.id,
        "handwritten_image_path": str(file_path),
        "preview_url": f"/storage/handwritten_snaps/{file_name}",
    }


@router.post("/{session_id}/questions/{question_id}/upload-image")
def upload_solution_image_file(
    session_id: int,
    question_id: int,
    image_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Handles drag-and-drop or AirDrop solution photo files."""
    q_rec = (
        db.query(QuestionRecord)
        .filter(QuestionRecord.id == question_id, QuestionRecord.session_id == session_id)
        .first()
    )
    if not q_rec:
        raise HTTPException(status_code=404, detail="Question not found in this session")

    ext = Path(image_file.filename or "snap.png").suffix or ".png"
    file_name = f"session_{session_id}_q_{question_id}_{uuid.uuid4().hex[:6]}{ext}"
    file_path = SNAP_DIR / file_name
    with file_path.open("wb") as f:
        img_bytes = image_file.file.read()
        f.write(img_bytes)

    q_rec.handwritten_image_path = str(file_path)
    db.commit()

    return {
        "question_id": q_rec.id,
        "handwritten_image_path": str(file_path),
        "preview_url": f"/storage/handwritten_snaps/{file_name}",
    }


@router.post("/{session_id}/submit")
async def submit_and_grade_assessment(
    session_id: int,
    submission: SubmitAssessmentRequest,
    db: Session = Depends(get_db),
):
    """
    Grades all questions in the session:
    - 5-Option MCQs (single & multi): Graded with Partial Credit (|U|/|C| with 0 on wrong pick).
    - Short Answer & Calculations: Graded via VisionSolutionGrader (GLM-OCR + DeepSeek step-by-step rubric).
    - Automatically populates the Wrong Question Bank and recomputes >=80% Section & Chapter Mastery.
    """
    exam = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")

    exam.time_spent_seconds = submission.time_spent_seconds
    ans_map = {item.question_id: item for item in submission.answers}

    questions = (
        db.query(QuestionRecord)
        .filter(QuestionRecord.session_id == session_id)
        .all()
    )

    graded_results = []
    wrong_collected_count = 0

    for q in questions:
        sub_item = ans_map.get(q.id)
        raw_user_ans = sub_item.user_answer if sub_item else None
        if sub_item and sub_item.handwritten_image_path:
            q.handwritten_image_path = sub_item.handwritten_image_path

        if q.question_type in ("mcq_single", "mcq_multi"):
            mcq_res = ScoringEngine.grade_mcq_five_option(
                user_selection=raw_user_ans or "",
                correct_answer=q.correct_answer,
                max_points=q.max_points,
            )
            if isinstance(raw_user_ans, list):
                q.user_answer = ", ".join(str(x) for x in raw_user_ans)
            else:
                q.user_answer = str(raw_user_ans or "")
            q.score_awarded = mcq_res["score_awarded"]
            existing_explanation = q.ai_feedback_and_solution or ""
            q.ai_feedback_and_solution = f"{mcq_res['feedback']}\n\n{existing_explanation}".strip()
        else:
            typed_str = str(raw_user_ans) if raw_user_ans else None
            vis_res = await VisionSolutionGrader.grade_written_solution(
                question_prompt=q.prompt_markdown,
                official_rubric_and_answer=q.correct_answer,
                max_points=q.max_points,
                typed_answer=typed_str,
                handwritten_image_path=q.handwritten_image_path,
            )
            q.user_answer = vis_res["transcribed_student_work"]
            q.score_awarded = vis_res["score_awarded"]
            steps_md = "\n".join(f"- {s}" for s in vis_res.get("step_breakdown", []))
            q.ai_feedback_and_solution = (
                f"**Error Diagnosis:** {vis_res.get('error_diagnosis', '')}\n\n"
                f"**Step-by-Step Rubric Breakdown:**\n{steps_md}\n\n"
                f"{vis_res.get('ai_feedback_and_solution', '')}"
            ).strip()

        db.commit()
        wrong_entry = ScoringEngine.sync_wrong_question_bank(db, exam.chapter_id, q)
        if wrong_entry:
            wrong_collected_count += 1

        graded_results.append({
            "question_id": q.id,
            "question_type": q.question_type,
            "user_answer": q.user_answer,
            "correct_answer": q.correct_answer,
            "score_awarded": q.score_awarded,
            "max_points": q.max_points,
            "is_flagged_wrong": q.is_flagged_wrong,
            "ai_feedback_and_solution": q.ai_feedback_and_solution,
        })

    mastery_summary = ScoringEngine.update_section_and_chapter_mastery(db, exam.id)

    return {
        **mastery_summary,
        "wrong_questions_collected": wrong_collected_count,
        "questions": graded_results,
    }
