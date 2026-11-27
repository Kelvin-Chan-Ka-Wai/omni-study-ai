"""Time limits and an offline, cited reading guide for a delayed note section."""
import asyncio
import re
from contextlib import contextmanager
from contextvars import ContextVar

from services.learning_sources import terms

# Leave time for SQLite, loading the chapter and the UI's next status poll.
NOTE_AI_SECONDS = 105
NOTE_WORKERS = 9
PAPER_WORKERS = 6


# A cold route check can take several seconds. Sibling model calls wait for the
# same check; the existing provider router owns the result, its TTL and all credentials.
_batch = ContextVar('generation_batch', default=None)


@contextmanager
def generation_batch():
    token = _batch.set(asyncio.Lock())
    try:
        yield
    finally:
        _batch.reset(token)


async def prepare_model_route():
    lock = _batch.get()
    if lock is not None:
        from services.llm_harness import HybridLLMHarness
        async with lock:
            await HybridLLMHarness.is_um_genai_alive()


def source_reading_guide(title, slides, excerpt):
    """Keep every scoped slide intact; pair it with a relevant, attributed reading where available."""
    sections = re.findall(r'^--- SLIDE (\d+) ---\n(.*?)(?=^--- SLIDE \d+ ---\n|\Z)', slides, re.M | re.S)
    if not sections:
        raise ValueError('No source slides are available for the reading guide.')
    readings = []
    for page, body in re.findall(r'^\[Textbook p\. (\d+)\]: (.*?)(?=^\[Textbook p\. \d+\]:|\Z)', excerpt, re.M | re.S):
        # Preserve the author's words and numbers. Omit headings and PDF fragments.
        for sentence in re.split(r'(?<=[.!?。！？])\s+', ' '.join(body.split())):
            if 45 <= len(sentence) <= 580 and sentence[-1] in '.!?。！？' and not re.search(r'\.{3,}', sentence):
                readings.append((page, sentence, terms(sentence)))
    title_words = terms(title)
    out = [f'## {title}', '> **Source reading guide.** The AI lesson did not finish in time. These are excerpts from your selected slides and matching textbook passages. Regenerate this section to request a worked AI explanation.']
    for n, raw in sections:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        out += [f'### Slide {n}', '\n'.join('> '+line+'  ' for line in lines)]
        words = terms(raw)
        candidates = [(len(t & words) + 2 * len(t & title_words), i) for i, (_, _, t) in enumerate(readings) if len(t & words) >= 2]
        if candidates:
            _, index = max(candidates, key=lambda pair: pair[0]); page, text, _ = readings.pop(index)
            out += [f'**Related reading (Textbook p. {page}):**', '> '+text]
    out += ['### Check your understanding', f'Cover the excerpts and explain {title} in your own words. Work through any example on the slides, then compare your reasoning with the cited material.']
    return '\n\n'.join(out)
