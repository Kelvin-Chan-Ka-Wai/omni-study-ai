"""Keep currency, Markdown code, and TeX delimiters separate in study notes."""
from collections.abc import Iterator
from dataclasses import dataclass
import re
import textwrap


_TOKEN = re.compile(r"(?m)^[ \t]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n|`+|\\[\s\S]|\$+")
_DOLLAR_OR_ESCAPE = re.compile(r"\\[\s\S]|\$+")
_CURRENCY_ONLY = re.compile(r"\\\$[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\Z")


@dataclass(frozen=True)
class MathSpan:
    start: int
    end: int
    content: str
    display: bool = False
    indent: str = ""


def _dollar_close(text: str, start: int, delimiter: str) -> re.Match | None:
    end = text.find("\n", start) if delimiter == "$" else len(text)
    if end < 0:
        end = len(text)
    for candidate in _DOLLAR_OR_ESCAPE.finditer(text, start, end):
        if candidate.group() == delimiter:
            return candidate
    return None


def math_spans(text: str) -> Iterator[MathSpan]:
    """Recognize matched math delimiters and skip literal Markdown code."""
    pos = 0
    while token := _TOKEN.search(text, pos):
        marker = token.group()
        pos = token.end()
        fence = token.group("fence")
        if fence:
            end_fence = re.compile(rf"(?m)^[ \t]{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$").search(text, pos)
            if not end_fence:
                break
            pos = end_fence.end()
            if token.group("info").strip().lower() in ("latex", "math", "tex") and text[token.end():end_fence.start()].strip():
                indent = text[token.start():token.start("fence")]
                yield MathSpan(token.start("fence"), pos, text[token.end():end_fence.start()], True, indent)
            continue
        if marker.startswith("`"):
            ending = re.compile(rf"(?<!`){re.escape(marker)}(?!`)").search(text, pos)
            if ending:
                pos = ending.end()
            continue
        if marker.startswith("$"):
            closing = _dollar_close(text, pos, marker)
            if not closing or not text[pos:closing.start()].strip():
                continue
            before = text[text.rfind("\n", 0, token.start()) + 1:token.start()]
            line_end = text.find("\n", closing.end())
            after = text[closing.end():line_end if line_end != -1 else len(text)]
            display = len(marker) > 1 and not before.strip() and not after.strip()
            yield MathSpan(token.start(), closing.end(), text[pos:closing.start()], display, before if display else "")
            pos = closing.end()
            continue
        if marker in (r"\(", r"\["):
            closing = r"\)" if marker == r"\(" else r"\]"
            end = text.find(closing, pos)
            if end != -1 and (marker == r"\[" or "\n" not in text[pos:end]):
                before = text[text.rfind("\n", 0, token.start()) + 1:token.start()]
                line_end = text.find("\n", end + len(closing))
                after = text[end + len(closing):line_end if line_end != -1 else len(text)]
                display = marker == r"\[" and not before.strip() and not after.strip()
                yield MathSpan(token.start(), end + len(closing), text[pos:end], display, before if display else "")
                pos = end + len(closing)


def _normalize_expression(expression: str) -> str:
    # Some older generated notes contain JSON control characters instead of TeX commands.
    expression = expression.replace("\x0c", r"\f").replace("\x08", r"\b")
    expression = re.sub(r"\t(?=[a-zA-Z])", r"\\t", expression)
    expression = re.sub(r"\r(?=[a-zA-Z])", r"\\r", expression)
    # Markdown's inline math tokenizer does not treat \$ as an escaped delimiter.
    # An equivalent TeX command keeps the dollar sign inside the equation.
    return re.sub(r"\\[\s\S]", lambda m: r"\text{\textdollar{}}" if m.group() == r"\$" else m.group(), expression)


def normalize_study_math(markdown: str) -> str:
    if not markdown:
        return ""
    chunks = []
    last = 0
    for formula in math_spans(markdown):
        chunks.append(markdown[last:formula.start])
        body = formula.content.strip()
        if not formula.display and _CURRENCY_ONLY.fullmatch(body):
            chunks.append(body)  # Literal currency in prose: Markdown will render \$ as $.
        elif formula.display:
            normalized = _normalize_expression(textwrap.dedent(formula.content).strip())
            lines = normalized.split("\n")
            chunks.append("$$\n" + "\n".join(formula.indent + line for line in lines) + "\n" + formula.indent + "$$")
        else:
            inline = body.replace("\n", " ")
            chunks.append("$" + _normalize_expression(inline) + "$")
        last = formula.end
    chunks.append(markdown[last:])
    return "".join(chunks)
