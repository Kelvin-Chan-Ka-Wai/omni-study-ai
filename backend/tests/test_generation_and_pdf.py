import asyncio
import json
import time
import pytest
from database import SessionLocal
from models import ChapterSection
from services.llm_harness import HybridLLMHarness
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


def test_mapping_visits_all_pages(monkeypatch):
    visited=[]
    async def mapping(messages,**kwargs):
        import re
        text=messages[-1]['content'];pages=[int(n) for n in re.findall(r'SLIDE (\d+):',text)];visited.extend(pages)
        return {'content':json.dumps({'sections':[{'section_title':'Topic','slide_pages':','.join(map(str,pages)),'extracted_study_notes':'evidence'}]})}
    monkeypatch.setattr(HybridLLMHarness,'chat',mapping)
    result=asyncio.run(SlideScopeRAG.map_slide_sections('Course','Chapter',[{'slide_number':i,'text':'facts'} for i in range(1,30)]))
    assert sorted(visited)==list(range(1,30))
    assert len(result)==4


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
