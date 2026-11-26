import json
import re
import time

import pytest
from database import SessionLocal, STORAGE_DIR
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, WrongQuestionBank
from services.slide_scope_rag import SlideScopeRAG
from services.learning_sources import BankItem, bank_plan
from services.scoring_engine import ScoringEngine


def deck(db,name,title,slides=None):
    ch=Chapter(course_name=name,chapter_title=title,slide_file_path=slides); db.add(ch); db.flush()
    s=ChapterSection(chapter_id=ch.id,section_code='Section 1',section_title=title,slide_pages='Slides 1-2'); db.add(s); db.flush()
    return ch.id,s.id


def record(db,cid,mode,status,parts):
    e=ExamSession(chapter_id=cid,mode=mode,status=status,total_score=sum(v for _,v,_ in parts),max_score=sum(p for _,_,p in parts)); db.add(e);db.flush()
    for sid,v,p in parts: db.add(QuestionRecord(session_id=e.id,section_id=sid,score_awarded=v,max_points=p,question_type='short_answer',core_concept_tag='test',prompt_markdown='Practice',correct_answer='ok'))
    db.flush();return e.id


def test_mastery_equal_attempts_boundary_pending_and_cross_deck(client,seeded):
    cid,(a,unseen)=seeded
    with SessionLocal() as db:
        bcid,b=deck(db,'  TEST    Course ','Next chapter'); other,foreign=deck(db,'Other course','Elsewhere')
        record(db,cid,'section_quiz','completed',[(a,10,10)]);record(db,cid,'section_quiz','completed',[(a,3,5)])
        record(db,cid,'final','submitted_retry',[(a,0,100)]);record(db,other,'midterm','completed',[(foreign,5,5)])
        eid=record(db,cid,'midterm','completed',[(a,9,10),(b,1,10)]);db.commit()
    detail=client.get(f'/api/chapters/{cid}').json();report=detail['course_progress'];quiz=report['modes']['section_quiz']; assert quiz==dict(attempts=2,average_percent=80,average_earned=6.5,average_possible=7.5,mastered=False)
    assert report['modes']['final']['average_percent'] is None and report['modes']['final']['awaiting_grade']==1 and report['modes']['midterm']['average_percent']==50
    assert {c['id'] for c in report['chapters']}=={cid,bcid};home,second=report['chapters']; assert home['modes']['midterm']['average_percent']==90 and second['modes']['midterm']['average_percent']==10
    active={s['id']:s for s in home['sections']};assert active[a]['overall']['mastered'] and not active[unseen]['overall']['attempts'];assert detail['progress_percentage']==50
    assert [h['session_id'] for h in client.get(f'/api/chapters/{bcid}').json()['study_history']]==[eid]
    assert '83.3333% average' in client.get(f'/api/export/chapter/{cid}?all_sections=true').text


