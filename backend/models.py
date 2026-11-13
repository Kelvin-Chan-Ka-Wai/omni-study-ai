from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, index=True)
    course_name = Column(String(255), nullable=False, index=True)
    chapter_title = Column(String(255), nullable=False)
    slide_file_path = Column(String(512), nullable=True)
    textbook_file_path = Column(String(512), nullable=True)
    testbank_file_path = Column(String(512), nullable=True)
    progress_percentage = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)

    sections = relationship("ChapterSection", back_populates="chapter", cascade="all, delete-orphan")
    exam_sessions = relationship("ExamSession", back_populates="chapter", cascade="all, delete-orphan")
    wrong_questions = relationship("WrongQuestionBank", back_populates="chapter", cascade="all, delete-orphan")

class ChapterSection(Base):
    __tablename__ = "chapter_sections"

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    section_code = Column(String(64), nullable=False)
    section_title = Column(String(255), nullable=False)
    slide_pages = Column(String(128), nullable=True)
    extracted_study_notes = Column(Text, nullable=True)
    best_accuracy = Column(Float, default=0.0)
    latest_accuracy = Column(Float, default=0.0)
    quiz_attempts = Column(Integer, default=0)
    is_mastered = Column(Boolean, default=False)

    chapter = relationship("Chapter", back_populates="sections")
    question_records = relationship("QuestionRecord", back_populates="section")

class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String(32), nullable=False)
    selected_section_ids_json = Column(Text, nullable=True)
    time_limit_minutes = Column(Integer, default=120)
    grace_period_minutes = Column(Integer, default=5)
    time_spent_seconds = Column(Integer, default=0)
    is_paused = Column(Boolean, default=False)
    status = Column(String(32), default="in_progress")
    total_score = Column(Float, default=0.0)
    max_score = Column(Float, default=100.0)
    accuracy = Column(Float, default=0.0)
    started_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
    draft_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    deadline_at = Column(String(64), nullable=True)
    paused_remaining = Column(Float, nullable=True)
    grace_started_at = Column(String(64), nullable=True)

    chapter = relationship("Chapter", back_populates="exam_sessions")
    questions = relationship("QuestionRecord", back_populates="session", cascade="all, delete-orphan")

class QuestionRecord(Base):
    __tablename__ = "question_records"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("exam_sessions.id", ondelete="CASCADE"), nullable=False)
    section_id = Column(Integer, ForeignKey("chapter_sections.id", ondelete="SET NULL"), nullable=True)
    question_type = Column(String(32), nullable=False)
    core_concept_tag = Column(String(255), nullable=False)
    slide_reference = Column(String(128), nullable=True)
    prompt_markdown = Column(Text, nullable=False)
    options_json = Column(Text, nullable=True)
    correct_answer = Column(Text, nullable=False)
    user_answer = Column(Text, nullable=True)
    handwritten_image_path = Column(String(512), nullable=True)
    score_awarded = Column(Float, default=0.0)
    max_points = Column(Float, nullable=False)
    ai_feedback_and_solution = Column(Text, nullable=True)
    is_flagged_wrong = Column(Boolean, default=False)

    session = relationship("ExamSession", back_populates="questions")
    section = relationship("ChapterSection", back_populates="question_records")

class WrongQuestionBank(Base):
    __tablename__ = "wrong_question_bank"

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    section_id = Column(Integer, ForeignKey("chapter_sections.id", ondelete="SET NULL"), nullable=True)
    source_question_id = Column(Integer, ForeignKey("question_records.id", ondelete="SET NULL"), nullable=True)
    question_type = Column(String(32), nullable=False)
    core_concept_tag = Column(String(255), nullable=False)
    slide_reference = Column(String(128), nullable=True)
    prompt_markdown = Column(Text, nullable=False)
    options_json = Column(Text, nullable=True)
    correct_answer = Column(Text, nullable=False)
    user_wrong_answer = Column(Text, nullable=True)
    handwritten_image_path = Column(String(512), nullable=True)
    ai_diagnosis_and_solution = Column(Text, nullable=True)
    consecutive_correct_count = Column(Integer, default=0)
    total_review_attempts = Column(Integer, default=0)
    mutation_generation = Column(Integer, default=0)
    original_json = Column(Text, nullable=True)
    variant_history_json = Column(Text, nullable=True)
    next_review_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="active")
    created_at = Column(DateTime, default=utc_now)
    last_reviewed_at = Column(DateTime, default=utc_now)

    chapter = relationship("Chapter", back_populates="wrong_questions")


class NoteVersion(Base):
    __tablename__ = "note_versions"
    id = Column(Integer, primary_key=True)
    section_id = Column(Integer, ForeignKey("chapter_sections.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    reason = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=utc_now)


class SlideTranscription(Base):
    __tablename__ = "slide_transcriptions"
    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    page = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)


class GenerationJob(Base):
    __tablename__ = 'generation_jobs'
    id = Column(String(64), primary_key=True)
    chapter_id = Column(Integer, ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
