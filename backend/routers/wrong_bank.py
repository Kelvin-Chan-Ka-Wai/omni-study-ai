import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from config import settings
from database import get_db
from models import WrongQuestionBank
from services.llm_harness import HybridLLMHarness
from services.scoring_engine import ScoringEngine
from services.slide_scope_rag import SlideScopeRAG

router = APIRouter(prefix="/api/wrong-bank", tags=["Wrong Question Bank (0/3 -> 3/3 Mastery)"])


class AttemptWrongRequest(BaseModel):
    user_answer: str | list[str]


class WrongItemResponse(BaseModel):
    id: int
    chapter_id: int
    section_id: int | None = None
    question_type: str
    core_concept_tag: str
    slide_reference: str
    prompt_markdown: str
    options: dict[str, str] | None = None
    correct_answer: str
    user_wrong_answer: str
    ai_diagnosis_and_solution: str
    consecutive_correct_count: int
    required_streak: int
    badge: str
    total_review_attempts: int
    mutation_generation: int
    status: str
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    original_question: dict | None = None
    attempt_is_correct: bool | None = None
    attempt_feedback: str | None = None


def _safe_parse_options(raw_options: str | dict | None) -> dict | None:
    if not raw_options:
        return None
    if isinstance(raw_options, dict):
        return raw_options
    if isinstance(raw_options, str):
        raw_str = raw_options.strip()
        if not raw_str or raw_str == "null":
            return None
        try:
            parsed = json.loads(raw_str)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            try:
                parsed = SlideScopeRAG._clean_json_response(raw_str)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
    return None


def _serialize_wrong_item(item: WrongQuestionBank) -> dict:
    parsed_opts = _safe_parse_options(getattr(item, "options_json", None))
    required_streak = getattr(settings, "WRONG_QUESTION_GRADUATION_STREAK", 3) or 3
    streak = getattr(item, "consecutive_correct_count", 0) or 0
    return {
        "id": item.id,
        "chapter_id": item.chapter_id,
        "section_id": getattr(item, "section_id", None),
        "question_type": item.question_type or "mcq_single",
        "core_concept_tag": item.core_concept_tag or "Slide Concept",
        "slide_reference": item.slide_reference or "Slides",
        "prompt_markdown": SlideScopeRAG.sanitize_markdown_latex_notes(item.prompt_markdown or ""),
        "options": parsed_opts,
        "correct_answer": item.correct_answer or "",
        "user_wrong_answer": getattr(item, "user_wrong_answer", "") or "",
        "ai_diagnosis_and_solution": SlideScopeRAG.sanitize_markdown_latex_notes(
            getattr(item, "ai_diagnosis_and_solution", "") or ""
        ),
        "consecutive_correct_count": streak,
        "required_streak": required_streak,
        "badge": f"{streak}/{required_streak}",
        "next_review_at": item.next_review_at.replace(tzinfo=timezone.utc) if item.next_review_at else None,
        "last_reviewed_at": item.last_reviewed_at.replace(tzinfo=timezone.utc) if item.last_reviewed_at else None,
        "mutation_generation": item.mutation_generation,
        "original_question": json.loads(item.original_json) if item.original_json else None,
        "total_review_attempts": getattr(item, "total_review_attempts", 0) or 0,
        "status": item.status or "active",
        "graduated_at": getattr(item, "graduated_at", None),
    }


@router.get("/{chapter_id}", response_model=list[WrongItemResponse])
def list_wrong_questions(
    chapter_id: int,
    status: str = Query("active", pattern="^(active|graduated|all)$"),
    db: Session = Depends(get_db),
):
    query = db.query(WrongQuestionBank).filter(WrongQuestionBank.chapter_id == chapter_id)
    if status != "all":
        query = query.filter(WrongQuestionBank.status == status)
    items = query.order_by(WrongQuestionBank.id.desc()).all()
    return [_serialize_wrong_item(it) for it in items]


