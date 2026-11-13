import os
import sys
import tempfile
from pathlib import Path

os.environ['OMNISTUDY_STORAGE_DIR'] = tempfile.mkdtemp(prefix='omnistudy-tests-')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from main import app
from database import Base, engine, SessionLocal, init_db
from services.llm_harness import HybridLLMHarness
from config import settings


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    Base.metadata.drop_all(engine)
    init_db()
    # No test may use real credentials or make live model calls.
    for key in ('OPEN_WEBUI_API_KEY','DEEPSEEK_API_KEY','OPENAI_API_KEY','UMPASS_USERNAME','UMPASS_PASSWORD'):
        monkeypatch.setattr(settings, key, '')
    async def unavailable(*args, **kwargs): raise RuntimeError('Mock provider unavailable')
    monkeypatch.setattr(HybridLLMHarness, 'chat', unavailable)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app, base_url='http://127.0.0.1') as client:
        client.get('/api/session')
        yield client


@pytest.fixture
def seeded():
    from models import Chapter, ChapterSection
    from database import STORAGE_DIR
    source = STORAGE_DIR / 'uploads' / 'test.md'
    source.parent.mkdir(exist_ok=True)
    source.write_text('Slide one original evidence\n\nSlide two different evidence')
    with SessionLocal() as db:
        chapter = Chapter(course_name='Test course', chapter_title='Test chapter', slide_file_path='/storage/uploads/test.md')
        db.add(chapter);db.flush()
        sections = [ChapterSection(chapter_id=chapter.id, section_code=f'Section {i}', section_title=f'Topic {i}', slide_pages=f'Slide {i}', extracted_study_notes=f'Notes {i}') for i in (1,2)]
        db.add_all(sections);db.commit()
        return chapter.id, [s.id for s in sections]
