import asyncio
import math
from datetime import datetime, timezone, timedelta
import base64
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import STORAGE_DIR, SessionLocal, get_db
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, QuestionSource, PaperSectionSnapshot, SlideTranscription
from services import choice_review
from services.question_history import QuestionHistory, RepeatedQuestion
from services.documents import resolve_local_upload
from services.slide_outline import review_slides
from services.scope import exam_sections, page_numbers
from services.scoring_engine import ScoringEngine
from services.slide_scope_rag import SlideScopeRAG
from services.vision_grader import VisionSolutionGrader

router = APIRouter(prefix="/api/assessments", tags=["Quizzes, Mock Tests & 2-Hr Exams"])

SNAP_DIR = STORAGE_DIR / "handwritten_snaps"
SNAP_DIR.mkdir(parents=True, exist_ok=True)


class GenerateAssessmentRequest(BaseModel):
    chapter_id: int
    mode: str = "section_quiz"  # 'section_quiz' | 'mock_test' | 'midterm' | 'final'
    section_ids: list[int] | None = None
    all_sections: bool = False
    exam_pages: dict[int, str] | None = None


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
    corrected_transcription: str | None = None


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

    if req.mode not in ScoringEngine.EXAM_BLUEPRINTS:
        raise HTTPException(400, "Choose a supported assessment mode.")
    selected = exam_sections(db, chapter, req.section_ids, req.mode, req.exam_pages, req.all_sections)
    explicit = req.exam_pages is not None
    blueprint = ScoringEngine.EXAM_BLUEPRINTS[req.mode]
    if explicit and len(selected) > sum(t['count'] for t in blueprint['distribution'].values()):
        raise HTTPException(400, 'Select no more sections than there are questions so each section can be tested.')
    course = chapter.course_name
    decks, scoped_dicts, snapshot, codes, banks = {}, [], [], {}, {}
    history = QuestionHistory.load(db, course, chapter.testbank_file_path)
    for sec, requested_pages in selected:
        deck = sec.chapter
        if deck.id not in decks:
            path = resolve_local_upload(STORAGE_DIR, deck.slide_file_path)
            if not path: raise HTTPException(400, f'Source slides missing for {deck.chapter_title}.')
            slides = SlideScopeRAG.extract_slides_text(path)
            overrides = {r.page: r.text for r in db.query(SlideTranscription).filter_by(chapter_id=deck.id)}
            decks[deck.id] = review_slides([{**slide, 'text':overrides.get(slide['slide_number'], slide['text']),
                                            'verified':slide['slide_number'] in overrides} for slide in slides])
        ref, evidence = SlideScopeRAG.scoped_slide_evidence(decks[deck.id], requested_pages)
        code = f'D{deck.id}-S{sec.id}' if explicit else sec.section_code
        codes[code.lower()] = sec.id
        scoped_dicts.append(dict(id=sec.id, section_code=code, section_title=sec.section_title, slide_pages=ref,
                                 source_text=evidence, narrow=page_numbers(ref) != page_numbers(sec.slide_pages)))
        snapshot.append(dict(id=sec.id, section_code=sec.section_code, section_title=sec.section_title,
                             slide_pages=ref if explicit else sec.slide_pages, chapter_id=deck.id, chapter_title=deck.chapter_title))
        if explicit and deck.testbank_file_path:
            banks.setdefault(deck.testbank_file_path, set()).add(code)
    bank_inputs = []
    for ref, allowed in banks.items():
        path = resolve_local_upload(STORAGE_DIR, ref)
        if path: bank_inputs.append((path, allowed, QuestionHistory.load(db, course, ref)))
    exam_title = ' / '.join(dict.fromkeys(s['chapter_title'] for s in snapshot)) if explicit else chapter.chapter_title
    tb_path = resolve_local_upload(STORAGE_DIR, chapter.testbank_file_path)
    try:
        generated = await SlideScopeRAG.generate_scoped_assessment(
            course_name=course, chapter_title=exam_title, scoped_sections=scoped_dicts,
            mode=req.mode, testbank_file_path=tb_path, history=history,
            **({"exam_banks": bank_inputs} if explicit else {}),
        )
    except RepeatedQuestion as error:
        raise HTTPException(422, str(error)) from error

    # Refresh after slow model calls. Serialize only the final check and insert, even across workers.
    db.rollback()
    db.execute(text('BEGIN IMMEDIATE'))
    try:
        QuestionHistory.load(db, course).accept(generated['questions'])
    except RepeatedQuestion:
        db.rollback()
        raise HTTPException(409, 'A question was already used. No paper was saved. Generate another paper or broaden the selected sections.') from None
    if explicit and {str(q.get('section_code', '')).lower() for q in generated['questions']} != set(codes):
        raise HTTPException(422, 'The paper did not cover every selected section. No paper was saved.')
    blueprint = generated["blueprint"]
    exam = ExamSession(
        chapter_id=chapter.id,
        mode=req.mode,
        selected_section_ids_json=json.dumps([s["id"] for s in snapshot]),
        time_limit_minutes=blueprint["time_limit_minutes"],
        grace_period_minutes=blueprint["grace_period_minutes"],
        max_score=blueprint["total_points"],
        status="in_progress",
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=blueprint["time_limit_minutes"])).isoformat(),
    )
    db.add(exam)
    db.flush()

    # Map section_code -> section.id so mastery updates link back to exact slide sections
    db.add(PaperSectionSnapshot(session_id=exam.id, sections_json=json.dumps(snapshot, ensure_ascii=False)))
    code_to_sec_id = codes

    saved_questions = []
    for q in generated["questions"]:
        sec_code = str(q.get("section_code", "")).lower()
        if sec_code not in code_to_sec_id:
            raise HTTPException(502, "Generated question has an unknown source section.")
        matched_sec_id = code_to_sec_id[sec_code]
        opts = q.get("options")
        opts_json = json.dumps(opts) if isinstance(opts, dict) else None

        q_rec = QuestionRecord(
            session_id=exam.id,
            section_id=matched_sec_id,
            question_type=q.get("question_type", "mcq_single"),
            core_concept_tag=q.get("core_concept_tag", "Slide Concept"),
            slide_reference=(next(s["chapter_title"] for s in snapshot if s["id"] == matched_sec_id) + " · " if explicit else "") + q.get("slide_reference", "Lecture Slides"),
            testbank_reference=q.get('testbank_reference'),
            prompt_markdown=q.get("prompt_markdown", ""),
            options_json=opts_json,
            correct_answer=str(q.get("correct_answer", "")),
            max_points=float(q.get("max_points", 2.0)),
            ai_feedback_and_solution=q.get("solution_explanation", ""),
        )
        db.add(q_rec)
        saved_questions.append(q_rec)

    db.flush()
    for row, q in zip(saved_questions, generated['questions']):
        if q.get('_source'):
            db.add(QuestionSource(question_id=row.id, source_json=json.dumps(q['_source'], ensure_ascii=False)))
    result = serialize_session(exam, saved_questions)
    db.commit()
    result.update(provider_used=generated["provider_used"], model_used=generated["model_used"])
    return result


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if value else None


