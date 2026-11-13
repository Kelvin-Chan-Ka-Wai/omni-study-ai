import asyncio
from datetime import datetime,timezone,timedelta
import pytest
from database import SessionLocal
from models import ExamSession,ChapterSection
from services.vision_grader import VisionSolutionGrader
from test_reliability import make_exam


def test_concurrent_submit_grades_once(client,seeded,monkeypatch):
    eid,qid=make_exam(seeded,True)
    calls=[]
    async def grade(*a,**k):
        calls.append(1);await asyncio.sleep(.05)
        return {'transcribed_student_work':'4','score_awarded':4,'ai_feedback_and_solution':'Correct'}
    monkeypatch.setattr(VisionSolutionGrader,'grade_written_solution',grade)
    payload={'answers':[{'question_id':qid,'user_answer':'4'}]}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:client.post(f'/api/assessments/{eid}/submit',json=payload).status_code,range(2)))
    assert sorted(results) in ([200,409],[200,200])
    assert len(calls)==1
    with SessionLocal() as db:assert db.get(ChapterSection,seeded[1][0]).quiz_attempts==1


def test_timer_pause_and_grace(client,seeded):
    eid,qid=make_exam(seeded)
    pause=client.patch(f'/api/assessments/{eid}/timer',json={'is_paused':True,'time_spent_seconds':0})
    assert pause.status_code==200,pause.text
    assert pause.json()['is_paused'] is True
    assert pause.json()['paused_remaining']>1100
    resume=client.patch(f'/api/assessments/{eid}/timer',json={'is_paused':False,'time_spent_seconds':0})
    assert resume.status_code==200
    grace=client.patch(f'/api/assessments/{eid}/timer',json={'is_paused':False,'time_spent_seconds':0,'enter_grace_upload':True})
    assert grace.status_code==200
    assert grace.json()['status']=='grace_upload'
    assert client.put(f'/api/assessments/{eid}/draft',json={'answers':[]}).status_code==409
