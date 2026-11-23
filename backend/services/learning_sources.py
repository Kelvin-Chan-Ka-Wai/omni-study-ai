"""Page-preserving lookup for textbook explanations and individual bank questions."""
import math
import re
from functools import lru_cache
from random import SystemRandom
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from services.documents import DocumentReadError, read_pages
from services.scope import page_numbers


_STOP = set('about after also answer based before between chapter choose could correct current following from given have into lecture most notes option page pages question section select should slide slides some such than that their them then there these they this those under using what when where which while with would'.split())


def terms(text):
    words = re.findall(r'[^\W\d_]{2,}', text.casefold(), re.UNICODE)
    result = set()
    for word in words:
        if re.fullmatch(r'[\u3400-\u9fff]+', word):
            result.update(word[i:i + 2] for i in range(len(word) - 1))
        elif word not in _STOP:
            result.add(word[:-1] if len(word) > 4 and word.endswith('s') and not word.endswith('ss') else word)
    return result


def passages(path, size=1800):
    chunks = []
    page = 0
    for page, text in enumerate(read_pages(Path(path)), 1):
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                split = max(text.rfind('\n', start + size // 2, end), text.rfind(' ', start + size // 2, end))
                if split > start:
                    end = split + 1
            if excerpt := text[start:end].strip():
                chunks.append({'page': page, 'text': excerpt})
            start = end
    if not page:
        raise DocumentReadError("The document is empty. Choose a file with content.")
    return chunks


def textbook_citations(text):
    """Expand page lists and ranges so every cited page can be checked, not only the first."""
    pattern = r'\btextbook(?:\s+ref)?\s*[,:(]?\s*(?:pp?|pages?)\.?\s*(\d+(?:\s*(?:[-–—,;]|\band\b)\s*\d+)*)'
    pages = set()
    for spec in re.findall(pattern, text, re.I):
        try:
            pages.update(page_numbers(re.sub(r'\band\b', ',', spec, flags=re.I)))
        except ValueError:
            return {-1}
    return pages


class TextbookIndex:
    def __init__(self, chunks):
        self.entries = [(c, terms(c['text'])) for c in chunks]
        counts = Counter(w for _, words in self.entries for w in words)
        self.weight = {w: math.log1p((len(chunks) + 1) / (n + 1)) for w, n in counts.items()}

    def excerpt(self, title, evidence, limit=4):
        title_terms, body_terms = terms(title), terms(evidence)
        ranked = []
        for i, (chunk, words) in enumerate(self.entries):
            names, detail = title_terms & words, body_terms & words
            if not (len(names | detail) >= 2 or (len(title_terms) == 1 and names)):
                continue
            score = sum(self.weight[t] for t in names) * 3 + sum(self.weight[t] for t in detail)
            if title_terms and title_terms <= words:
                score *= 1.35
            if re.search(r'\.{4,}', chunk['text']) or len(chunk['text'].strip()) < 60:
                score *= .6
            ranked.append((score, i, chunk))
        if not ranked:
            return ''
        ranked.sort(key=lambda row: (-row[0], row[1]))
        best, _, anchor = ranked[0]
        # Prefer nearby passages in the same topic over distant mentions in the index or exercises.
        chosen = sorted((row for row in ranked if row[0] >= best * .48), key=lambda row: -(row[0] * (1.45 if abs(row[2]['page'] - anchor['page']) <= 2 else 1)))[:limit]
        return '\n\n'.join(f"[Textbook p. {c['page']}]: {c['text']}" for _, _, c in sorted(chosen, key=lambda row: row[1]))


def _file_version(path):
    path = Path(path).resolve()
    st = path.stat()
    return path, st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


@lru_cache(maxsize=1)
def _indexed_book(version):
    return TextbookIndex(passages(version[0]))


def textbook_index(path):
    return _indexed_book(_file_version(path))


@dataclass
class BankItem:
    id: str
    page: int
    stem: str
    options: list
    answer: str
    topic: str
    kind: str


_NUM = re.compile(r'^\s*(?:#{1,6}\s*)?(?:Q(?:uestion)?\s*)?(\d{1,4})[.):](?!\d)\s*', re.I)
_OPT = re.compile(r'^\s*\(?([A-E])[.):]\s*(\S.*)$', re.I)
_KEY = re.compile(r'^(?:correct\s+answer|answer(?:\s+key)?)\s*:\s*(.+)', re.I)
_CALC = re.compile(r'\b(?:calculate|compute|derive|how much|how many|what (?:is|was|will be) the (?:present|future) value)\b', re.I)


def _publisher_page(page):
    """Connect-export PDFs overlay answer marks separately from the question text."""
    blocks = sorted(page.get_text('blocks'), key=lambda b: (b[1], b[0]))
    icons = [b for b in blocks if b[4].strip() in ('\uea56', '\uea57\uea56')]
    if not icons:
        return []
    result, last = [], -1
    for meta in blocks:
        topic = re.search(r'(?m)^Section:\s*(.+)', meta[4])
        if not topic or 'Multiple Choice' not in meta[4]:
            continue
        marks = [b for b in icons if last < b[1] < meta[1]]
        if 2 <= len(marks) <= 5:
            ref = next((b for b in blocks if marks[-1][1] < b[1] < meta[1] and b[4].strip() == 'References'), meta)
            content = [b for b in blocks if last < b[1] < ref[1] and b[0] >= marks[0][0]-40
                       and b not in marks and 'Award:' not in b[4] and not re.search(r'[\ue000-\uf8ff]', b[4])]
            def text(start, end):
                return ' '.join(' '.join(b[4].split()) for b in content if start <= b[1] < end)
            stem = text(last, marks[0][1]-3)
            options = [text(b[1]-3, marks[i+1][1]-3 if i+1 < len(marks) else ref[1]) for i,b in enumerate(marks)]
            keys = [chr(65+i) for i,b in enumerate(marks) if '\uea57' in b[4]]
            if stem and all(options):
                result.append((stem, options, ','.join(keys), topic[1]))
        last = meta[1]
    return result


def bank_items(path):
    return _parsed_bank(_file_version(path))


@lru_cache(maxsize=4)
def _parsed_bank(version):
    path = version[0]
    items, seen = [], set()
    path = Path(path)
    layouts = {}
    if path.suffix.lower() == '.pdf':
        import pymupdf
        with pymupdf.open(path) as pdf:
            for n, page in enumerate(pdf, 1):
                if 'Multiple Choice' in page.get_text() and (records := _publisher_page(page)):
                    layouts[n] = records
    def add(page, lines, topic='', publisher=False):
        lines = [line for line in lines if line.strip()]
        if not lines:
            return
        stem, options, key = [], [], ''
        if publisher and len(lines) == 6 and not any(_OPT.match(line) for line in lines[1:]):
            stem, options = lines[:1], lines[1:]
        else:
            for line in lines:
                if match := _KEY.match(line):
                    key = match[1]; break
                if match := _OPT.match(line):
                    if match[1].upper() != chr(65 + len(options)):
                        return
                    options.append(match[2]); continue
                if options:
                    options[-1] += ' ' + line
                else:
                    stem.append(line)
            if publisher and not options:
                return  # Broken PDF option layout cannot be safely reconstructed.
        stem = ' '.join(stem).strip()
        identity = ' '.join(stem.casefold().split())
        if len(stem) < 8 or len(stem) > 1900 or identity in seen or len(' '.join(options)) > 3500:
            return
        seen.add(identity)
        kind = 'mcq' if options else 'calculation' if _CALC.search(stem) else 'short_answer'
        items.append(BankItem(f'B{len(items)+1}', page, stem, options, key, topic, kind))

    pending, start = [], 0
    for page, raw in enumerate(read_pages(Path(path)), 1):
        lines = [s.strip() for s in raw.splitlines() if s.strip()]
        if any(s.startswith('Section:') for s in lines) and 'References' in lines and any('Multiple Choice' in s for s in lines):
            add(start, pending); pending = []
            for stem, options, key, topic in layouts.get(page, []):
                add(page, [stem, *(f'{chr(65+i)}. {o}' for i,o in enumerate(options)), f'Answer: {key}'] if key
                    else [stem, *(f'{chr(65+i)}. {o}' for i,o in enumerate(options))], topic)
            block, meta = [], False
            for line in lines:
                if line.startswith('Section:'):
                    add(page, block, line.partition(':')[2].strip(), publisher=True)
                    block, meta = [], False
                elif line == 'References':
                    meta = True
                elif not meta and not re.match(r'^(?:\d+\.|Award:.*)$', line):
                    block.append(line)
            continue
        for line in lines:
            numbered = _NUM.match(line)
            if numbered:
                add(start, pending); pending, start = [line[numbered.end():]], page
            elif pending and (pending[-1].endswith('?') and line.endswith('?') or _KEY.match(pending[-1]) and not _KEY.match(line)) and not _OPT.match(line):
                add(start, pending); pending, start = [line], page
            elif pending:
                pending.append(line)
            elif line.endswith('?') or _CALC.match(line) or re.match(r'^(?:explain|describe|compare|define)\b', line, re.I):
                pending, start = [line], page
    add(start, pending)
    return items


def bank_plan(items, sections, distribution):
    scopes = [(s['section_code'], terms(s['section_title']), terms(s['source_text']), re.match(r'(\d+\.\d+)\b', s['section_title'])) for s in sections]
    matched = []
    for item in items:
        topic, cues = terms(item.topic), terms(item.stem + ' ' + ' '.join(item.options))
        scores = []
        label = re.match(r'(\d+\.\d+)\b', item.topic)
        for code, title, evidence, heading in scopes:
            if label and heading and label[1].split('.')[0] == heading[1].split('.')[0] and label[1] != heading[1]:
                continue
            if topic and title and len(topic & title) / len(topic | title) >= .7:
                score = 100 + len(cues & evidence)
            elif len(cues & (title | evidence)) >= 2 and (not topic or len(topic & (title | evidence)) >= 2):
                score = 4 * len(cues & title) + len(cues & evidence)
            else:
                continue
            scores.append((score, code))
        if scores:
            score, code = max(scores, key=lambda pair: pair[0]); matched.append((score, code, item))
    SystemRandom().shuffle(matched)  # Rotate equally relevant items between practice attempts.
    plan = {k: [] for k in distribution}; used = set(); per_section = Counter()
    def take(kind, predicate):
        while len(plan[kind]) < distribution[kind]['count']:
            eligible = [row for row in matched if row[2].id not in used and predicate(row[2])]
            if not eligible:
                break
            _, code, item = max(eligible, key=lambda r: (r[0] >= 100, -per_section[r[1]], r[0]))
            plan[kind].append((code, item)); used.add(item.id); per_section[code] += 1
    for kind in ('calculation', 'short_answer'):
        take(kind, lambda b, k=kind: b.kind == k)
    take('calculation', lambda b: bool(re.search(r'\d', b.stem) and (_CALC.search(b.stem) or
         (len(b.options) >= 3 and all(re.search(r'\d', o) for o in b.options)))))
    take('mcq', lambda b: b.kind == 'mcq')
    take('short_answer', lambda b: True)
    take('mcq', lambda b: True)
    return plan
