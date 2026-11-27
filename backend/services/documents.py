"""Read study documents locally while preserving their source page numbers."""
from collections.abc import Iterator
from pathlib import Path
from zipfile import ZipFile

import pymupdf
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

DOCUMENT_SUFFIXES = frozenset({'.pdf', '.pptx', '.md', '.txt'})
MAX_SOURCE_PAGES = 10_000
VISUAL_ONLY = '(Visual/Diagram Slide)'


class DocumentReadError(ValueError):
    """A user-actionable document error safe to show in the UI."""


def _shape_text(shapes) -> Iterator[str]:
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _shape_text(shape.shapes)
        if shape.has_text_frame:
            text = shape.text_frame.text.strip()
            if text:
                yield text
        if shape.has_table:
            for row in shape.table.rows:
                text = ' | '.join(cell.text.strip() for cell in row.cells if not cell.is_spanned)
                if text.strip(' |'):
                    yield text


def _check_page_count(count: int) -> None:
    if count > MAX_SOURCE_PAGES:
        raise DocumentReadError(f'Split documents with more than {MAX_SOURCE_PAGES:,} pages into smaller files.')


def read_pages(path: Path) -> Iterator[str]:
    """Yield one entry per PDF page, slide, or non-empty text block."""
    suffix = path.suffix.lower()
    try:
        if suffix == '.pdf':
            with pymupdf.open(path) as document:
                if not document.is_pdf:
                    raise DocumentReadError('This file is not a PDF. Export it again as a PDF.')
                if document.needs_pass:
                    raise DocumentReadError('This PDF needs a password. Save an unlocked copy and try again.')
                _check_page_count(len(document))
                for page in document:
                    # Keep formulas, currency symbols and punctuation in the source evidence.
                    yield page.get_text('text').strip()
        elif suffix == '.pptx':
            with ZipFile(path) as package:
                if sum(item.file_size for item in package.infolist()) > 350 * 1024 * 1024:
                    raise DocumentReadError('This PowerPoint expands to more than 350 MB. Split it into smaller files.')
            presentation = Presentation(str(path))
            _check_page_count(len(presentation.slides))
            for slide in presentation.slides:
                parts = list(_shape_text(slide.shapes))
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        parts.append(f'[Speaker Notes]: {notes}')
                yield '\n'.join(parts)
        elif suffix in ('.md', '.txt'):
            raw = path.read_bytes()
            encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = raw.decode(encoding).replace('\r\n', '\n').replace('\r', '\n')
            if '\x00' in text:
                raise DocumentReadError('This file contains binary data. Save it as a plain text or Markdown file.')
            blocks = [part.strip() for part in text.split('\n\n') if part.strip()]
            _check_page_count(len(blocks))
            yield from blocks
        else:
            raise DocumentReadError('Choose a PDF, PPTX, Markdown or text document.')
    except DocumentReadError:
        raise
    except UnicodeDecodeError as exc:
        raise DocumentReadError('This text file could not be decoded. Save it as UTF-8 and try again.') from exc
    except Exception as exc:
        # The parsers raise different errors for invalid containers and content.
        raise DocumentReadError(f'Could not read this {suffix.lstrip(".").upper()} file. Open it and export a new copy, then try again.') from exc


def resolve_local_upload(storage_dir: Path, url: str | None) -> Path | None:
    prefix = '/storage/uploads/'
    if not url or not url.startswith(prefix):
        return None
    uploads = (storage_dir / 'uploads').resolve()
    candidate = (uploads / url.removeprefix(prefix)).resolve()
    return candidate if candidate.is_relative_to(uploads) and candidate.is_file() else None
