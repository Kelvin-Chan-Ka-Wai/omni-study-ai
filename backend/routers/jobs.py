"""Cancelable generation jobs. Results and status persist locally; interrupted jobs are marked on startup."""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import SessionLocal
from models import GenerationJob
from routers.ingestion import regenerate_structured_study_notes, RegenerateNotesRequest
from routers.assessment import generate_assessment, GenerateAssessmentRequest

router = APIRouter(prefix='/api/jobs', tags=['Generation progress'])
tasks = {}


class JobRequest(BaseModel):
    kind: str
    chapter_id: int
    section_ids: list[int]
    mode: str = 'section_quiz'


def set_state(job_id, **fields):
    with SessionLocal() as db:
        row = db.get(GenerationJob, job_id)
        if row:
            for key, value in fields.items(): setattr(row, key, value)
            db.commit()


async def run_job(job_id, req):
    set_state(job_id, status='running')
    try:
        with SessionLocal() as db:
            if req.kind == 'notes':
                result = await regenerate_structured_study_notes(req.chapter_id, RegenerateNotesRequest(section_ids=req.section_ids), db)
            else:
                result = await generate_assessment(GenerateAssessmentRequest(chapter_id=req.chapter_id, section_ids=req.section_ids, mode=req.mode), db)
        set_state(job_id, status='completed', result_json=json.dumps(result))
    except asyncio.CancelledError:
        set_state(job_id, status='canceled', message='Canceled. Previously saved work is preserved.')
    except Exception as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error) if isinstance(error, ValueError) else 'Generation unavailable. Check your provider and retry.'
        set_state(job_id, status='failed', message=detail)
    finally:
        tasks.pop(job_id, None)


@router.post('')
async def create_job(req: JobRequest):
    if req.kind not in ('notes', 'assessment') or not req.section_ids:
        raise HTTPException(400, 'Choose a generation type and at least one section')
    with SessionLocal() as db:
        if db.query(GenerationJob).filter(GenerationJob.chapter_id == req.chapter_id, GenerationJob.status.in_(['queued', 'running'])).first():
            raise HTTPException(409, 'Generation is already running for this chapter')
        job_id = uuid.uuid4().hex
        db.add(GenerationJob(id=job_id, chapter_id=req.chapter_id, kind=req.kind, status='queued'))
        db.commit()
    tasks[job_id] = asyncio.create_task(run_job(job_id, req))
    return {'job_id': job_id}


@router.get('/{job_id}')
def get_job(job_id: str):
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        if not job: raise HTTPException(404, 'Generation job not found')
        return {'id': job.id, 'status': job.status, 'message': job.message, 'result': json.loads(job.result_json) if job.result_json else None}


@router.delete('/{job_id}')
async def cancel_job(job_id: str):
    task = tasks.get(job_id)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return get_job(job_id)
