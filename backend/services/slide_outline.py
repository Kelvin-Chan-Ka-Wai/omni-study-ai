"""Find study topics and obvious front/back matter without sending slides to an AI."""
import re

from services.documents import VISUAL_ONLY

_PUBLISHER = re.compile(r"^(?:©|\(c\)|copyright\s+(?:©|\d{4}\b)|all rights reserved\b|no reproduction or distribution\b)", re.I)
_BOILERPLATE = re.compile(r"^(?:because learning changes everything[.!]?|®|access the text alternative for slide images[.!]?)$", re.I)
_NUMBERED = re.compile(r"^\d{1,3}\.\d{1,3}(?:\s*[.:–—-]\s*|\s+)\S")
_CHAPTER_LABEL = re.compile(r"^(?:chapter|unit|module|lecture)\s+\d+(?:\b.*)?$", re.I)
_ADMIN = re.compile(r"^(?:course (?:information|logistics|policies|administration)|greetings[!:.]?|what will i be doing\?(?:\s*\(continued\))?|kahoot|assessment schedule|grading policy|attendance policy)$", re.I)
_OUTLINE = re.compile(r"^(?:(?:chapter|lecture|topic|course) outline|table of contents|agenda)$", re.I)
_END = re.compile(r"^(?:thank you(?: for (?:listening|your attention))?|questions\??|q\s*&\s*a|end of (?:chapter|lecture|presentation)(?:\s+\d+)?)[.!?]?$", re.I)
_HEADING = re.compile(r"^#{1,6}\s+")
_CONTINUATION = re.compile(r"\s*(?:\(continued\)|[–—:-]\s*continued|\s+[IVX]{1,4})$", re.I)


def format_slide_pages(pages):
    pages = sorted(set(pages))
    runs = []
    for n in pages:
        if runs and n == runs[-1][-1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ("Slide " if len(pages) == 1 else "Slides ") + ", ".join(
        str(a) if a == b else f"{a}-{b}" for a, b in runs
    )


def _heading(text):
    return _HEADING.sub("", text).strip().rstrip("#").strip()


def review_slides(slides):
    """Retain unknown/visual pages; exclude only recognizable non-study pages."""
    lines_by_slide = [s["text"].splitlines() for s in slides]
    reviewed = []
    for slide, lines in zip(slides, lines_by_slide):
        lines = [line.strip() for line in lines if line.strip()]
        payload = [line for line in lines if not _PUBLISHER.match(line)
                   and not _BOILERPLATE.match(line) and not re.fullmatch(r"\d{1,3}", line)]
        title = _heading(payload[0]) if payload else ""
        if _NUMBERED.match(title) and len(payload) > 1 and re.search(r"\b(?:a|an|and|for|in|of|on|the|to|with)$", title, re.I):
            if payload[1][0].isupper() and len(payload[1].split()) <= 5 and not re.search(r"[.!?:;]$", payload[1]):
                title += " " + payload[1]
        reviewed.append({**slide, "title": title, "lines": payload, "original_lines": lines,
                         "topic_start": bool(_NUMBERED.match(title) or (payload and re.match(r"^#{1,3}\s", payload[0])))})

    first_topic = next((i for i, page in enumerate(reviewed) if page["topic_start"] and _NUMBERED.match(page["title"])), len(slides))
    for i, slide in enumerate(reviewed):
        title, payload, original = slide["title"], slide.pop("lines"), slide.pop("original_lines")
        reason = None
        if not slide.get("verified") and slide["text"] != VISUAL_ONLY:
            cover_metadata = len(payload) <= 3 or any(
                _PUBLISHER.match(line) or _BOILERPLATE.match(line) or re.search(r"\bedition\b", line, re.I)
                for line in original
            )
            if i == 0 and len(slides) > 1 and len(payload) <= 10 and cover_metadata and (
                any(_CHAPTER_LABEL.fullmatch(_heading(line)) for line in payload[:3]) or title.lower() in {"title slide", "cover page"}
            ) and not any(re.search(r"^[•*]|[.!?]$", line) for line in payload[1:]):
                reason = "Opening cover"
            elif i < min(first_topic, 8) and _ADMIN.fullmatch(title):
                reason = "Course logistics"
            elif _OUTLINE.fullmatch(title) and (i < first_topic or i < 3) and all(
                len(line.split()) <= 12 and not re.search(r"[.!?]\s+\w", line) for line in payload[1:]
            ):
                reason = "Outline only"
            elif i >= len(slides) - 2 and _END.fullmatch(title) and all(
                re.match(r"^(?:https?://|www\.|\S+@\S+)", line, re.I) for line in payload[1:]
            ):
                reason = "Closing slide"
            elif original and any(_PUBLISHER.match(line) or _BOILERPLATE.match(line) for line in original) and all(
                re.fullmatch(r"(?:https?://|www\.)\S+", line, re.I) for line in payload
            ):
                reason = "Publisher credits"
        if payload and not slide.get("verified"):
            # Keep the original evidence, including standalone numeric values, except clear boilerplate.
            slide["text"] = "\n".join(line for line in original if not _PUBLISHER.match(line) and not _BOILERPLATE.match(line))
        slide["excluded_reason"] = reason
    return reviewed


def build_outline(reviewed):
    sections = []
    group = []
    size = 0
    topic = ""
    carried_title = ""

    def finish():
        if not group:
            return
        reference = format_slide_pages(p["slide_number"] for p in group)
        title = carried_title or group[0]["title"] or reference
        if group[0]["text"] == VISUAL_ONLY:
            title = f"{reference} (needs transcription)"
        sections.append({"section_code": f"Section {len(sections) + 1}", "section_title": title[:100], "slide_pages": reference})

    for slide in reviewed:
        if slide["excluded_reason"]:
            continue
        visual = slide["text"] == VISUAL_ONLY
        boundary = slide["topic_start"] and _CONTINUATION.sub("", slide["title"]).casefold() != _CONTINUATION.sub("", topic).casefold()
        # For numbered topics, use the actual topic boundary, with a size limit for generation.
        limit = 8 if topic else 5
        if group and (boundary or len(group) >= limit or size + len(slide["text"]) > 18000
                      or visual != (group[-1]["text"] == VISUAL_ONLY)):
            finish()
            group, size, carried_title = [], 0, topic if not (boundary or visual) else ""
        if slide["topic_start"]:
            topic = slide["title"]
        if not group and not visual and topic:
            carried_title = topic
        group.append(slide)
        size += len(slide["text"])
    finish()
    return sections
