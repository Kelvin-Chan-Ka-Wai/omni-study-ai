import html
import json
import re
from uuid import uuid4
from models import Chapter, ChapterSection, ExamSession, QuestionRecord, WrongQuestionBank
from services.study_math import math_spans, normalize_study_math


class AcademicExporter:
    @staticmethod
    def _md_to_latex_safe(text: str) -> str:
        if not text:
            return ""
        out = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
        out = re.sub(r"^###\s+(.+)$", r"\\subsubsection*{\1}", out, flags=re.MULTILINE)
        out = re.sub(r"^##\s+(.+)$", r"\\subsection*{\1}", out, flags=re.MULTILINE)
        out = re.sub(r"^#\s+(.+)$", r"\\section*{\1}", out, flags=re.MULTILINE)
        return out

    @staticmethod
    def render_printable_katex_pdf_html(title: str, subtitle: str, markdown_body: str) -> str:
        """Render Markdown and identified math separately using local assets."""
        from markdown_it import MarkdownIt
        from markdown_it.token import Token

        markdown = normalize_study_math(markdown_body)
        formulas = list(math_spans(markdown))
        prefix = f"OMNIMATH{uuid4().hex}X"
        placeholder = re.compile(rf"{prefix}(\d+)Z")
        protected = []
        last = 0
        for index, formula in enumerate(formulas):
            protected.extend((markdown[last:formula.start], f"{prefix}{index}Z"))
            last = formula.end
        protected.append(markdown[last:])
        parser = MarkdownIt("commonmark", {"html": False})
        parser.disable("image")
        tokens = parser.parse("".join(protected))
        for token in tokens:
            if not token.children:
                continue
            children = []
            for child in token.children:
                if child.type != "text" or prefix not in child.content:
                    children.append(child)
                    continue
                cursor = 0
                for marker in placeholder.finditer(child.content):
                    if marker.start() > cursor:
                        children.append(Token("text", "", 0, content=child.content[cursor:marker.start()]))
                    formula = formulas[int(marker.group(1))]
                    mode = "block" if formula.display else "inline"
                    children.append(Token("html_inline", "", 0, content=(
                        f'<span class="study-formula" data-mode="{mode}">{html.escape(formula.content.strip())}</span>'
                    )))
                    cursor = marker.end()
                if cursor < len(child.content):
                    children.append(Token("text", "", 0, content=child.content[cursor:]))
            token.children = children
        rendered = parser.renderer.render(tokens, parser.options, {})
        title, subtitle = html.escape(title), html.escape(subtitle)
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<link rel="stylesheet" href="https://assets.omnistudy.local/katex.min.css">
<script src="https://assets.omnistudy.local/katex.min.js"></script>
<style>@page{{size:A4;margin:18mm}}body{{font:11pt Georgia,serif;color:#16213a;line-height:1.6}}h1,h2,h3{{font-family:Arial,sans-serif;break-after:avoid}}h1{{color:#3730a3}}h2{{border-left:4px solid #6366f1;padding-left:12px}}pre{{white-space:pre-wrap}}.katex-display{{overflow:visible}}blockquote{{border-left:3px solid #a5b4fc;padding-left:12px}}</style>
</head><body><h1>{title}</h1><p>{subtitle}</p><main id="content">{rendered}</main>
<script>for (const formula of document.querySelectorAll('.study-formula')) {{
  katex.render(formula.textContent, formula, {{displayMode: formula.dataset.mode === 'block', throwOnError: false, trust: false}});
}}
window.formulasReady=true;</script></body></html>"""

    @classmethod
    def export_chapter_study_guide(
        cls,
        chapter: Chapter,
        sections: list[ChapterSection],
        fmt: str = "md",
        progress=None,
    ) -> str:
        def label(s):
            item = progress.section(s.id) if progress else None
            if not item or not item['attempts']: return 'Not attempted'
            return f"{'Mastered' if item['mastered'] else 'Needs practice'} · {item['average_percent']:g}% average"
        pct = progress.percent_mastered(chapter) if progress else chapter.progress_percentage
        lines = [
            f"# {chapter.course_name} — {chapter.chapter_title}",
            f"**Overall Chapter Mastery (sections with an average above 80%):** {pct:.1f}%\n",
            "---\n",
        ]
        for sec in sections:
            badge = label(sec)
            lines.append(f"## {sec.section_code}: {sec.section_title} ({sec.slide_pages}) — [{badge}]\n")
            lines.append(normalize_study_math(sec.extracted_study_notes or "") or "_No notes extracted._")
            lines.append("\n\n---\n")
        md_doc = "\n".join(lines)

        if fmt == "md":
            return md_doc
        if fmt == "pdf":
            return cls.render_printable_katex_pdf_html(
                title=f"{chapter.course_name} — {chapter.chapter_title} (Study Notes)",
                subtitle=f"Slide-Scoped Study Guide • Mastery: {pct:.1f}%",
                markdown_body=md_doc,
            )

        body = []
        for sec in sections:
            notes_tex = cls._md_to_latex_safe(normalize_study_math(sec.extracted_study_notes or ""))
            badge_tex = label(sec).replace("%", r"\%")
            body.append(
                f"\\section{{{sec.section_code}: {sec.section_title} ({sec.slide_pages})}}\n"
                f"\\textit{{{badge_tex}}}\\par\\medskip\n"
                f"{notes_tex}\n\\bigskip"
            )

        joined_body = "\n".join(body)
        return (
            "\\documentclass[11pt,a4paper]{article}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage{amsmath,amssymb,amsthm}\n"
            "\\usepackage[margin=1in]{geometry}\n"
            "\\usepackage{enumitem}\n"
            f"\\title{{{chapter.course_name}: {chapter.chapter_title} \\\\ \\large Slide-Scoped Study Guide}}\n"
            "\\date{\\today}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            f"{joined_body}\n"
            "\\end{document}\n"
        )

    @classmethod
    def export_exam_session(
        cls,
        chapter: Chapter,
        exam: ExamSession,
        questions: list[QuestionRecord],
        include_solutions: bool = True,
        fmt: str = "md",
    ) -> str:
        mode_title = exam.mode.replace("_", " ").upper()
        lines = [
            f"# {chapter.course_name} — {chapter.chapter_title} ({mode_title})",
            f"**Time Limit:** {exam.time_limit_minutes} mins (+{exam.grace_period_minutes} mins Photo Grace) | "
            f"**Score:** {exam.total_score}/{exam.max_score} pts ({exam.accuracy * 100:.1f}%)\n",
            "---\n",
        ]
        for idx, q in enumerate(questions, start=1):
            source = '; '.join(filter(None, (q.slide_reference or 'Slides', q.testbank_reference)))
            lines.append(f"### Q{idx}. [{q.question_type.upper()} — {q.max_points} pts] ({source})\n")
            lines.append(q.prompt_markdown)
            if q.options_json:
                try:
                    opts = json.loads(q.options_json)
                    lines.append("")
                    for k in ["A", "B", "C", "D", "E"]:
                        if k in opts:
                            lines.append(f"- **{k}.** {opts[k]}")
                except Exception:
                    pass
            if include_solutions:
                lines.append(f"\n> **Your Answer:** `{q.user_answer or 'Unanswered'}` ({q.score_awarded}/{q.max_points} pts)\n>")
                lines.append(f"> **Correct Answer / Rubric:** {q.correct_answer}\n>")
                if q.ai_feedback_and_solution:
                    lines.append(f"> **Step-by-Step Solution & Feedback:**\n> {q.ai_feedback_and_solution}")
            lines.append("\n\n---\n")
        md_doc = "\n".join(lines)

        if fmt == "md":
            return md_doc
        if fmt == "pdf":
            return cls.render_printable_katex_pdf_html(
                title=f"{chapter.course_name} — {mode_title}",
                subtitle=f"{chapter.chapter_title} • Score: {exam.total_score}/{exam.max_score} pts",
                markdown_body=md_doc,
            )

        q_blocks = []
        for idx, q in enumerate(questions, start=1):
            prompt_tex = cls._md_to_latex_safe(q.prompt_markdown)
            source = '; '.join(filter(None, (q.slide_reference or 'Slides', q.testbank_reference)))
            block = [f"\\subsection*{{Question {idx} ({q.max_points} pts) — [{source}]}}"]
            block.append(prompt_tex)
            if q.options_json:
                try:
                    opts = json.loads(q.options_json)
                    block.append("\\begin{enumerate}[label=\\textbf{\\Alph*.}]")
                    for k in ["A", "B", "C", "D", "E"]:
                        if k in opts:
                            block.append(f"  \\item {cls._md_to_latex_safe(str(opts[k]))}")
                    block.append("\\end{enumerate}")
                except Exception:
                    pass
            if include_solutions:
                sol_tex = cls._md_to_latex_safe(q.ai_feedback_and_solution or "")
                block.append(
                    f"\\par\\noindent\\textbf{{Correct Answer:}} {cls._md_to_latex_safe(q.correct_answer)}\\\\"
                    f"\\textbf{{Awarded:}} {q.score_awarded}/{q.max_points} pts\\\\"
                    f"\\textbf{{Solution:}} {sol_tex}"
                )
            else:
                block.append("\\vspace{3cm}")
            q_blocks.append("\n".join(block))

        joined_q = "\n\n\\bigskip\n".join(q_blocks)
        return (
            "\\documentclass[11pt,a4paper]{article}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage{amsmath,amssymb,amsthm}\n"
            "\\usepackage[margin=1in]{geometry}\n"
            "\\usepackage{enumitem}\n"
            f"\\title{{{chapter.course_name}: {chapter.chapter_title} \\\\ \\large {mode_title} ({exam.max_score} pts, {exam.time_limit_minutes} mins)}}\n"
            "\\date{\\today}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            f"{joined_q}\n"
            "\\end{document}\n"
        )

    @classmethod
    def export_wrong_question_bank(
        cls,
        chapter: Chapter,
        wrong_items: list[WrongQuestionBank],
        fmt: str = "md",
        source_names=None,
    ) -> str:
        title = f'{chapter.course_name} · all chapters' if source_names is not None else f'{chapter.course_name}: {chapter.chapter_title}'
        def topic(item):
            return f'{source_names[item.chapter_id]} · {item.core_concept_tag}' if source_names is not None else item.core_concept_tag
        lines = [
            f"# Wrong Question Collection (錯題本) — {title}",
            f"**Total Tracked Questions:** {len(wrong_items)} (Graduates at 3/3 Consecutive Correct)\n",
            "---\n",
        ]
        for idx, item in enumerate(wrong_items, start=1):
            lines.append(
                f"### #{idx} [{topic(item)}] — Streak: `{item.consecutive_correct_count}/3` ({item.status.upper()})\n"
            )
            lines.append(f"**Slide Ref:** {item.slide_reference or 'N/A'} | **Type:** `{item.question_type}`\n")
            lines.append(item.prompt_markdown)
            if item.options_json:
                try:
                    opts = json.loads(item.options_json)
                    lines.append("")
                    for k in ["A", "B", "C", "D", "E"]:
                        if k in opts:
                            lines.append(f"- **{k}.** {opts[k]}")
                except Exception:
                    pass
            lines.append(f"\n- **Your Previous Wrong Answer:** `{item.user_wrong_answer}`")
            lines.append(f"- **Correct Answer:** `{item.correct_answer}`")
            lines.append(f"- **AI Diagnosis & Solution:**\n\n{item.ai_diagnosis_and_solution or ''}\n")
            lines.append("\n---\n")
        md_doc = "\n".join(lines)

        if fmt == "md":
            return md_doc
        if fmt == "pdf":
            return cls.render_printable_katex_pdf_html(
                title=f"Wrong Question Collection — {chapter.course_name}",
                subtitle=f"{title} ({len(wrong_items)} Questions)",
                markdown_body=md_doc,
            )

        blocks = []
        for idx, item in enumerate(wrong_items, start=1):
            blocks.append(
                f"\\subsection*{{Mistake \\#{idx}: {cls._md_to_latex_safe(topic(item))} "
                f"[Streak: {item.consecutive_correct_count}/3 — {item.status.upper()}]}}\n"
                f"{cls._md_to_latex_safe(item.prompt_markdown)}\n"
                f"\\par\\medskip\\noindent\\textbf{{Your Wrong Answer:}} {cls._md_to_latex_safe(item.user_wrong_answer or '')}\\\\\n"
                f"\\textbf{{Correct Answer:}} {cls._md_to_latex_safe(item.correct_answer)}\\\\\n"
                f"\\textbf{{Diagnosis \\& Solution:}} {cls._md_to_latex_safe(item.ai_diagnosis_and_solution or '')}"
            )
        joined = "\n\n\\bigskip\n".join(blocks)
        return (
            "\\documentclass[11pt,a4paper]{article}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage{amsmath,amssymb}\n"
            "\\usepackage[margin=1in]{geometry}\n"
            f"\\title{{Wrong Question Bank: {cls._md_to_latex_safe(title)}}}\n"
            "\\date{\\today}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            f"{joined}\n"
            "\\end{document}\n"
        )