def ensure_deadline(exam):
    if not exam.deadline_at and not exam.is_paused:
        start = exam.started_at.replace(tzinfo=timezone.utc)
        exam.deadline_at = (start + timedelta(minutes=exam.time_limit_minutes)).isoformat()


def writing_open(exam):
    ensure_deadline(exam)
    return exam.status == "in_progress" and (exam.is_paused or utc_now() < parse_time(exam.deadline_at))


LOCKED = {"completed", "submitted_grading", "submitted_retry"}


def review_item(q, status, draft):
    if status not in LOCKED:
        return {}
    mcq = q.question_type.startswith("mcq")
    answer = q.user_answer if status == "completed" else draft.get("user_answer")
    item = {"user_answer": answer, "correct_answer": q.correct_answer}
    if mcq:
        item.update(selected_options=sorted(ScoringEngine.parse_option_set(answer or "")),
                    correct_options=sorted(ScoringEngine.parse_option_set(q.correct_answer)))
    if status == "completed":
        return {**item, "score_awarded": q.score_awarded, "is_flagged_wrong": q.is_flagged_wrong,
                "ai_feedback_and_solution": q.ai_feedback_and_solution}
    if mcq:
        scored = ScoringEngine.grade_mcq_five_option(answer or "", q.correct_answer, q.max_points)
        return {**item, "score_awarded": scored["score_awarded"], "ai_feedback_and_solution": scored["feedback"]}
    if answer or draft.get("corrected_transcription") or q.handwritten_image_path:
        return {**item, "grading_pending": True}
    return {**item, "score_awarded": 0, "ai_feedback_and_solution": "No answer submitted."}


