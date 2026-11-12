from database import init_db, SessionLocal
from models import Chapter, ChapterSection, ExamSession, QuestionRecord
from services.scoring_engine import ScoringEngine

def run_tests():
    init_db()
    db = SessionLocal()

    print("=== 1. Testing 5-Option MCQ Partial Credit Rule (Correct = A, C, E | Max = 3.0 pts) ===")
    for pick in ["A, C, E", "A, C", "A, B", ""]:
        res = ScoringEngine.grade_mcq_five_option(pick, "A, C, E", max_points=3.0)
        print(f"Pick {repr(pick):11} -> {res['score_awarded']}/{res['max_points']} pts ({res['status']})")

    print("\n=== 2. Testing Wrong Question Bank Auto-Capture & 3-Strike Graduation ===")
    ch = Chapter(course_name="Quantitative Risk Management", chapter_title="Ch 2: Extreme Value Theory")
    db.add(ch)
    db.commit()
    db.refresh(ch)

    sec1 = ChapterSection(chapter_id=ch.id, section_code="2.1", section_title="GEV Distribution", slide_pages="Slides 1-14")
    sec2 = ChapterSection(chapter_id=ch.id, section_code="2.2", section_title="Peaks Over Threshold", slide_pages="Slides 15-28")
    db.add_all([sec1, sec2])
    db.commit()

    exam = ExamSession(chapter_id=ch.id, mode="section_quiz", max_score=10.0)
    db.add(exam)
    db.commit()
    db.refresh(exam)

    # User gets partial credit (2/3 pts) on Sec 2.1 MCQ and 7/7 pts on Sec 2.1 Calc -> Total 9/10 (90% >= 80% Mastery)
    q1 = QuestionRecord(
        session_id=exam.id,
        section_id=sec1.id,
        question_type="mcq_multi",
        core_concept_tag="GEV Tail Index",
        prompt_markdown="Which tail properties hold?",
        correct_answer="A, C, E",
        user_answer="A, C",
        score_awarded=2.0,
        max_points=3.0,
    )
    q2 = QuestionRecord(
        session_id=exam.id,
        section_id=sec1.id,
        question_type="calculation",
        core_concept_tag="Hill Estimator",
        prompt_markdown="Compute the Hill estimator...",
        correct_answer="0.35",
        user_answer="0.35",
        score_awarded=7.0,
        max_points=7.0,
    )
    db.add_all([q1, q2])
    db.commit()

    wrong_item = ScoringEngine.sync_wrong_question_bank(db, ch.id, q1)
    print(f"Captured Wrong MCQ ID={wrong_item.id} | Initial Streak: {wrong_item.consecutive_correct_count}/3 ({wrong_item.status})")

    for attempt_ok in [True, True, False, True, True, True]:
        state = ScoringEngine.record_wrong_bank_review_attempt(db, wrong_item.id, is_correct=attempt_ok)
        print(f"Review Correct={str(attempt_ok):5} -> Badge: {state['badge']} | Status: {state['status']}")

    print("\n=== 3. Testing >= 80% Section Mastery & Chapter Progress (%) ===")
    summary = ScoringEngine.update_section_and_chapter_mastery(db, exam.id)
    db.refresh(sec1)
    db.refresh(sec2)
    print(f"Section 2.1 Accuracy: {sec1.best_accuracy*100:.0f}% | Mastered (>=80%): {sec1.is_mastered}")
    print(f"Section 2.2 Accuracy: {sec2.best_accuracy*100:.0f}% | Mastered (>=80%): {sec2.is_mastered}")
    print(f"Overall Chapter Progress (1 of 2 slide sections mastered): {summary['chapter_progress_percentage']}%")
    db.close()

if __name__ == "__main__":
    run_tests()
