import json
from datetime import datetime, timedelta, timezone
import pytest
from database import SessionLocal, init_db
from models import ChapterSection, ExamSession, QuestionRecord
from services.llm_harness import HybridLLMHarness
from services.vision_grader import VisionSolutionGrader


def paper(seeded, mode='section_quiz'):
    with SessionLocal() as db:
        exam = ExamSession(chapter_id=seeded[0], mode=mode, status='in_progress', max_score=7,
            deadline_at=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
        db.add(exam); db.flush()
        rows = [QuestionRecord(session_id=exam.id, section_id=seeded[1][0], question_type=t, core_concept_tag='Practice',
            prompt_markdown=stem, correct_answer=key, options_json=opts, max_points=pts, ai_feedback_and_solution='Original teaching explanation.')
            for t, stem, key, opts, pts in [('mcq_multi','Which options fit?', 'A,C',json.dumps(dict(zip('ABCDE', ['one','two','three','four','five']))),4),
                ('short_answer','Explain your approach.', 'Use the definition.', None,1), ('calculation','Compute 2+2.', '4', None,2)]]
        db.add_all(rows); db.commit(); return exam.id, [q.id for q in rows]


@pytest.mark.parametrize('mode,selection,earned', [('section_quiz',['A','C'],4),('mock_test',['A'],2),('midterm',['B'],0),('final',[],0)])
def test_finish_without_uploads_and_review_each_option(client,seeded,monkeypatch,mode,selection,earned):
    eid, (mcq, short, calc) = paper(seeded,mode); url=f'/api/assessments/{eid}'
    assert client.post(url+'/choice-review',json={'question_ids':[mcq]}).status_code==409
    assert 'correct_options' not in client.get(url).json()['questions'][0]
    payload={'answers':[{'question_id':mcq,'user_answer':selection}]}
    result=client.post(url+'/finish',json=payload).json()
    assert (result['status'],result['total_score'],result['max_score'])==('completed',earned,7)
    assert result['questions'][0]['selected_options']==selection and 'Original teaching explanation.' in result['questions'][0]['ai_feedback_and_solution']
    assert all('Official solution' in q['ai_feedback_and_solution'] for q in result['questions'][1:])
    assert client.post(url+'/finish',json={'answers':[]}).json()['total_score']==earned
    original=client.get(url).json(); assert client.post(url+'/choice-review',json={'question_ids':[short]}).status_code==400
    assert client.post(url+'/choice-review',json={'question_ids':[mcq]}).status_code==503
    reasons={k:f'The condition for option {k} is distinct.' for k in 'ABCDE'}
    calls=[]
    async def model(messages,**kwargs):
        calls.append(json.loads(messages[1]['content'])); return {'content':json.dumps({str(mcq):reasons})}
    monkeypatch.setattr(HybridLLMHarness,'chat',model)
    for _ in range(2): assert client.post(url+'/choice-review',json={'question_ids':[mcq]}).json()=={str(mcq):reasons}
    assert len(calls)==1 and calls[0][str(mcq)]['correct']==['A','C'] and 'user_answer' not in calls[0][str(mcq)]
    reopened=client.get(url).json();assert reopened['questions'][0].pop('option_explanations')==reasons
    assert original['questions']==reopened['questions'] and original['total_score']==reopened['total_score']
    with SessionLocal() as db: assert db.get(ChapterSection,seeded[1][0]).quiz_attempts==1


def test_finished_paper_stays_locked_and_written_feedback_survives_retry(client,seeded,monkeypatch):
    eid, (mcq,short,calc)=paper(seeded);url=f'/api/assessments/{eid}'
    answers=[{'question_id':mcq,'user_answer':['A']},{'question_id':short,'user_answer':'my reasoning'},{'question_id':calc,'user_answer':'my steps'}]
    preview=client.post(url+'/finish',json={'answers':answers}).json()
    assert preview['status']=='submitted_grading' and preview['total_score']==2
    assert all(q['grading_pending'] and 'score_awarded' not in q for q in preview['questions'][1:])
    assert client.get(url).json()['status']=='submitted_retry'
    assert client.put(url+'/draft',json={'answers':[]}).status_code==409
    assert client.patch(url+'/timer',json={'is_paused':False,'time_spent_seconds':0,'enter_grace_upload':True}).status_code==409
    assert client.post(url+f'/questions/{calc}/paste-image',json={'image_base64':'AA=='}).status_code==409
    with SessionLocal() as db:
        db.get(ExamSession,eid).status='submitted_grading';db.commit()
    init_db();assert client.get(url).json()['status']=='submitted_retry'
    async def grade(prompt,answer,maximum,typed_answer,handwritten_image_path):
        return {'transcribed_student_work':typed_answer,'score_awarded':maximum-0.5,'ai_feedback_and_solution':'Personalized analysis: '+typed_answer}
    monkeypatch.setattr(VisionSolutionGrader,'grade_written_solution',grade)
    client.post(url+'/finish',json={'answers':[]})  # never replace the locked submission
    result=client.get(url).json();assert (result['status'],result['total_score'],result['max_score'])==('completed',4,7)
    assert [q['ai_feedback_and_solution'] for q in result['questions'][1:]]==['Personalized analysis: my reasoning','Personalized analysis: my steps']
    with SessionLocal() as db: assert db.get(ChapterSection,seeded[1][0]).quiz_attempts==1


def test_review_rejects_incomplete_option_reasons(client,seeded,monkeypatch):
    eid, (mcq,_,_)=paper(seeded);url=f'/api/assessments/{eid}';client.post(url+'/finish',json={'answers':[]})
    async def incomplete(**kwargs): return {'content':json.dumps({str(mcq):{'A':'Only one option covered.'}})}
    monkeypatch.setattr(HybridLLMHarness,'chat',incomplete)
    assert client.post(url+'/choice-review',json={'question_ids':[mcq]}).status_code==503
    assert 'option_explanations' not in client.get(url).json()['questions'][0]