def serialize_session(exam, questions, db=None):
    if exam.status not in LOCKED:
        ensure_deadline(exam)
    draft = json.loads(exam.draft_json or "[]")
    by_id = {a['question_id']: a for a in draft}
    reviews = choice_review.cached(db, [q.id for q in questions if q.question_type.startswith("mcq")]) if db is not None and exam.status in LOCKED else {}
    items = [{"id": q.id, "section_id": q.section_id, "question_type": q.question_type,
              "core_concept_tag": q.core_concept_tag, "slide_reference": q.slide_reference,
              "testbank_reference": q.testbank_reference, "prompt_markdown": q.prompt_markdown,
              "options": json.loads(q.options_json) if q.options_json else None,
              "max_points": q.max_points, "handwritten_image_path": q.handwritten_image_path,
              **review_item(q, exam.status, by_id.get(q.id, {})),
              **({"option_explanations": reviews[q.id]} if q.id in reviews else {})} for q in questions]
    return {
        "session_id": exam.id, "chapter_id": exam.chapter_id, "mode": exam.mode,
        "status": exam.status, "time_limit_minutes": exam.time_limit_minutes,
        "grace_period_minutes": exam.grace_period_minutes, "max_score": exam.max_score,
        "deadline_at": exam.deadline_at, "is_paused": exam.is_paused,
        "paused_remaining": exam.paused_remaining, "grace_started_at": exam.grace_started_at,
        "server_now": utc_now().isoformat(), "time_spent_seconds": exam.time_spent_seconds,
        "draft_answers": draft, "questions": items,
        **({"total_score": exam.total_score if exam.status == 'completed' else round(sum(q.get('score_awarded', 0) for q in items), 2)} if exam.status in LOCKED else {}),
    }


class ChoiceReviewRequest(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=3)


@router.post("/{session_id}/choice-review")
async def explain_choices(session_id: int, request: ChoiceReviewRequest, db: Session = Depends(get_db)):
    exam = db.get(ExamSession, session_id)
    if not exam: raise HTTPException(404, "Exam not found")
    if exam.status not in LOCKED: raise HTTPException(409, "Submit your paper before reviewing the options.")
    ids = set(request.question_ids)
    questions = [q for q in exam.questions if q.id in ids and q.question_type.startswith("mcq")]
    if len(questions) != len(ids): raise HTTPException(400, "Choose multiple-choice questions from this paper.")
    try:
        return await choice_review.explain(db, questions)
    except Exception:
        db.rollback()
        raise HTTPException(503, "Choice explanations are unavailable. Your result is saved; retry the explanations.") from None


@router.get("/active/{chapter_id}")
def active_assessment(chapter_id: int, db: Session = Depends(get_db)):
    exam = db.query(ExamSession).filter(ExamSession.chapter_id == chapter_id, ExamSession.status.in_(["in_progress", "grace_upload", "grading", "submitted_grading", "submitted_retry"])).order_by(ExamSession.id.desc()).first()
    if not exam: return None
    result = serialize_session(exam, exam.questions, db)
    db.commit()
    return result


@router.get("/{session_id}")
def get_assessment(session_id: int, db: Session = Depends(get_db)):
    exam = db.get(ExamSession, session_id)
    if not exam: raise HTTPException(404, "Exam not found")
    result = serialize_session(exam, exam.questions, db)
    db.commit()
    return result


@router.put("/{session_id}/draft")
def save_draft(session_id: int, submission: SubmitAssessmentRequest, db: Session = Depends(get_db)):
    exam = db.get(ExamSession, session_id)
    if not exam: raise HTTPException(404, "Exam not found")
    if not writing_open(exam): raise HTTPException(409, "Writing time has ended; your last saved draft is preserved.")
    allowed = {q.id for q in exam.questions}
    if any(a.question_id not in allowed for a in submission.answers): raise HTTPException(400, "Answer does not belong to this exam")
    changed = db.query(ExamSession).filter_by(id=session_id, status='in_progress').update({
        'draft_json': json.dumps([a.model_dump() for a in submission.answers]),
        'time_spent_seconds': max(0, submission.time_spent_seconds)}, synchronize_session=False)
    if not changed: raise HTTPException(409, "This paper is already locked.")
    db.commit()
    return {"saved": True, "saved_at": utc_now().isoformat()}