@pytest.mark.parametrize('mode',['midterm','final'])
def test_real_job_builds_full_exam_with_only_the_requested_pages(client,seeded,monkeypatch,mode):
    cid,(a,_)=seeded
    with SessionLocal() as db:
        db.get(ChapterSection,a).slide_pages='Slides 1-2'
        ch,b=deck(db,'TEST COURSE','Other deck','/storage/uploads/deck-b.txt');db.commit()
    (STORAGE_DIR/'uploads/deck-b.txt').write_text('Exclude secret mountain example\n\nSelected ocean passage about currents and tides')
    seen=[]
    async def provider(course,title,context,block,instruction):
        assert 'Slide two different evidence' not in context and 'secret mountain' not in context
        assert ('Slide one original evidence' in context) != ('Selected ocean passage' in context)
        seen.append(context)
        m=re.search(r'exactly (\d+) (MCQs|short_answer|calculation).*?worth ([\d.]+) points',instruction); n,k,pts=m.groups();seq=len(seen)
        return [dict(question_type='mcq_single' if k=='MCQs' else k,prompt_markdown=f'Scenario {seq} variant {j}',correct_answer='A',max_points=float(pts),options=dict(zip('ABCDE','vwxyz')) if k=='MCQs' else None) for j in range(int(n))],'offline','fixture'
    monkeypatch.setattr(SlideScopeRAG,'_generate_question_batch',staticmethod(provider))
    data={'kind':'assessment','chapter_id':cid,'mode':mode,'section_ids':[a,b],'exam_pages':{str(a):'1',str(b):'2'}}
    start=client.post('/api/jobs',json=data); assert start.status_code==200,start.text
    for _ in range(100):
        state=client.get('/api/jobs/'+start.json()['job_id']).json()
        if state['status'] not in ('running','queued'):break
        time.sleep(.02)
    assert state['status']=='completed',state.get('message');q=state['result']['questions'];assert len(q)==29 and sum(row['max_points'] for row in q)==100 and {r['section_id'] for r in q}=={a,b}
    assert {v['slide_reference'] for v in q}=={'Test chapter · Slide 1','Other deck · Slide 2'}
    h=client.get(f'/api/chapters/{ch}').json()['study_history'][0];assert {s['slide_pages'] for s in h['sections']}=={'Slide 1','Slide 2'}
    for bad in [dict(mode='mock_test'),dict(exam_pages={str(a):'3',str(b):'1'}),dict(section_ids=[b])]: assert client.post('/api/jobs',json={**data,**bad}).status_code==400
    with SessionLocal() as db:
        db.get(Chapter,ch).course_name='Different course';db.commit()
    assert client.post('/api/assessments/generate',json=data).status_code==400


def test_bank_from_one_deck_cannot_take_another_decks_only_slot():
    secs=[dict(section_code=k,section_title='Bond Pricing',source_text='coupon rates prices') for k in ('D1','D2')]
    bank=[BankItem(str(i),1,'Which coupon rate fits '+str(i)+'?',list('ABCDE'),'A','Bond Pricing','mcq') for i in range(5)]
    dist={k:dict(count=int(k=='mcq')*2) for k in ('mcq','short_answer','calculation')}
    plan=bank_plan(bank,secs,dist,allowed={i.id:{'D1'} for i in bank},cover_all=True)
    assert len(plan['mcq'])==1 and plan['mcq'][0][0]=='D1'


def test_shared_wrong_bank_filters_exports_and_review_stays_on_original(client,seeded):
    cid,(a,_)=seeded
    with SessionLocal() as db:
        ch,b=deck(db,' Test  COURSE ','Options');foreign,c=deck(db,'Other','Private');ids=[]
        for owner,sid,title in [(cid,a,'alpha'),(ch,b,'beta'),(foreign,c,'gamma')]:
            row=WrongQuestionBank(chapter_id=owner,section_id=sid,core_concept_tag='Topic',question_type='mcq_single',prompt_markdown=title,correct_answer='A',status='active',consecutive_correct_count=2);db.add(row);db.flush();ids.append(row.id)
        db.commit()
    for anchor in (cid,ch):
        rows=client.get(f'/api/wrong-bank/{anchor}?scope=course').json(); assert {r['prompt_markdown'] for r in rows}=={'alpha','beta'};assert {r['chapter_title'] for r in rows}=={'Test chapter','Options'}
        doc=client.get(f'/api/export/wrong-bank/{anchor}?scope=course').text;assert all(x in doc for x in ('alpha','beta','Options','all chapters')) and 'gamma' not in doc
    assert len(client.get(f'/api/wrong-bank/{cid}').json())==1
    assert client.post(f'/api/wrong-bank/{ids[1]}/attempt',json={'user_answer':'A'}).json()['status']=='graduated'
    assert [r['id'] for r in client.get(f'/api/wrong-bank/{cid}?scope=course&status=graduated').json()]==[ids[1]]
    with SessionLocal() as db: assert db.get(WrongQuestionBank,ids[1]).chapter_id==ch and db.query(WrongQuestionBank).count()==3
