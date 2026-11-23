import asyncio
from database import SessionLocal
from models import ChapterSection
from services.scope import page_numbers
from services.slide_scope_rag import SlideScopeRAG


def test_cancel_generation_preserves_notes(client, seeded, monkeypatch):
    async def slow(*a, **k):
        await asyncio.sleep(60)
        return 'Replacement'
    monkeypatch.setattr(SlideScopeRAG,'generate_single_section_note_fast',slow)
    cid,ids=seeded
    result=client.post('/api/jobs',json={'kind':'notes','chapter_id':cid,'section_ids':[ids[0]]})
    assert result.status_code==200,result.text
    jid=result.json()['job_id']
    canceled=client.delete('/api/jobs/'+jid)
    assert canceled.status_code==200,canceled.text
    assert canceled.json()['status']=='canceled'
    with SessionLocal() as db:assert db.get(ChapterSection,ids[0]).extracted_study_notes=='Notes 1'


def test_selected_regeneration_uses_original_source(client,seeded,monkeypatch):
    observed=[]
    async def notes(**kwargs):
        observed.append(kwargs['section_slides_text']);return 'Updated section one'
    monkeypatch.setattr(SlideScopeRAG,'generate_single_section_note_fast',notes)
    cid,ids=seeded
    result=client.post(f'/api/chapters/{cid}/regenerate-notes',json={'section_ids':[ids[0]]})
    assert result.status_code==200,result.text
    assert observed==['--- SLIDE 1 ---\nSlide one original evidence']
    with SessionLocal() as db:
        assert db.get(ChapterSection,ids[1]).extracted_study_notes=='Notes 2'


def test_local_mapping_covers_all_pages_once():
    pages = [{'slide_number': i, 'text': 'facts'} for i in range(1, 30)]
    result = SlideScopeRAG.map_slide_sections(pages)
    assert [page for section in result for page in page_numbers(section['slide_pages'])] == list(range(1, 30))
    assert all(len(page_numbers(section['slide_pages'])) <= 5 for section in result)


def test_actual_pdf_download(client,seeded):
    cid,ids=seeded
    with SessionLocal() as db:
        db.get(ChapterSection,ids[0]).extracted_study_notes='Verified formula: $x^2 + y^2 = z^2$\n\n<script>throw new Error("unsafe")</script>';db.commit()
    response=client.get(f'/api/export/chapter/{cid}',params={'fmt':'pdf','section_ids':str(ids[0])})
    assert response.status_code==200,response.text[:1000]
    assert response.headers['content-type']=='application/pdf'
    assert response.content.startswith(b'%PDF-')
    import pymupdf
    pdf=pymupdf.open(stream=response.content,filetype='pdf')
    assert len(pdf)>=1
    assert 'Notes 2' not in ''.join(p.get_text() for p in pdf)


def test_note_deadline_covers_queue_and_preserves_existing_lesson(client, seeded, monkeypatch):
    from services import generation_pacing as pacing
    from database import STORAGE_DIR
    from models import Chapter, NoteVersion
    cid, ids = seeded
    book = STORAGE_DIR / 'uploads' / 'reference.txt'
    book.write_text('Original evidence and different evidence can each be checked against the stated findings.')
    with SessionLocal() as db:
        db.get(Chapter, cid).textbook_file_path = '/storage/uploads/reference.txt'
        db.get(ChapterSection, ids[1]).extracted_study_notes = ''
        db.commit()
    started = []
    async def stalled(**kwargs):
        started.append(kwargs['section_code'])
        await asyncio.Event().wait()
    monkeypatch.setattr(SlideScopeRAG, 'generate_single_section_note_fast', stalled)
    monkeypatch.setattr(pacing, 'NOTE_AI_SECONDS', .1)
    monkeypatch.setattr(pacing, 'NOTE_WORKERS', 1)
    result = client.post(f'/api/chapters/{cid}/regenerate-notes', json={'section_ids': ids}).json()
    assert len(started) == 1 and result['kept_section_ids'] == ids[:1]
    assert result['source_guide_section_ids'] == result['regenerated_section_ids'] == ids[1:]
    with SessionLocal() as db:
        assert db.get(ChapterSection, ids[0]).extracted_study_notes == 'Notes 1'
        assert not db.query(NoteVersion).filter_by(section_id=ids[0]).count()
        guide = db.get(ChapterSection, ids[1]).extracted_study_notes
        assert 'Slide 2' in guide and 'Slide two different evidence' in guide
        assert 'Textbook p. 1' in guide and 'Original evidence and different' in guide
        assert 'Slide one original evidence' not in guide


def test_cached_reference_replacement_at_same_path(tmp_path):
    import os
    from services.learning_sources import textbook_index, bank_items
    book = tmp_path / 'reference.txt'
    book.write_text('Demand falls as price increases.')
    index = textbook_index(book)
    assert textbook_index(book) is index
    new_book = tmp_path / 'replacement.txt'
    new_book.write_text('Supply rises as price increases.')
    os.replace(new_book, book)
    changed = textbook_index(book)
    assert changed is not index and 'Supply rises' in changed.excerpt('supply', 'supply and price')
    bank = tmp_path / 'questions.txt'
    bank.write_text('1. Explain market demand.\nAnswer: A demand schedule.')
    assert 'demand' in bank_items(bank)[0].stem
    bank.write_text('1. Explain market supply.\nAnswer: A supply schedule.')
    assert 'supply' in bank_items(bank)[0].stem