@router.patch("/{session_id}/timer")
def update_exam_timer(session_id: int, state: TimerStateUpdate, db: Session = Depends(get_db)):
    """Handles Pausable Timer state and triggers the 5-minute Photo Upload Grace Window."""
    exam = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")

    if exam.status not in ("in_progress", "grace_upload"):
        raise HTTPException(409, "This exam is no longer editable.")
    ensure_deadline(exam)
    now = utc_now()
    changes = {}
    if state.enter_grace_upload:
        changes = {"grace_started_at": exam.grace_started_at or now.isoformat(), "status": "grace_upload", "is_paused": False}
    elif exam.status == "in_progress":
        if state.is_paused and not exam.is_paused:
            remaining = max(0, (parse_time(exam.deadline_at) - now).total_seconds())
            if remaining <= 0: raise HTTPException(409, "Writing time has ended")
            changes = {"paused_remaining": remaining, "is_paused": True}
        elif not state.is_paused and exam.is_paused:
            changes = {"deadline_at": (now + timedelta(seconds=exam.paused_remaining or 0)).isoformat(), "is_paused": False}
    if changes and not db.query(ExamSession).filter_by(id=session_id, status=exam.status).update(changes, synchronize_session=False):
        raise HTTPException(409, "This paper is already locked.")
    db.commit()
    return serialize_session(exam, exam.questions, db)


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

    ensure_upload_open(db.get(ExamSession, session_id))
    raw_b64 = payload.image_base64
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(raw_b64, validate=True)
        validate_image(img_bytes)
    except Exception:
        raise HTTPException(400, "Paste a valid image smaller than 10 MB")
    file_name = f"session_{session_id}_q_{question_id}_{uuid.uuid4().hex[:6]}.png"
    file_path = SNAP_DIR / file_name
    file_path.write_bytes(img_bytes)

    link_finished_upload(db, q_rec.id, session_id, file_path)

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

    ensure_upload_open(db.get(ExamSession, session_id))
    ext = ".png"
    file_name = f"session_{session_id}_q_{question_id}_{uuid.uuid4().hex[:6]}{ext}"
    file_path = SNAP_DIR / file_name
    with file_path.open("wb") as f:
        img_bytes = image_file.file.read(10 * 1024 * 1024 + 1)
        validate_image(img_bytes)
        f.write(img_bytes)

    link_finished_upload(db, q_rec.id, session_id, file_path)

    return {
        "question_id": q_rec.id,
        "handwritten_image_path": str(file_path),
        "preview_url": f"/storage/handwritten_snaps/{file_name}",
    }


def link_finished_upload(db, question_id, session_id, file_path):
    changed = db.query(QuestionRecord).filter(QuestionRecord.id == question_id,
        QuestionRecord.session.has(ExamSession.status.in_(["in_progress", "grace_upload"]))).update(
            {"handwritten_image_path": str(file_path)}, synchronize_session=False)
    if not changed:
        db.rollback(); file_path.unlink(missing_ok=True)
        raise HTTPException(409, "This upload finished after submission and was not included.")
    db.commit()


def validate_image(data):
    from PIL import Image
    from io import BytesIO
    if len(data) > 10 * 1024 * 1024: raise HTTPException(400, "Image must be smaller than 10 MB")
    try:
        with Image.open(BytesIO(data)) as image: image.verify()
    except Exception: raise HTTPException(400, "Invalid image")


def ensure_upload_open(exam):
    ensure_deadline(exam)
    finish = parse_time(exam.grace_started_at) if exam.grace_started_at else parse_time(exam.deadline_at)
    if exam.status not in ("in_progress", "grace_upload") or (not exam.is_paused and utc_now() > finish + timedelta(minutes=exam.grace_period_minutes)):
        raise HTTPException(409, "Photo upload time has ended")


@router.post("/{session_id}/questions/{question_id}/transcribe")
async def transcribe_solution(session_id: int, question_id: int, db: Session = Depends(get_db)):
    q = db.query(QuestionRecord).filter_by(id=question_id, session_id=session_id).first()
    if not q or not q.handwritten_image_path: raise HTTPException(404, "Upload an image first")
    result = await VisionSolutionGrader.transcribe_handwritten_image(q.handwritten_image_path)
    return {"transcription": result["transcribed_latex"]}


@router.post("/{session_id}/submit")
async def submit_and_grade_assessment(session_id: int, submission: SubmitAssessmentRequest, db: Session = Depends(get_db)):
    exam = db.get(ExamSession, session_id)
    if not exam: raise HTTPException(404, "Exam not found")
    if exam.status == "completed" and exam.result_json:
        return json.loads(exam.result_json)
    previous_status = exam.status
    claim_submission(db, exam, submission, "grading")
    return await grade_claimed(session_id, db, "grading", previous_status)


def claim_submission(db, exam, submission, target):
    if exam.status not in ("in_progress", "grace_upload"):
        raise HTTPException(409, "This paper has already been submitted.")
    allowed = {q.id for q in exam.questions}
    if len({a.question_id for a in submission.answers}) != len(submission.answers) or any(a.question_id not in allowed for a in submission.answers):
        raise HTTPException(400, "Invalid or duplicate question IDs")
    answers = [a.model_dump() for a in submission.answers] if writing_open(exam) else json.loads(exam.draft_json or "[]")
    changed = db.query(ExamSession).filter(ExamSession.id == exam.id, ExamSession.status == exam.status).update({
        "status": target, "draft_json": json.dumps(answers), "time_spent_seconds": max(exam.time_spent_seconds or 0, min(max(0, submission.time_spent_seconds), exam.time_limit_minutes * 60))}, synchronize_session=False)
    if not changed: raise HTTPException(409, "Submission is already in progress; your answers are saved.")
    db.commit()
    db.refresh(exam)


