"""Explicit section selection shared by generation, deletion and export."""
import re
from fastapi import HTTPException
from models import ChapterSection


def selected_sections(db, chapter_id, ids, all_sections=False):
    query = db.query(ChapterSection).filter(ChapterSection.chapter_id == chapter_id).order_by(ChapterSection.id)
    if all_sections:
        return query.all()
    if not ids:
        raise HTTPException(400, "Select at least one section. All sections requires an explicit action.")
    if any(not isinstance(i, int) or i <= 0 for i in ids):
        raise HTTPException(400, "Invalid section selection.")
    rows = query.filter(ChapterSection.id.in_(ids)).all()
    if {s.id for s in rows} != set(ids):
        raise HTTPException(400, "Some selected sections do not belong to this chapter.")
    return rows


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
