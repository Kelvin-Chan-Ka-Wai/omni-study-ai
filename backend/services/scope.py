"""Explicit section selection shared by generation, deletion and export."""
import re
from fastapi import HTTPException
from models import ChapterSection


def section_order(section):
    match = re.fullmatch(r"Section (\d+)", section.section_code)
    return (int(match.group(1)) if match else section.id, section.id)


def selected_sections(db, chapter_id, ids, all_sections=False, *, include_archived=False):
    query = db.query(ChapterSection).filter(ChapterSection.chapter_id == chapter_id).order_by(ChapterSection.id)
    if all_sections:
        return sorted(query.filter_by(is_archived=False).all(), key=section_order)
    if not include_archived:
        query = query.filter_by(is_archived=False)
    if not ids:
        raise HTTPException(400, "Select at least one section. All sections requires an explicit action.")
    if any(not isinstance(i, int) or i <= 0 for i in ids):
        raise HTTPException(400, "Invalid section selection.")
    rows = query.filter(ChapterSection.id.in_(ids)).all()
    if {s.id for s in rows} != set(ids):
        raise HTTPException(400, "Some selected sections do not belong to this chapter.")
    return sorted(rows, key=section_order)


def page_numbers(reference):
    text = re.sub(r"(?i)\b(slides?|pages?)\b", "", reference or "").strip()
    if not re.fullmatch(r"[\d\s,;\-–—]+", text):
        raise ValueError("Slide references must contain exact pages or ranges, such as 1-3, 7.")
    result = set()
    for part in re.split(r"[,;]", text):
        if not part.strip():
            raise ValueError("Empty slide reference.")
        bounds = re.split(r"[-–—]", part.strip())
        if len(bounds) > 2:
            raise ValueError("Invalid slide range.")
        nums = [int(n.strip()) for n in bounds]
        if min(nums) < 1 or nums[0] > nums[-1] or nums[-1] > 10000:
            raise ValueError("Invalid slide range.")
        result.update(range(nums[0], nums[-1] + 1))
    return sorted(result)


def exam_sections(db, chapter, ids, mode, pages, all_sections=False):
    """Explicit cross-deck, exact-page scope is exclusive to midterms and finals."""
    if pages is None:
        return [(s, s.slide_pages) for s in selected_sections(db, chapter.id, ids, all_sections)]
    from services.mastery import course_key
    if mode not in ('midterm', 'final') or all_sections or not ids or len(ids) != len(set(ids)) or set(ids) != set(pages):
        raise HTTPException(400, 'Select sections and slide pages explicitly for a midterm or final.')
    rows = db.query(ChapterSection).filter(ChapterSection.id.in_(ids), ChapterSection.is_archived.is_(False)).all()
    if len(rows) != len(ids) or any(course_key(s.chapter.course_name) != course_key(chapter.course_name) for s in rows):
        raise HTTPException(400, 'Use active sections from the same course only. Reopen the slide selector.')
    for s in rows:
        try:
            if not set(page_numbers(pages[s.id])) <= set(page_numbers(s.slide_pages)): raise ValueError()
        except ValueError:
            raise HTTPException(400, f'Choose pages within {s.chapter.chapter_title} · {s.section_code} ({s.slide_pages}).') from None
    return [(s, pages[s.id]) for s in sorted(rows, key=lambda s: (s.chapter_id, section_order(s)))]
