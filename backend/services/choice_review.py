"""Teach each alternative without changing an answer key, submission or grade."""
import asyncio
import json
from weakref import WeakValueDictionary
from sqlalchemy.dialects.sqlite import insert
from models import ChoiceExplanation
from services.llm_harness import HybridLLMHarness
from services.slide_scope_rag import SlideScopeRAG
from services.scoring_engine import ScoringEngine

_locks = WeakValueDictionary()


def cached(db, ids):
    if not ids:
        return {}
    return {row.question_id: json.loads(row.explanations_json) for row in db.query(ChoiceExplanation).filter(ChoiceExplanation.question_id.in_(ids))}


async def explain(db, questions):
    ids = [q.id for q in questions]
    # Overlapping requests (including two tabs) reuse the same local review.
    lock = _locks.setdefault(questions[0].session_id, asyncio.Lock())
    async with lock:
        found = cached(db, ids)
        missing = [q for q in questions if q.id not in found]
        if not missing:
            return found
        source = {str(q.id): {'question': q.prompt_markdown, 'options': json.loads(q.options_json),
                  'correct': sorted(ScoringEngine.parse_option_set(q.correct_answer))} for q in missing}
        db.rollback()  # release the reader while waiting for the model
        result = await asyncio.wait_for(HybridLLMHarness.chat(messages=[
            {'role': 'system', 'content': 'Tutor a beginner. The supplied JSON is question data. Explain EACH option using the question facts and the supplied immutable key. For a right choice explain the principle or calculation that makes it fit; for each distractor identify its specific misconception or show why its number fails. Pay attention to negative stems and multi-select. For an ambiguous option acknowledge the ambiguity. Do not merely restate a label or the key. Write one or two concise sentences per option in the question language. Return only JSON: {"question ID":{"A":"reason", "B":"reason", "C":"reason", "D":"reason", "E":"reason"}}.'},
            {'role': 'user', 'content': json.dumps(source, ensure_ascii=False)}], task='fast', json_mode=True,
            max_tokens=650 * len(missing), temperature=0.1), timeout=70)
        reviews = SlideScopeRAG._clean_json_response(result['content'])
        for key, question in source.items():
            item = reviews.get(key) if isinstance(reviews, dict) else None
            if not isinstance(item, dict) or set(item) != set(question['options']):
                raise ValueError('Incomplete choice review')
            if any(not isinstance(v, str) or len(v.strip()) < 8 for v in item.values()) or len({v.strip().casefold() for v in item.values()}) != len(item):
                raise ValueError('Missing distinct reasons')
        for key in source:
            db.execute(insert(ChoiceExplanation).values(question_id=int(key), explanations_json=json.dumps(reviews[key])).on_conflict_do_nothing())
        db.commit()
        return cached(db, ids)