@router.post("/{wrong_id}/attempt", response_model=WrongItemResponse)
async def attempt_wrong_question(
    wrong_id: int,
    req: AttemptWrongRequest,
    db: Session = Depends(get_db),
):
    item = db.query(WrongQuestionBank).filter(WrongQuestionBank.id == wrong_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Wrong question not found")

    required_streak = getattr(settings, "WRONG_QUESTION_GRADUATION_STREAK", 3) or 3
    q_type = item.question_type or "mcq_single"

    is_correct = False
    feedback = ""

    if q_type in ("mcq_single", "mcq_multi"):
        score_res = ScoringEngine.grade_mcq_five_option(
            user_selection=req.user_answer,
            correct_answer=item.correct_answer or "",
            max_points=10.0,
        )
        is_correct = score_res["is_fully_correct"]
        feedback = (
            f"Correct! ({item.correct_answer})"
            if is_correct
            else f"Not quite. Correct answer is {item.correct_answer}."
        )
    else:
        user_str = (
            ", ".join(req.user_answer)
            if isinstance(req.user_answer, list)
            else str(req.user_answer)
        ).strip()
        if not user_str:
            is_correct = False
            feedback = "Please enter an answer before submitting."
        else:
            prompt = f"""Grade this student retry on a university question.
Question: {item.prompt_markdown}
Official Solution: {item.correct_answer}
Student Answer: {user_str}

Return JSON only: {{"is_correct": true or false, "feedback": "1 concise sentence explanation"}}"""
            try:
                res = await HybridLLMHarness.chat(
                    messages=[{"role": "user", "content": prompt}],
                    task="fast",
                    temperature=0.1,
                    json_mode=True,
                    max_tokens=250,
                )
                parsed = SlideScopeRAG._clean_json_response(res["content"])
                if not isinstance(parsed, dict) or type(parsed.get("is_correct")) is not bool:
                    raise ValueError("Invalid grading response")
                is_correct = parsed["is_correct"]
                feedback = str(parsed.get("feedback", ""))
            except Exception:
                raise HTTPException(503, "Grading unavailable. Your answer and mastery streak are unchanged; please retry.")

    item.last_reviewed_at = datetime.now(timezone.utc)
    item.next_review_at = datetime.now(timezone.utc) + timedelta(days=(1, 3, 7, 14)[min(item.consecutive_correct_count or 0, 3)] if is_correct else 0)
    item.total_review_attempts = (getattr(item, "total_review_attempts", 0) or 0) + 1
    if is_correct:
        item.consecutive_correct_count = min(required_streak, (getattr(item, "consecutive_correct_count", 0) or 0) + 1)
        if item.consecutive_correct_count >= required_streak:
            item.status = "graduated"
            if hasattr(item, "graduated_at"):
                item.graduated_at = datetime.utcnow()
    else:
        item.consecutive_correct_count = 0
        item.status = "active"

    db.commit()
    db.refresh(item)

    serialized = _serialize_wrong_item(item)
    serialized["attempt_is_correct"] = is_correct
    serialized["attempt_feedback"] = feedback
    return serialized


@router.post("/{wrong_id}/mutate", response_model=WrongItemResponse)
async def mutate_wrong_question(
    wrong_id: int,
    db: Session = Depends(get_db),
):
    item = db.query(WrongQuestionBank).filter(WrongQuestionBank.id == wrong_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Wrong question not found")

    original = {"prompt_markdown": item.prompt_markdown, "options_json": item.options_json, "correct_answer": item.correct_answer}
    mutated = await SlideScopeRAG.mutate_wrong_question({
        "question_type": item.question_type,
        "core_concept_tag": item.core_concept_tag,
        "slide_reference": item.slide_reference,
        "prompt_markdown": item.prompt_markdown,
        "options_json": getattr(item, "options_json", None),
        "correct_answer": item.correct_answer,
    })

    if not isinstance(mutated, dict) or not mutated.get("prompt_markdown") or not mutated.get("correct_answer"):
        raise HTTPException(502, "Incomplete twin question; original question preserved.")
    if item.question_type.startswith("mcq") and (not isinstance(mutated.get("options"), dict) or set(mutated["options"]) != set("ABCDE")):
        raise HTTPException(502, "Twin question must include five valid options; original preserved.")
    if not item.original_json:
        item.original_json = json.dumps(original)
    history = json.loads(item.variant_history_json or "[]")
    history.append(original)
    item.variant_history_json = json.dumps(history)
    item.mutation_generation = (item.mutation_generation or 0) + 1
    if mutated.get("prompt_markdown"):
        item.prompt_markdown = SlideScopeRAG.sanitize_markdown_latex_notes(
            mutated["prompt_markdown"]
        )
    if "options" in mutated and isinstance(mutated["options"], dict):
        item.options_json = json.dumps(mutated["options"], ensure_ascii=False)
    if mutated.get("correct_answer"):
        item.correct_answer = str(mutated["correct_answer"])
    if mutated.get("ai_diagnosis_and_solution"):
        item.ai_diagnosis_and_solution = SlideScopeRAG.sanitize_markdown_latex_notes(
            str(mutated["ai_diagnosis_and_solution"])
        )

    db.commit()
    db.refresh(item)
    return _serialize_wrong_item(item)