async def grade_in_background(session_id):
    with SessionLocal() as db:
        try:
            await grade_claimed(session_id, db, "submitted_grading", "submitted_retry")
        except HTTPException:
            pass  # The locked paper remains available for a retry.


@router.post("/{session_id}/finish")
async def finish_now(session_id: int, submission: SubmitAssessmentRequest, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    exam = db.get(ExamSession, session_id)
    if not exam: raise HTTPException(404, "Exam not found")
    if exam.status in ('completed', 'submitted_grading'):
        return serialize_session(exam, exam.questions, db)
    if exam.status == 'submitted_retry':
        changed = db.query(ExamSession).filter_by(id=session_id, status='submitted_retry').update({'status': 'submitted_grading'}, synchronize_session=False)
        db.commit(); db.refresh(exam)
        if not changed: return serialize_session(exam, exam.questions, db)
    else:
        claim_submission(db, exam, submission, 'submitted_grading')
    preview = serialize_session(exam, exam.questions, db)
    if any(q.get('grading_pending') for q in preview['questions']):
        tasks.add_task(grade_in_background, session_id)
        return preview
    await grade_claimed(session_id, db, 'submitted_grading', 'submitted_retry')
    return serialize_session(exam, exam.questions, db)


async def grade_claimed(session_id, db, claimed_status, failure_status):
    exam = db.get(ExamSession, session_id)
    answers = [QuestionSubmissionItem(**a) for a in json.loads(exam.draft_json or "[]")]
    try:
        questions = db.query(QuestionRecord).filter_by(session_id=session_id).all()
        answer_map = {a.question_id: a for a in answers}
        gate = asyncio.Semaphore(3)
        async def grade(q):
            item = answer_map.get(q.id)
            raw = item.user_answer if item else ""
            if q.question_type.startswith("mcq"):
                result = ScoringEngine.grade_mcq_five_option(raw or "", q.correct_answer, q.max_points)
                explanation = q.ai_feedback_and_solution or ""
                feedback = "\n\n".join(filter(None, [result["feedback"], explanation]))
                return q, str(raw or ""), result["score_awarded"], feedback
            corrected = item.corrected_transcription if item else None
            # Do not accept arbitrary client-supplied filesystem paths.
            path = q.handwritten_image_path
            if path:
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(SNAP_DIR.resolve()): raise HTTPException(400, "Invalid solution image")
            async with gate:
                result = await VisionSolutionGrader.grade_written_solution(q.prompt_markdown, q.correct_answer, q.max_points,
                    typed_answer="\n".join(v for v in (str(raw or ""), corrected) if v), handwritten_image_path=path if not (corrected or raw) else None)
            if not math.isfinite(result["score_awarded"]): raise ValueError("Invalid grading score")
            return q, result["transcribed_student_work"], result["score_awarded"], result["ai_feedback_and_solution"]
        results = await asyncio.gather(*(grade(q) for q in questions))
        # No question/mastery writes until every grade succeeded. Final transaction is all-or-nothing.
        graded = []
        wrong_count = 0
        for q, answer, score, feedback in results:
            q.user_answer, q.score_awarded, q.ai_feedback_and_solution = answer, score, feedback
            if ScoringEngine.sync_wrong_question_bank(db, q.section.chapter_id if q.section else exam.chapter_id, q, commit=False): wrong_count += 1
            graded.append({"question_id": q.id, "user_answer": answer, "correct_answer": q.correct_answer, "score_awarded": score,
                "max_points": q.max_points, "ai_feedback_and_solution": feedback, "is_flagged_wrong": q.is_flagged_wrong})
        summary = ScoringEngine.update_section_and_chapter_mastery(db, session_id, commit=False)
        result = {**summary, "wrong_questions_collected": wrong_count, "questions": graded}
        exam = db.get(ExamSession, session_id)
        exam.result_json = json.dumps(result)
        db.commit()
        return result
    except BaseException as exc:
        db.rollback()
        db.query(ExamSession).filter_by(id=session_id, status=claimed_status).update({"status": failure_status}, synchronize_session=False)
        db.commit()
        if isinstance(exc, (asyncio.CancelledError, HTTPException)): raise
        raise HTTPException(503, "Grading unavailable. Your saved answers are preserved; retry submission.") from None
