"""Exercise paper selection and history in an isolated database, without model calls."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from database import SessionLocal
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, QuestionSource
from services import slide_scope_rag as rag
from services.learning_sources import BankItem
from services.question_history import QuestionHistory, identity
from services.scoring_engine import ScoringEngine


def blueprint(kind):
    return {'total_points': 1, 'time_limit_minutes': 20, 'grace_period_minutes': 5,
            'distribution': {k: {'count': int(k == kind), 'points_each': 1} for k in ('mcq', 'short_answer', 'calculation')}}


def original(prompt):
    return {'question_type': 'short_answer', 'prompt_markdown': prompt, 'correct_answer': 'Example solution',
            'core_concept_tag': 'Topic', 'section_code': 'Section 1', 'slide_reference': 'Slide 1', 'max_points': 1}


def generate(client, seeded, mode):
    cid, sections = seeded
    return client.post('/api/assessments/generate', json={'chapter_id': cid, 'mode': mode, 'section_ids': [sections[0]]})


def test_bank_priority_then_retry_and_never_save_repeats(client, seeded, monkeypatch):
    stems = ['How does a deposit change the current balance?', 'Why might bondholders prefer a secured claim?']
    bank = [BankItem(str(i), 1, stem, list('ABCDE'), 'A', 'Topic 1', 'mcq') for i, stem in enumerate(stems)]
    with SessionLocal() as db:
        ch = db.get(Chapter, seeded[0]); ch.testbank_file_path = ch.slide_file_path; db.commit()
    monkeypatch.setattr(rag, 'bank_items', lambda path: bank)
    for mode in ('section_quiz', 'mock_test', 'midterm', 'final'):
        monkeypatch.setitem(ScoringEngine.EXAM_BLUEPRINTS, mode, blueprint('mcq' if mode == 'section_quiz' else 'short_answer'))
    first = generate(client, seeded, 'section_quiz'); assert first.status_code == 200, first.text
    first_stem = first.json()['questions'][0]['prompt_markdown']
    second = generate(client, seeded, 'mock_test'); assert second.status_code == 200, second.text
    adapted = second.json()['questions'][0]; assert adapted['prompt_markdown'].startswith(next(s for s in stems if s != first_stem))
    assert adapted['testbank_reference'] and '_source' not in adapted
    seen = []
    async def model(*args):
        seen.append(1)
        return [original('Trace the impact of seasonal inventory.' if len(seen) == 2 else first_stem)], 'offline', 'test'
    monkeypatch.setattr(rag.SlideScopeRAG, '_generate_question_batch', staticmethod(model))
    third = generate(client, seeded, 'midterm'); assert third.status_code == 200, third.text
    assert not third.json()['questions'][0]['testbank_reference'] and len(seen) == 2
    fourth = generate(client, seeded, 'final'); assert fourth.status_code == 422 and 'unused' in fourth.text
    with SessionLocal() as db:
        assert db.query(ExamSession).count() == 3 and db.query(QuestionSource).count() == 2
        assert QuestionHistory.load(db, '  TEST   course ').contains(identity(first_stem))
        assert not QuestionHistory.load(db, 'Another course').contains(identity(first_stem))


def test_identity_variants_and_legacy_unresolved_pages():
    opts = ['liability', 'asset', 'claim', 'stock', 'bond']
    stem = 'Which of the following statements is correct?'
    assert identity(stem, opts) == identity('3. '+stem+' (Select all that apply)', opts[::-1])
    assert identity(stem, opts) == identity(stem+'\n\n'+'\n'.join(f'{c}. {v}' for c,v in zip('ABCDE',opts))+'\n\nState your answer in words and explain why it is correct.')
    assert identity(stem, opts) != identity(stem, ['up', 'down'])
    pool = QuestionHistory(); pool.legacy[1] = [identity('An untraceable adapted problem')]; pool.legacy[2] = [identity('Define liquidity.')]
    bank = [BankItem('A',1,'Which claim is senior?', [], '', '', ''), BankItem('B',2,'What is liquidity?', [], '', '', '')]
    assert pool.untraceable_pages(bank) == {1}


def test_concurrent_generation_cannot_save_the_same_question(client, seeded, monkeypatch):
    barrier = threading.Barrier(2)
    async def simultaneous(**kwargs):
        await asyncio.to_thread(barrier.wait, 4)
        return {'questions': [original('Describe a permanent change in demand.')], 'blueprint': blueprint('short_answer'),
                'provider_used': 'offline', 'model_used': 'test'}
    monkeypatch.setattr(rag.SlideScopeRAG, 'generate_scoped_assessment', staticmethod(simultaneous))
    with ThreadPoolExecutor(2) as threads:
        replies = list(threads.map(lambda mode: generate(client,seeded,mode), ('final','section_quiz')))
    assert sorted(r.status_code for r in replies) == [200,409]
    with SessionLocal() as db:
        assert db.query(QuestionRecord).count() == db.query(ExamSession).count() == 1


def test_study_history_draft_coverage_and_original_section_labels(client, seeded, monkeypatch):
    a, b = seeded[1]
    async def paper(**kwargs):
        return {'questions': [original('Explain cash reserves.'), original('Define equity.')], 'blueprint': blueprint('short_answer'),
                'provider_used': 'offline', 'model_used': 'test'}
    monkeypatch.setattr(rag.SlideScopeRAG, 'generate_scoped_assessment', staticmethod(paper))
    gen = client.post('/api/assessments/generate',json={'chapter_id':seeded[0], 'mode':'mock_test', 'section_ids':[a,b]}).json()
    with SessionLocal() as db:
        h = db.get(ExamSession,gen['session_id']); h.draft_json = json.dumps([{'question_id':gen['questions'][1]['id'], 'corrected_transcription':'A handwritten answer'}]); s = db.get(ChapterSection,a); s.section_title = 'Different title now'; s.is_archived = True; db.commit()
    rows = client.get(f'/api/chapters/{seeded[0]}').json()['study_history'][0]['sections']
    assert [(s['id'], s['section_title'],s['slide_pages'],s['answered_count'],s['question_count']) for s in rows] == [(a,'Topic 1','Slide 1',1,2),(b,'Topic 2','Slide 2',0,0)]


def test_old_completed_attempt_uses_question_links_not_current_selection(client, seeded):
    a,b = seeded[1]
    with SessionLocal() as db:
        h = ExamSession(chapter_id=seeded[0], mode='section_quiz', status='completed'); db.add(h); db.flush()
        for sid, answer in [(b,'A'),(b,'(No answer submitted)'),(a,'[]')]:
            db.add(QuestionRecord(session_id=h.id, section_id=sid, question_type='short_answer', core_concept_tag='old', prompt_markdown='Legacy question', correct_answer='Example', user_answer=answer, max_points=1))
        db.get(ChapterSection,b).is_archived=True; db.commit()
    rows = client.get(f'/api/chapters/{seeded[0]}').json()['study_history'][0]['sections']
    assert {s['id']:(s['answered_count'], s['question_count']) for s in rows} == {a:(0,1), b:(1,2)}
