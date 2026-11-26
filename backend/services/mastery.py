"""Read-only progress from finalized scores. Each graded attempt carries equal weight."""
from collections import defaultdict, Counter
from fractions import Fraction
from sqlalchemy import func
from models import Chapter, ChapterSection, ExamSession, QuestionRecord
from services.scope import section_order

MODES = ('section_quiz', 'mock_test', 'midterm', 'final')


def course_key(name):
    return ' '.join(name.casefold().split())


def course_chapters(db, chapter):
    return [c for c in db.query(Chapter).order_by(Chapter.id) if course_key(c.course_name) == course_key(chapter.course_name)]


def summary(scores):
    if not scores:
        return dict(attempts=0, average_percent=None, average_earned=None, average_possible=None, mastered=False)
    n = len(scores)
    ratio = sum(e / p for e, p in scores) / n
    return dict(attempts=n, average_percent=round(float(100 * ratio), 4),
                average_earned=round(float(sum(e for e, _ in scores) / n), 2),
                average_possible=round(float(sum(p for _, p in scores) / n), 2), mastered=ratio > Fraction(4, 5))


def pair(earned, possible):
    return Fraction(str(round(earned or 0, 6))), Fraction(str(round(possible, 6)))


class Progress:
    def __init__(self, db, chapters):
        ids = [c.id for c in chapters]
        self.chapters = chapters
        self.by_section = defaultdict(lambda: defaultdict(list))
        self.by_chapter = defaultdict(lambda: defaultdict(list))
        self.by_course = defaultdict(list)
        rows = (db.query(QuestionRecord.section_id, ChapterSection.chapter_id, ExamSession.id, ExamSession.mode,
                         func.sum(QuestionRecord.score_awarded), func.sum(QuestionRecord.max_points))
                .join(ExamSession, ExamSession.id == QuestionRecord.session_id)
                .join(ChapterSection, ChapterSection.id == QuestionRecord.section_id)
                .filter(ChapterSection.chapter_id.in_(ids), ExamSession.status == 'completed')
                .group_by(QuestionRecord.section_id, ChapterSection.chapter_id, ExamSession.id, ExamSession.mode))
        self.pending = defaultdict(Counter)
        waiting = (db.query(ExamSession.id, ExamSession.mode, ExamSession.status, ChapterSection.chapter_id, ChapterSection.id)
                   .select_from(ExamSession).join(QuestionRecord).join(ChapterSection)
                   .filter(ChapterSection.chapter_id.in_(ids), ExamSession.status != 'completed').distinct())
        scopes = set()
        for eid, mode, status, cid, sid in waiting:
            kind = 'awaiting_grade' if status.startswith('submitted_') or status == 'grading' else 'in_progress'
            for key in [('section', sid), ('chapter', cid), ('course', 0)]: scopes.add((eid, mode, kind, key))
        for _, mode, kind, key in scopes: self.pending[key, mode][kind] += 1
        portions = defaultdict(lambda: (0, 0))
        for sid, cid, eid, mode, earned, possible in rows:
            if not possible or mode not in MODES: continue
            e, p = pair(earned, possible); self.by_section[sid][mode].append((e, p))
            oe, op = portions[cid, eid, mode]; portions[cid, eid, mode] = (oe + e, op + p)
        for (cid, _, mode), value in portions.items(): self.by_chapter[cid][mode].append(value)
        for mode, earned, possible in (db.query(ExamSession.mode, ExamSession.total_score, ExamSession.max_score)
                                       .filter(ExamSession.chapter_id.in_(ids), ExamSession.status == 'completed')):
            if possible and mode in MODES: self.by_course[mode].append(pair(earned, possible))

    def section(self, sid):
        counts = sum((self.pending[('section', sid), m] for m in MODES), Counter())
        return {**summary([row for scores in self.by_section[sid].values() for row in scores]), **counts}

    def percent_mastered(self, ch):
        active = [s for s in ch.sections if not s.is_archived]
        return round(100 * sum(self.section(s.id)['mastered'] for s in active) / len(active), 1) if active else 0

    def report(self):
        def modes(groups, key):
            return {m: {**summary(groups[m]), **self.pending[key, m]} for m in MODES}
        return {'modes': modes(self.by_course, ('course', 0)), 'chapters': [
            {'id': ch.id, 'title': ch.chapter_title, 'modes': modes(self.by_chapter[ch.id], ('chapter', ch.id)), 'sections': [
                {'id': s.id, 'label': f'{s.section_code} · {s.section_title}', 'pages': s.slide_pages,
                 'archived': s.is_archived, 'overall': self.section(s.id), 'modes': modes(self.by_section[s.id], ('section', s.id))}
                for s in sorted(ch.sections, key=section_order) if not s.is_archived or self.by_section[s.id]]}
            for ch in self.chapters]}
