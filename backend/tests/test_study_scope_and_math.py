import re

import pymupdf
from database import SessionLocal
from models import ChapterSection, NoteVersion
from services.scope import page_numbers
from services.slide_outline import build_outline, review_slides
from services.slide_scope_rag import SlideScopeRAG
from services.study_math import normalize_study_math


def lecture_pdf():
    footer = '© Example Publisher'
    pages = [
        f'{footer}\nChapter 1\nIntroduction to Finance',
        f'{footer}\nChapter Outline\n1.1 Cash Flows\n1.2 Financing',
        f'{footer}\n1.1 Cash Flows\nA firm generates cash by selling assets.',
        f'{footer}\nCash Flow Example\nInvestors contribute $100.',
        f'{footer}\n1.2 Financing\nFirms can raise funds with debt.',
        f'{footer}\nQuestions?\nCalculate interest on $100 at 5%.',
        'Thank you',
        '© Example Publisher. All rights reserved.',
    ]
    with pymupdf.open() as document:
        for text in pages:
            document.new_page().insert_text((50, 50), text)
        return document.tobytes()


def test_import_reviews_topics_and_only_study_pages_reach_generator(client, monkeypatch):
    result = client.post('/api/chapters/onboard', data={'course_name': 'Finance', 'chapter_title': 'Chapter 1'},
                         files={'slide_file': ('lecture.pdf', lecture_pdf())})
    assert result.status_code == 200, result.text
    chapter = result.json()
    cid = chapter['chapter_id']
    review = client.get(f'/api/chapters/{cid}/slide-outline').json()
    assert not review['can_apply']
    assert [(s['section_title'], page_numbers(s['slide_pages'])) for s in review['sections']] == [
        ('1.1 Cash Flows', [3, 4]), ('1.2 Financing', [5, 6])]
    assert {p['page']: p['reason'] for p in review['excluded']} == {
        1: 'Opening cover', 2: 'Outline only', 7: 'Closing slide', 8: 'Publisher credits'}

    observed = []

    async def notes(**kwargs):
        observed.append((kwargs['slide_pages'], kwargs['section_slides_text']))
        return 'Generated notes'

    monkeypatch.setattr(SlideScopeRAG, 'generate_single_section_note_fast', notes)
    reply = client.post(f'/api/chapters/{cid}/regenerate-notes', json={'all_sections': True})
    assert reply.status_code == 200, reply.text
    prompt = '\n'.join(text for _, text in observed)
    assert set(re.findall(r'--- SLIDE (\d+) ---', prompt)) == {'3', '4', '5', '6'}
    assert 'Example Publisher' not in prompt and 'Calculate interest' in prompt


def test_review_of_existing_course_preserves_prior_notes_and_versions(client, seeded):
    cid, ids = seeded
    from database import STORAGE_DIR
    from models import Chapter
    (STORAGE_DIR / 'uploads' / 'legacy.pdf').write_bytes(lecture_pdf())
    with SessionLocal() as db:
        db.get(Chapter, cid).slide_file_path = '/storage/uploads/legacy.pdf'
        db.get(ChapterSection, ids[0]).slide_pages = 'Slides 1-4'
        db.get(ChapterSection, ids[1]).slide_pages = 'Slides 5-6'
        db.add(NoteVersion(section_id=ids[0], content='An earlier version', reason='regenerate'))
        db.commit()
    url = f'/api/chapters/{cid}/slide-outline'
    assert client.get(url).json()['can_apply']
    assert client.post(url).status_code == 200
    detail = client.get(f'/api/chapters/{cid}').json()
    assert [(s['slide_pages'], s['extracted_study_notes']) for s in detail['sections']] == [
        ('Slides 3-4', ''), ('Slides 5-6', 'Notes 2')]
    assert [(s['id'], s['extracted_study_notes']) for s in detail['archived_sections']] == [(ids[0], 'Notes 1')]
    assert client.get(f'/api/chapters/{cid}/sections/{ids[0]}/versions').json()[0]['reason'] == 'regenerate'
    assert client.post(f'/api/jobs', json={'kind': 'notes', 'chapter_id': cid, 'section_ids': [ids[0]]}).status_code == 400
    assert 'Notes 1' in client.get(f'/api/export/chapter/{cid}', params={'section_ids': str(ids[0])}).text
    assert not client.post(url).json()['can_apply']
    assert client.get(f'/api/chapters/{cid}').json()['sections'] == detail['sections']


def test_visual_and_verified_slides_are_retained_with_original_page_numbers():
    from services.documents import VISUAL_ONLY
    slides = review_slides([
        {'slide_number': 1, 'text': '1.1 Capital Budgeting\nCash flow matters.'},
        {'slide_number': 2, 'text': VISUAL_ONLY},
        {'slide_number': 3, 'text': '© Study Publisher'},
        {'slide_number': 4, 'text': 'Questions?\nA verified transcript', 'verified': True},
        {'slide_number': 5, 'text': 'Thank you'},
    ])
    assert [page_numbers(s['slide_pages']) for s in build_outline(slides)] == [[1], [2], [4]]
    assert slides[1]['excluded_reason'] is None


BROKEN_NOTE = (
    r'Investors put $\$100$ into the firm and get $\$110$ back.' '\n\n'
    r'Check: $\text{Cash Flows to Investors} = \$110 > \text{Cash Flows from Investors} = \$100$.'
)


def test_normalize_math_without_rewriting_code_or_ordinary_currency():
    sample = BROKEN_NOTE + '\n\n' + r'Code `$\$5$`; prose \$75; formula \(x^2\).' + '\n\n```tex\nx + 1\n```'
    clean = normalize_study_math(sample)
    assert r'put \$100 into the firm and get \$110 back' in clean
    assert r'\text{Cash Flows to Investors} = \text{\textdollar{}}110 >' in clean
    assert r'Code `$\$5$`; prose \$75; formula $x^2$.' in clean
    assert clean.endswith('$$\nx + 1\n$$')
    assert normalize_study_math(clean) == clean


def test_saved_note_renders_as_clean_markdown_and_pdf_without_regenerating(client, seeded):
    cid, ids = seeded
    with SessionLocal() as db:
        db.get(ChapterSection, ids[0]).extracted_study_notes = BROKEN_NOTE
        db.commit()
    note = client.get(f'/api/chapters/{cid}').json()['sections'][0]['extracted_study_notes']
    assert note == normalize_study_math(BROKEN_NOTE)
    assert note in client.get(f'/api/export/chapter/{cid}', params={'section_ids': str(ids[0])}).text
    pdf = client.get(f'/api/export/chapter/{cid}', params={'section_ids': str(ids[0]), 'fmt': 'pdf'})
    assert pdf.status_code == 200
    with pymupdf.open(stream=pdf.content, filetype='pdf') as document:
        text = ''.join(page.get_text() for page in document)
    assert 'Investors put $100 into the firm and get $110 back.' in text
    assert 'CashFlowstoInvestors=$110>CashFlowsfromInvestors=$100' in re.sub(r'\s+', '', text)
    with SessionLocal() as db:
        assert db.get(ChapterSection, ids[0]).extracted_study_notes == BROKEN_NOTE
