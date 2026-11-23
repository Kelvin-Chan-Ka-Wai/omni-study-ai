from io import BytesIO
from secrets import token_hex
from pathlib import Path
from unittest.mock import AsyncMock

import pymupdf
import pytest
from pptx import Presentation
from pptx.util import Inches
from sqlalchemy import event

from database import STORAGE_DIR, SessionLocal
from models import ChapterSection
from routers import ingestion
from services.llm_harness import HybridLLMHarness
from services.scope import page_numbers
from services.slide_scope_rag import SlideScopeRAG


def pdf_bytes(*pages, encrypted=False):
    with pymupdf.open() as doc:
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_text((60, 60), text)
        if encrypted:
            return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=token_hex(12), user_pw=token_hex(12))
        return doc.tobytes()


def pptx_bytes():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(3), Inches(1)).text = 'Grouped heading'
    table = slide.shapes.add_table(1, 2, 0, Inches(1), Inches(3), Inches(1)).table
    table.cell(0, 0).text = 'Column A'
    table.cell(0, 1).text = 'Column B'
    deck.slides.add_slide(deck.slide_layouts[6])
    result = BytesIO()
    deck.save(result)
    return result.getvalue()


def onboard(client, name, raw, **optional):
    return client.post('/api/chapters/onboard', data={'course_name': '  Course ', 'chapter_title': ' Trial  '},
                       files={'slide_file': (name, raw), **optional})


@pytest.mark.parametrize('name, sample', [
    ('lecture.PDF', lambda: pdf_bytes('Capital $100', 'Market value')),
    ('lecture.pptx', pptx_bytes),
    ('lecture.md', lambda: b'\xef\xbb\xbf# Lecture\r\n\r\nEvidence'),
    ('lecture.txt', lambda: '講義\n\nEvidence'.encode('utf-16')),
])
def test_import_formats_offline_and_open_saved_chapter(client, monkeypatch, name, sample):
    provider = AsyncMock(side_effect=RuntimeError('AI provider is offline'))
    monkeypatch.setattr(HybridLLMHarness, 'chat', provider)
    raw = sample()
    result = onboard(client, name, raw, textbook_file=('extra.md', b'More context'), testbank_file=('quiz.txt', b'Sample question'))
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['course_name'] == 'Course' and data['chapter_title'] == 'Trial'
    assert data['total_slides_parsed'] == 2
    assert [pg for section in data['sections'] for pg in page_numbers(section['slide_pages'])] == [1, 2]
    assert all(not section['extracted_study_notes'] for section in data['sections'])
    chapter = client.get(f"/api/chapters/{data['chapter_id']}").json()
    assert client.get(chapter['slide_file_path']).content == raw
    assert client.get(chapter['textbook_file_path']).status_code == 200
    assert client.get(chapter['testbank_file_path']).status_code == 200
    provider.assert_not_awaited()
    pages = SlideScopeRAG.extract_slides_text(STORAGE_DIR / 'uploads' / Path(chapter['slide_file_path']).name)
    if name.endswith('PDF'):
        assert 'Capital $100' in pages[0]['text']
    elif name.endswith('.pptx'):
        assert 'Grouped heading' in pages[0]['text'] and 'Column A | Column B' in pages[0]['text']
        assert 'needs transcription' in data['sections'][1]['section_title']
    elif name.endswith('.md'):
        assert data['sections'][0]['section_title'] == 'Lecture'


@pytest.mark.parametrize('name, content, status, message', [
    ('empty.md', b'  \n', 422, 'no pages or text'),
    ('empty.pdf', b'', 422, 'file is empty'),
    ('unknown.docx', b'data', 400, 'choose a PDF'),
    ('damaged.pdf', b'invalid data', 422, 'Could not read this PDF'),
    ('damaged.pptx', b'invalid data', 422, 'Could not read this PPTX'),
    ('encoded.txt', b'\x8bhello', 422, 'UTF-8'),
    ('locked.pdf', pdf_bytes('Available after unlock', encrypted=True), 422, 'needs a password'),
])
def test_invalid_upload_rejected_without_artifacts(client, name, content, status, message):
    before = set(ingestion.UPLOAD_DIR.iterdir())
    response = onboard(client, name, content)
    assert response.status_code == status
    assert message in response.json()['detail']
    assert client.get('/api/chapters').json() == []
    assert set(ingestion.UPLOAD_DIR.iterdir()) == before


def test_late_optional_upload_error_rolls_back_staged_documents(client):
    before = set(ingestion.UPLOAD_DIR.iterdir())
    response = onboard(client, 'slides.md', b'Slides', textbook_file=('extra.md', b'Extra'),
                       testbank_file=('unreadable.pdf', b'Invalid file'))
    assert response.status_code == 422 and response.json()['detail'].startswith('Testbank:')
    assert client.get('/api/chapters').json() == []
    assert set(ingestion.UPLOAD_DIR.iterdir()) == before


