"""Question identity is based on content, never its type, position, or testbank page."""
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from models import Chapter, ExamSession, QuestionRecord, QuestionSource


class RepeatedQuestion(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    words: tuple
    features: frozenset


_LABEL = re.compile(r'^\s*(?:(?:question|q)\s*\d+\s*[.):\-]?|\d{1,4}[.)](?!\d))\s*', re.I)
_SUFFIX = re.compile(r'(?:\s*\(?select all (?:options )?that apply\)?[.!:]?|\s*state your answer in words and explain why it is correct\.|\s*show your calculation, including the formula, intermediate steps and units\.)\s*$', re.I)
_CHOICES = re.compile(r'^\s*\(?[a-e][.)]\s+', re.M)
_GENERIC = re.compile(r'^(?:which|select|choose|identify) (?:all |one |the )?(?:of )?(?:the )?(?:following )?(?:(?:statements?|options?|answers?|choices?) )?(?:(?:are|is) )?(?:true|false|correct|incorrect|accurate|best|applies|apply)$')
_SKIP = set('a an the is are was were of in to for please and that following which one'.split())


@lru_cache(maxsize=4096)
def _identity(prompt, choices):
    text = unicodedata.normalize('NFKC', prompt).casefold().replace('−', '-').replace('×', '*').replace('÷', '/')
    text = _LABEL.sub('', text.replace('**','').replace('`','').strip())
    text = _SUFFIX.sub('',text).strip()
    embedded = _CHOICES.split(text) if re.search(r'(?im)^\s*\(?a[.)]\s+',text) else []
    if embedded and len(embedded) >= 3:
        text, embedded = embedded[0], embedded[1:]
    else:
        embedded = []
    text = _SUFFIX.sub('',text)
    words = re.findall(r'[^\W_]+|[+<>=/%^*−-]', re.sub(r'(?<=[^\W\d_])[-–—](?=[^\W\d_])', ' ', text))
    stem = ' '.join(words)
    if _GENERIC.fullmatch(stem) and (choices or embedded):
        # With a generic stem the actual propositions ARE the question. Ignore choice order.
        words.extend(sorted(' '.join(re.findall(r'\w+|[+<>=/%^*-]', s.casefold())) for s in (choices or embedded)))
    elif stem.startswith(('what is ', 'what are ', 'define ')):
        words = words[1:] if words[0]=='define' else words[2:]
        words = ['define', *words]
    return Identity(tuple(words), frozenset(w for w in words if w not in _SKIP))


def identity(prompt, options=None):
    vals = options.values() if isinstance(options,dict) else options or ()
    return _identity(str(prompt), tuple(sorted(str(v) for v in vals)))


def question_keys(q):
    keys = {identity(q['prompt_markdown'], q.get('options'))}
    if q.get('_source'):
        keys.add(identity(*q['_source']))
    return keys


class QuestionHistory:
    def __init__(self):
        self.keys = set()
        self.index = defaultdict(set)
        self.examples = []
        self.legacy = defaultdict(list)

    def add(self, key):
        if key in self.keys: return
        self.keys.add(key)
        if len(key.features) >= 5:
            for term in key.features: self.index[term].add(key)

    def contains(self, key, except_key=None):
        if key != except_key and key in self.keys: return True
        if len(key.features) < 5: return False
        possible = set().union(*(self.index.get(w, ()) for w in key.features))
        return any(len(key.features & other.features) >= .88 * len(key.features | other.features) for other in possible if other != except_key)

    def accept(self, questions):
        # All-or-nothing: a rejected batch must not consume new items.
        pending = QuestionHistory()
        for q in questions:
            keys = question_keys(q)
            if any(self.contains(k) or pending.contains(k) for k in keys):
                raise RepeatedQuestion('This question is already used: '+q['prompt_markdown'][:120])
            for k in keys: pending.add(k)
        for k in pending.keys: self.add(k)

    def untraceable_pages(self, items):
        # Old adaptations only stored a page. If none of its stems match, avoid that page.
        pages = defaultdict(QuestionHistory)
        for item in items:
            if item.page in self.legacy:
                pages[item.page].add(identity(item.stem, item.options))
        return {p for p, keys in self.legacy.items() if any(not pages[p].contains(k) for k in keys)}

    @classmethod
    def load(cls, db, course, bank_path=None):
        # Include unfinished papers and legacy questions without source metadata. Never read answers.
        name = lambda v: ' '.join(v.casefold().split())
        chapters = {cid: path for cid, title, path in db.query(Chapter.id, Chapter.course_name, Chapter.testbank_file_path) if name(title) == name(course)}
        rows = (db.query(QuestionRecord.prompt_markdown, QuestionRecord.options_json, QuestionSource.source_json,
                         ExamSession.chapter_id, QuestionRecord.testbank_reference)
                .join(ExamSession, ExamSession.id == QuestionRecord.session_id)
                .outerjoin(QuestionSource, QuestionSource.question_id == QuestionRecord.id)
                .filter(ExamSession.chapter_id.in_(chapters)).order_by(QuestionRecord.id))
        pool = cls()
        for prompt, options, source, chapter, ref in rows:
            key = identity(prompt, json.loads(options) if options else None)
            pool.add(key)
            if source:
                pool.add(identity(*json.loads(source)))
            elif bank_path and chapters[chapter] == bank_path and (page := re.fullmatch(r'Testbank p\. (\d+)', ref or '', re.I)):
                pool.legacy[int(page[1])].append(key)
            pool.examples.append(prompt.split('\n')[0][:210])
        return pool
