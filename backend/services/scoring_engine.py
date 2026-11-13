import re
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from config import settings
from models import (
    Chapter,
    ChapterSection,
    ExamSession,
    QuestionRecord,
    WrongQuestionBank,
)

class ScoringEngine:
    EXAM_BLUEPRINTS = {
        "section_quiz": {
            "time_limit_minutes": 20,
            "grace_period_minutes": 5,
            "total_points": 25.0,
            "distribution": {
                "mcq": {"count": 5, "points_each": 2.0},
                "short_answer": {"count": 2, "points_each": 4.0},
                "calculation": {"count": 1, "points_each": 7.0},
            },
        },
        "mock_test": {
            "time_limit_minutes": 60,
            "grace_period_minutes": 5,
            "total_points": 50.0,
            "distribution": {
                "mcq": {"count": 10, "points_each": 2.0},
                "short_answer": {"count": 3, "points_each": 5.0},
                "calculation": {"count": 2, "points_each": 7.5},
            },
        },
        "midterm": {
            "time_limit_minutes": settings.MIDTERM_FINAL_DURATION_MINUTES,
            "grace_period_minutes": settings.PHOTO_UPLOAD_GRACE_MINUTES,
            "total_points": 100.0,
            "distribution": {
                "mcq": {"count": 20, "points_each": 1.5},
                "short_answer": {"count": 5, "points_each": 6.0},
                "calculation": {"count": 4, "points_each": 10.0},
            },
        },
        "final": {
            "time_limit_minutes": settings.MIDTERM_FINAL_DURATION_MINUTES,
            "grace_period_minutes": settings.PHOTO_UPLOAD_GRACE_MINUTES,
            "total_points": 100.0,
            "distribution": {
                "mcq": {"count": 20, "points_each": 1.5},
                "short_answer": {"count": 5, "points_each": 6.0},
                "calculation": {"count": 4, "points_each": 10.0},
            },
        },
    }

    @staticmethod
    def parse_option_set(raw_options: str | list[str]) -> set[str]:
        if not raw_options:
            return set()
        if isinstance(raw_options, list):
            raw_str = ",".join(str(x) for x in raw_options)
        else:
            raw_str = str(raw_options)
        letters = re.findall(r"(?<![A-Z])[A-E](?![A-Z])", raw_str.upper())
        return set(letters)

    @classmethod
    def grade_mcq_five_option(
        cls,
        user_selection: str | list[str],
        correct_answer: str | list[str],
        max_points: float,
    ) -> dict:
        C = cls.parse_option_set(correct_answer)
        U = cls.parse_option_set(user_selection)

        if not C:
            raise ValueError("Correct answer set C cannot be empty.")

        if not U:
            return {
                "score_awarded": 0.0,
                "max_points": max_points,
                "status": "unanswered",
                "is_fully_correct": False,
                "feedback": f"No option selected. Correct answer: {', '.join(sorted(C))}.",
            }

        wrong_picks = U - C
        if wrong_picks:
            return {
                "score_awarded": 0.0,
                "max_points": max_points,
                "status": "incorrect_wrong_pick",
                "is_fully_correct": False,
                "feedback": (
                    f"0 pts awarded because incorrect option(s) {{{', '.join(sorted(wrong_picks))}}} "
                    f"were selected. Correct answer: {{{', '.join(sorted(C))}}}."
                ),
            }

        ratio = len(U) / len(C)
        score = round(max_points * ratio, 2)
        is_full = len(U) == len(C)
        missing = C - U

        if is_full:
            feedback = f"Full credit ({score}/{max_points} pts)! Selected all correct options: {', '.join(sorted(C))}."
        else:
            feedback = (
                f"Partial credit ({score}/{max_points} pts — {len(U)}/{len(C)} correct). "
                f"You correctly picked {{{', '.join(sorted(U))}}} with no wrong choices, "
                f"but missed {{{', '.join(sorted(missing))}}}."
            )

        return {
            "score_awarded": score,
            "max_points": max_points,
            "status": "correct" if is_full else "partial_credit",
            "is_fully_correct": is_full,
            "feedback": feedback,
        }

    @staticmethod
    def should_collect_as_wrong(question_type: str, score_awarded: float, max_points: float) -> bool:
        if max_points <= 0:
            return False
        ratio = score_awarded / max_points
        if question_type in ("mcq_single", "mcq_multi"):
            return ratio < 0.999
        return ratio < settings.SECTION_MASTERY_THRESHOLD

    @classmethod
    def sync_wrong_question_bank(
        cls,
        db: Session,
        chapter_id: int,
        question_record: QuestionRecord,
        commit: bool = True,
    ) -> WrongQuestionBank | None:
        is_wrong = cls.should_collect_as_wrong(
            question_record.question_type,
            question_record.score_awarded,
            question_record.max_points,
        )
        question_record.is_flagged_wrong = is_wrong

        if not is_wrong:
            return None

        existing = (
            db.query(WrongQuestionBank)
            .filter(
                WrongQuestionBank.chapter_id == chapter_id,
                WrongQuestionBank.prompt_markdown == question_record.prompt_markdown,
            )
            .first()
        )

        if existing:
            existing.user_wrong_answer = question_record.user_answer
            existing.handwritten_image_path = question_record.handwritten_image_path
            existing.ai_diagnosis_and_solution = question_record.ai_feedback_and_solution
            existing.consecutive_correct_count = 0
            existing.status = "active"
            existing.last_reviewed_at = datetime.now(timezone.utc)
            db.commit() if commit else db.flush()
            db.refresh(existing)
            return existing

        wrong_entry = WrongQuestionBank(
            chapter_id=chapter_id,
            section_id=question_record.section_id,
            source_question_id=question_record.id,
            question_type=question_record.question_type,
            core_concept_tag=question_record.core_concept_tag,
            slide_reference=question_record.slide_reference,
            prompt_markdown=question_record.prompt_markdown,
            options_json=question_record.options_json,
            correct_answer=question_record.correct_answer,
            user_wrong_answer=question_record.user_answer,
            handwritten_image_path=question_record.handwritten_image_path,
            ai_diagnosis_and_solution=question_record.ai_feedback_and_solution,
            consecutive_correct_count=0,
            status="active",
        )
        db.add(wrong_entry)
        db.commit() if commit else db.flush()
        db.refresh(wrong_entry)
        return wrong_entry

    @classmethod
    def record_wrong_bank_review_attempt(
        cls,
        db: Session,
        wrong_id: int,
        is_correct: bool,
    ) -> dict:
        entry = db.query(WrongQuestionBank).filter(WrongQuestionBank.id == wrong_id).first()
        if not entry:
            raise ValueError(f"WrongQuestionBank ID {wrong_id} not found.")

        entry.total_review_attempts += 1
        entry.last_reviewed_at = datetime.now(timezone.utc)
        target_streak = settings.WRONG_QUESTION_GRADUATION_STREAK

        if is_correct:
            entry.consecutive_correct_count += 1
            if entry.consecutive_correct_count >= target_streak:
                entry.status = "graduated"
        else:
            entry.consecutive_correct_count = 0
            entry.status = "active"

        db.commit()
        db.refresh(entry)

        return {
            "wrong_id": entry.id,
            "consecutive_correct_count": entry.consecutive_correct_count,
            "target_streak": target_streak,
            "status": entry.status,
            "graduated": entry.status == "graduated",
            "badge": f"{entry.consecutive_correct_count}/{target_streak}",
        }

    @classmethod
    def update_section_and_chapter_mastery(
        cls,
        db: Session,
        session_id: int,
        commit: bool = True,
    ) -> dict:
        exam = db.query(ExamSession).filter(ExamSession.id == session_id).first()
        if not exam:
            raise ValueError(f"ExamSession {session_id} not found.")

        questions = (
            db.query(QuestionRecord)
            .filter(QuestionRecord.session_id == session_id)
            .all()
        )

        total_awarded = sum(q.score_awarded for q in questions)
        total_max = sum(q.max_points for q in questions)
        exam.total_score = round(total_awarded, 2)
        exam.max_score = round(total_max, 2) if total_max > 0 else exam.max_score
        exam.accuracy = round(total_awarded / total_max, 4) if total_max > 0 else 0.0
        exam.status = "completed"
        exam.completed_at = datetime.now(timezone.utc)

        section_buckets: dict[int, list[QuestionRecord]] = {}
        for q in questions:
            if q.section_id is not None:
                section_buckets.setdefault(q.section_id, []).append(q)

        threshold = settings.SECTION_MASTERY_THRESHOLD

        for sec_id, sec_questions in section_buckets.items():
            sec_awarded = sum(q.score_awarded for q in sec_questions)
            sec_max = sum(q.max_points for q in sec_questions)
            if sec_max <= 0:
                continue
            sec_acc = round(sec_awarded / sec_max, 4)
            section = db.query(ChapterSection).filter(ChapterSection.id == sec_id).first()
            if section:
                section.quiz_attempts += 1
                section.latest_accuracy = sec_acc
                if sec_acc > section.best_accuracy:
                    section.best_accuracy = sec_acc
                section.is_mastered = section.best_accuracy >= threshold

        all_sections = (
            db.query(ChapterSection)
            .filter(ChapterSection.chapter_id == exam.chapter_id)
            .all()
        )
        chapter = db.query(Chapter).filter(Chapter.id == exam.chapter_id).first()
        if chapter and all_sections:
            mastered_count = sum(1 for s in all_sections if s.is_mastered)
            chapter.progress_percentage = round(
                (mastered_count / len(all_sections)) * 100.0, 1
            )

        db.commit() if commit else db.flush()
        return {
            "session_id": exam.id,
            "total_score": exam.total_score,
            "max_score": exam.max_score,
            "accuracy_percent": round(exam.accuracy * 100, 1),
            "chapter_progress_percentage": chapter.progress_percentage if chapter else 0.0,
        }