def test_oversize_file_is_removed(client, monkeypatch):
    monkeypatch.setattr(ingestion, 'MAX_DOCUMENT_BYTES', 10)
    before = set(ingestion.UPLOAD_DIR.iterdir())
    response = onboard(client, 'long.txt', b'a' * 11)
    assert response.status_code == 413
    assert set(ingestion.UPLOAD_DIR.iterdir()) == before


def test_textbook_has_its_own_inclusive_size_limit(client, monkeypatch):
    monkeypatch.setattr(ingestion, 'MAX_DOCUMENT_BYTES', 10)
    monkeypatch.setattr(ingestion, 'MAX_TEXTBOOK_BYTES', 20)
    saved = onboard(client, 'slide.txt', b'lecture', textbook_file=('reference.txt', b'x' * 20))
    assert saved.status_code == 200, saved.text
    chapter = saved.json()['chapter_id']
    upload = client.get(f'/api/chapters/{chapter}').json()['textbook_file_path']
    assert client.get(upload).content == b'x' * 20

    before = set(ingestion.UPLOAD_DIR.iterdir())
    rejected = onboard(client, 'slide.txt', b'lecture', textbook_file=('reference.txt', b'x' * 21))
    assert rejected.status_code == 413 and rejected.json()['detail'].startswith('Textbook:')
    rejected = onboard(client, 'slide.txt', b'lecture', testbank_file=('questions.txt', b'x' * 11))
    assert rejected.status_code == 413 and rejected.json()['detail'].startswith('Testbank:')
    rejected = client.post(f'/api/chapters/{chapter}/upload-testbank', files={'testbank_file': ('questions.txt', b'x' * 11)})
    assert rejected.status_code == 413
    assert set(ingestion.UPLOAD_DIR.iterdir()) == before


def test_database_failure_does_not_leave_partial_chapter_or_files(client):
    def abort(*args):
        raise RuntimeError('Simulated database write failure')
    before = set(ingestion.UPLOAD_DIR.iterdir())
    event.listen(ChapterSection, 'before_insert', abort)
    try:
        with pytest.raises(RuntimeError, match='Simulated database write failure'):
            onboard(client, 'source.md', b'Study source')
    finally:
        event.remove(ChapterSection, 'before_insert', abort)
    assert client.get('/api/chapters').json() == []
    assert set(ingestion.UPLOAD_DIR.iterdir()) == before


def test_invalid_testbank_replacement_preserves_existing_attachment(client):
    result = onboard(client, 'source.md', b'Original scope', testbank_file=('exam.md', b'Original question'))
    old = result.json()['testbank_url']
    chapter = result.json()['chapter_id']
    failure = client.post(f'/api/chapters/{chapter}/upload-testbank', files={'testbank_file': ('damaged.pdf', b'bad')})
    assert failure.status_code == 422
    assert client.get(f'/api/chapters/{chapter}').json()['testbank_file_path'] == old
    assert client.get(old).content == b'Original question'


def test_visual_only_page_can_be_transcribed_and_other_sections_still_generate(client, monkeypatch):
    provider = AsyncMock(return_value={'content': 'A generated note'})
    monkeypatch.setattr(HybridLLMHarness, 'chat', provider)
    created = onboard(client, 'mixed.pdf', pdf_bytes('Readable fact', None, 'Another fact')).json()
    assert '1 slide page(s)' in created['warnings'][0]
    chapter = created['chapter_id']
    first, visual, third = [item['id'] for item in created['sections']]
    notes_url = f'/api/chapters/{chapter}/regenerate-notes'
    def notes(section):
        return client.post(notes_url, json={'section_ids': [section]})
    assert notes(first).status_code == 200
    rejected = notes(visual)
    assert rejected.status_code == 422 and 'slide page(s) 2' in rejected.json()['detail']
    assert client.post('/api/assessments/generate', json={'chapter_id': chapter, 'section_ids': [visual]}).status_code == 422
    assert client.put(f'/api/chapters/{chapter}/transcription', json={'page': 2, 'text': 'Verified diagram caption'}).status_code == 200
    assert notes(visual).status_code == 200
    assert 'Verified diagram caption' in provider.await_args.kwargs['messages'][-1]['content']
    with SessionLocal() as db:
        assert db.get(ChapterSection, third).extracted_study_notes == ''


def test_empty_ai_response_is_reported_and_old_notes_are_preserved(client, seeded, monkeypatch):
    provider = AsyncMock(return_value={'content': None})
    monkeypatch.setattr(HybridLLMHarness, 'chat', provider)
    chapter, (first, _) = seeded
    response = client.post('/api/jobs', json={'kind': 'notes', 'chapter_id': chapter, 'section_ids': [first]})
    assert response.status_code == 200
    from time import monotonic, sleep
    until = monotonic() + 3
    while monotonic() < until:
        job = client.get('/api/jobs/' + response.json()['job_id']).json()
        if job['status'] not in ('queued', 'running'):
            break
        sleep(.02)
    assert job['status'] == 'failed' and 'returned no notes' in job['message']
    with SessionLocal() as db:
        assert db.get(ChapterSection, first).extracted_study_notes == 'Notes 1'
