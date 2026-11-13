import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from database import SessionLocal, STORAGE_DIR
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, WrongQuestionBank, NoteVersion
from services.scoring_engine import ScoringEngine
from services.slide_scope_rag import SlideScopeRAG
from services.llm_harness import HybridLLMHarness


def test_wrong_mcq_retry_and_partial_credit(client, seeded):
    cid, ids = seeded
    with SessionLocal() as db:
        q = WrongQuestionBank(chapter_id=cid, section_id=ids[0], question_type='mcq_multi', core_concept_tag='Concept', prompt_markdown='Choose A and C', options_json=json.dumps({k:k for k in 'ABCDE'}), correct_answer='A,C')
        db.add(q);db.commit();qid=q.id
    for answer, streak in [(['A'],0), (['A','C'],1), (['A','C'],2), (['A','B'],0), (['A','C'],1)]:
        result=client.post(f'/api/wrong-bank/{qid}/attempt',json={'user_answer':answer})
        assert result.status_code==200,result.text
        assert result.json()['consecutive_correct_count']==streak
    assert ScoringEngine.grade_mcq_five_option(['A'],'A,C',4)['score_awarded']==2
    assert ScoringEngine.parse_option_set('because')==set()


def test_written_grader_outage_preserves_streak(client, seeded):
    cid,ids=seeded
    with SessionLocal() as db:
        q=WrongQuestionBank(chapter_id=cid,section_id=ids[0],question_type='calculation',core_concept_tag='C',prompt_markdown='Compute',correct_answer='12',consecutive_correct_count=2)
        db.add(q);db.commit();qid=q.id
    assert client.post(f'/api/wrong-bank/{qid}/attempt',json={'user_answer':'2'}).status_code==503
    with SessionLocal() as db: assert db.get(WrongQuestionBank,qid).consecutive_correct_count==2


def test_mutation_preserves_original(client, seeded, monkeypatch):
    cid,ids=seeded
    with SessionLocal() as db:
        q=WrongQuestionBank(chapter_id=cid,section_id=ids[0],question_type='calculation',core_concept_tag='C',prompt_markdown='Original',correct_answer='12')
        db.add(q);db.commit();qid=q.id
    async def twin(*a,**k): return {'prompt_markdown':'Twin','correct_answer':'24'}
    monkeypatch.setattr(SlideScopeRAG,'mutate_wrong_question',twin)
    result=client.post(f'/api/wrong-bank/{qid}/mutate')
    assert result.status_code==200,result.text
    assert result.json()['original_question']['prompt_markdown']=='Original'
    assert result.json()['mutation_generation']==1


def test_empty_and_foreign_selection_cannot_clear_or_regenerate(client,seeded):
    cid,ids=seeded
    for suffix in ('clear-notes','regenerate-notes'):
        for selection in ([],[999999]):
            assert client.post(f'/api/chapters/{cid}/{suffix}',json={'section_ids':selection}).status_code==400
    with SessionLocal() as db: assert db.get(ChapterSection,ids[0]).extracted_study_notes=='Notes 1'
    for selection in ('','invalid',str(ids[0])+',bad'):
        assert client.get(f'/api/export/chapter/{cid}',params={'fmt':'md','section_ids':selection}).status_code==400


def test_selected_export_clear_restore(client,seeded):
    cid,ids=seeded
    export=client.get(f'/api/export/chapter/{cid}',params={'fmt':'md','section_ids':str(ids[0])})
    assert export.status_code==200
    assert 'Notes 1' in export.text and 'Notes 2' not in export.text
    assert client.post(f'/api/chapters/{cid}/clear-notes',json={'section_ids':[ids[0]]}).status_code==200
    versions=client.get(f'/api/chapters/{cid}/sections/{ids[0]}/versions').json()
    assert client.post(f'/api/chapters/{cid}/sections/{ids[0]}/restore/{versions[0]["id"]}').status_code==200
    with SessionLocal() as db:
        assert db.get(ChapterSection,ids[0]).extracted_study_notes=='Notes 1'
        assert db.get(ChapterSection,ids[1]).extracted_study_notes=='Notes 2'


def make_exam(seeded, calculation=False):
    cid,ids=seeded
    with SessionLocal() as db:
        exam=ExamSession(chapter_id=cid,mode='section_quiz',time_limit_minutes=20,grace_period_minutes=5,deadline_at=(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),max_score=4,status='in_progress')
        db.add(exam);db.flush()
        q=QuestionRecord(session_id=exam.id,section_id=ids[0],question_type='calculation' if calculation else 'mcq_multi',core_concept_tag='C',prompt_markdown='Test',correct_answer='A,C',max_points=4,options_json=json.dumps({k:k for k in 'ABCDE'}))
        db.add(q);db.commit();return exam.id,q.id


