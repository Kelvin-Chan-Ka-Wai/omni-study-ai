import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import WrongQuestionBank
from services.scoring_engine import ScoringEngine
from services.slide_scope_rag import SlideScopeRAG
from services.vision_grader import VisionSolutionGrader

router = APIRouter(prefix="/api/wrong-bank", tags=["Wrong Question Collection & Mutation"])


class WrongReviewAttemptRequest(BaseModel):
    user_answer: str | list[str] | None = None
    handwritten_image_path: str | None = None


@router.get("")
def list_wrong_questions(
    chapter_id: int | None = None,
    status: str = "active",  # 'active' | 'graduated' | 'all'
    db: Session = Depends(get_db),
):
    """Returns Wrong Question Collection items with their 0/3 -> 3/3 graduation counters."""
    query = db.query(WrongQuestionBank)
    if chapter_id is not None:
        query = query.filter(WrongQuestionBank.chapter_id == chapter_id)
    if status != "all":
        query = query.filter(WrongQuestionBank.status == status)

    items = query.order_by(WrongQuestionBank.last_reviewed_at.desc()).all()
    return [
        {
            "id": item.id,
            "chapter_id": item.chapter_id,
            "section_id": item.section_id,
            "question_type": item.question_type,
            "core_concept_tag": item.core_concept_tag,
            "slide_reference": item.slide_reference,
            "prompt_markdown": item.prompt_markdown,
            "options": json.loads(item.options_json) if item.options_json else None,
            "correct_answer": item.correct_answer,
            "user_wrong_answer": item.user_wrong_answer,
            "ai_diagnosis_and_solution": item.ai_diagnosis_and_solution,
            "consecutive_correct_count": item.consecutive_correct_count,
            "badge": f"{item.consecutive_correct_count}/3",
            "mutation_generation": item.mutation_generation,
            "status": item.status,
            "last_reviewed_at": item.last_reviewed_at,
        }
        for item in items
    ]


@router.post("/{wrong_id}/mutate")
async def mutate_wrong_bank_question(wrong_id: int, db: Session = Depends(get_db)):
    """
    Regenerates the exact same underlying slide theorem/concept with mutated numbers,
    functions, and shuffled 5 options (A-E) so you test true understanding rather than memory.
    """
    entry = db.query(WrongQuestionBank).filter(WrongQuestionBank.id == wrong_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Wrong question not found")

    mutated = await SlideScopeRAG.mutate_wrong_question({
        "question_type": entry.question_type,
        "core_concept_tag": entry.core_concept_tag,
        "slide_reference": entry.slide_reference,
        "prompt_markdown": entry.prompt_markdown,
        "options_json": entry.options_json,
        "correct_answer": entry.correct_answer,
    })

    entry.prompt_markdown = mutated.get("prompt_markdown", entry.prompt_markdown)
    if mutated.get("options") and isinstance(mutated["options"], dict):
        entry.options_json = json.dumps(mutated["options"])
    entry.correct_answer = str(mutated.get("correct_answer", entry.correct_answer))
    entry.ai_diagnosis_and_solution = mutated.get(
        "ai_diagnosis_and_solution", entry.ai_diagnosis_and_solution
    )
    entry.mutation_generation += 1

    db.commit()
    db.refresh(entry)

    return {
        "id": entry.id,
        "mutation_generation": entry.mutation_generation,
        "question_type": entry.question_type,
        "core_concept_tag": entry.core_concept_tag,
        "prompt_markdown": entry.prompt_markdown,
        "options": json.loads(entry.options_json) if entry.options_json else None,
        "correct_answer": entry.correct_answer,
        "consecutive_correct_count": entry.consecutive_correct_count,
        "badge": f"{entry.consecutive_correct_count}/3",
        "provider_used": mutated.get("provider_used"),
    }


@router.post("/{wrong_id}/attempt")
async def submit_wrong_question_review_attempt(
    wrong_id: int,
    req: WrongReviewAttemptRequest,
    db: Session = Depends(get_db),
):
    """
    Grades a review attempt on a Wrong Question Bank item and updates the 3-strike counter:
    0/3 -> 1/3 -> 2/3 -> 3/3 (Auto-Graduates to Mastered Archive!).
    """
    entry = db.query(WrongQuestionBank).filter(WrongQuestionBank.id == wrong_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Wrong question not found")

    if entry.question_type in ("mcq_single", "mcq_multi"):
        res = ScoringEngine.grade_mcq_five_option(
            user_selection=req.user_answer or "",
            correct_answer=entry.correct_answer,
            max_points=3.0,
        )
        is_correct = res["is_fully_correct"]
        feedback = res["feedback"]
    else:
        vis_res = await VisionSolutionGrader.grade_written_solution(
            question_prompt=entry.prompt_markdown,
            official_rubric_and_answer=entry.correct_answer,
            max_points=10.0,
            typed_answer=str(req.user_answer) if req.user_answer else None,
            handwritten_image_path=req.handwritten_image_path,
        )
        is_correct = (vis_res["score_awarded"] / 10.0) >= 0.80
        feedback = vis_res["ai_feedback_and_solution"]

    streak_state = ScoringEngine.record_wrong_bank_review_attempt(
        db=db, wrong_id=entry.id, is_correct=is_correct
    )

    return {
        **streak_state,
        "is_correct": is_correct,
        "feedback": feedback,
        "official_solution": entry.ai_diagnosis_and_solution,
    }