def test_exam_draft_resume_and_idempotent_submit(client,seeded):
    eid,qid=make_exam(seeded)
    payload={'answers':[{'question_id':qid,'user_answer':['A','C']}],'time_spent_seconds':25}
    assert client.put(f'/api/assessments/{eid}/draft',json=payload).status_code==200
    active=client.get(f'/api/assessments/active/{seeded[0]}').json()
    assert active['draft_answers'][0]['user_answer']==['A','C']
    assert 'correct_answer' not in active['questions'][0]
    first=client.post(f'/api/assessments/{eid}/submit',json=payload)
    assert first.status_code==200,first.text
    second=client.post(f'/api/assessments/{eid}/submit',json=payload)
    assert first.json()==second.json()
    with SessionLocal() as db: assert db.get(ChapterSection,seeded[1][0]).quiz_attempts==1


def test_failed_grading_preserves_saved_answers(client,seeded):
    eid,qid=make_exam(seeded,True)
    payload={'answers':[{'question_id':qid,'user_answer':'work'}]}
    assert client.post(f'/api/assessments/{eid}/submit',json=payload).status_code==503
    state=client.get(f'/api/assessments/{eid}').json()
    assert state['status']=='in_progress'
    assert state['draft_answers'][0]['user_answer']=='work'
    with SessionLocal() as db: assert db.get(ChapterSection,seeded[1][0]).quiz_attempts==0


def test_expired_exam_cannot_replace_frozen_draft(client,seeded):
    eid,qid=make_exam(seeded)
    payload={'answers':[{'question_id':qid,'user_answer':['A']}]}
    client.put(f'/api/assessments/{eid}/draft',json=payload)
    with SessionLocal() as db:
        db.get(ExamSession,eid).deadline_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();db.commit()
    payload['answers'][0]['user_answer']=['A','C']
    assert client.put(f'/api/assessments/{eid}/draft',json=payload).status_code==409
    result=client.post(f'/api/assessments/{eid}/submit',json=payload)
    assert result.status_code==200,result.text
    assert result.json()['total_score']==2


def test_local_access_storage_and_origins(client,seeded):
    assert client.get('/api/chapters',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/chapters',headers={'Host':'evil.example'}).status_code==403
    for path in ('study_history.db','umpass_browser_profile/Default/Cookies','backups/test.db'):
        assert client.get('/storage/'+path).status_code==404
    assert client.get('/storage/uploads/test.md').status_code==200
    client.cookies.clear()
    assert client.get('/api/chapters').status_code==401


def test_exact_pages_never_expand_or_fallback():
    slides=[{'slide_number':i,'text':f'page {i}'} for i in range(1,9)]
    assert SlideScopeRAG._filter_slides_for_page_range(slides,'Slide 4')=='--- SLIDE 4 ---\npage 4'
    text=SlideScopeRAG._filter_slides_for_page_range(slides,'Slides 1-2, 7')
    assert 'page 7' in text and 'page 4' not in text
    for invalid in ('unknown','Slide 9','Slides 4-2'):
        with pytest.raises(ValueError): SlideScopeRAG._filter_slides_for_page_range(slides,invalid)


def test_backup_excludes_secrets_and_restore(client,seeded):
    import io,zipfile
    archive=client.get('/api/backup')
    assert archive.status_code==200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert 'study_history.db' in z.namelist()
        assert all(not any(w in p for w in ('.env','Cookies','profile','log')) for p in z.namelist())
    bad=io.BytesIO()
    with zipfile.ZipFile(bad,'w') as z:z.writestr('../.env','bad')
    assert client.post('/api/backup/restore',files={'backup':('bad.zip',bad.getvalue())}).status_code==400
    response=client.post('/api/backup/restore',files={'backup':('study.zip',archive.content)})
    assert response.status_code==200,response.text


def test_incomplete_paper_rejected():
    with pytest.raises(ValueError):SlideScopeRAG.validate_questions([],ScoringEngine.EXAM_BLUEPRINTS['section_quiz'],[])


def test_preserved_credential_files():
    backup=Path('/private/tmp/omnistudy-before-improvements')
    if not backup.exists():pytest.skip('Local credential preservation check only')
    root=Path(__file__).resolve().parents[2]
    for rel in ('backend/config.py','backend/services/llm_harness.py','backend/services/um_token_keeper.py','backend/routers/settings_router.py','frontend/src/components/layout/SettingsModal.tsx'):
        assert (root/rel).read_bytes()==(backup/rel).read_bytes(),rel
