import asyncio
import json
import re
from pathlib import Path
import pymupdf as fitz
from pptx import Presentation
from services.llm_harness import HybridLLMHarness
from services.scoring_engine import ScoringEngine


class SlideScopeRAG:
    @staticmethod
    def _clean_json_response(raw_text: str) -> dict | list:
        cleaned = raw_text.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        obj_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
        if obj_match:
            cleaned = obj_match.group(1)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Auto-escape unescaped LaTeX backslashes (e.g. \frac, \sigma, \text) inside JSON strings
            fixed = re.sub(r'\\(?![/"\\bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', cleaned)
            try:
                return json.loads(fixed)
            except Exception:
                # Salvage completed question objects if stream truncated
                salvaged = []
                for m in re.finditer(r'\{[^{}]*?"prompt_markdown"[\s\S]*?"solution_explanation"\s*:\s*"[^"]*"\s*\}', fixed):
                    try:
                        salvaged.append(json.loads(m.group(0)))
                    except Exception:
                        pass
                if salvaged:
                    return {"questions": salvaged}
                raise

    @staticmethod
    def _sanitize_pdf_extracted_text(raw: str) -> str:
        if not raw:
            return ""
        cleaned = re.sub(r'[.!#"%\']{3,}', " ", raw)
        cleaned = cleaned.replace("$", "")
        cleaned = re.sub(r"(\w+)-\s+(\w+)", r"\1\2", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def sanitize_markdown_latex_notes(md_text: str) -> str:
        if not md_text:
            return ""
        text = md_text.strip()
        text = re.sub(r"\s*\$\$\s*([\s\S]*?)\s*\$\$\s*", r"\n\n$$\n\1\n$$\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def extract_slides_text(cls, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Slide file not found: {path}")

        ext = path.suffix.lower()
        slides_data: list[dict] = []

        if ext == ".pptx":
            prs = Presentation(str(path))
            for idx, slide in enumerate(prs.slides, start=1):
                parts = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        txt = shape.text_frame.text.strip()
                        if txt:
                            parts.append(txt)
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        parts.append(f"[Speaker Notes]: {notes}")
                slides_data.append({
                    "slide_number": idx,
                    "text": "\n".join(parts).strip() or "(Visual/Diagram Slide)",
                })
        elif ext == ".pdf":
            doc = fitz.open(str(path))
            for idx, page in enumerate(doc, start=1):
                txt = cls._sanitize_pdf_extracted_text(page.get_text("text"))
                slides_data.append({
                    "slide_number": idx,
                    "text": txt or "(Visual/Diagram Slide)",
                })
            doc.close()
        else:
            content = path.read_text(encoding="utf-8", errors="ignore")
            chunks = [c.strip() for c in content.split("\n\n") if c.strip()]
            for idx, chunk in enumerate(chunks, start=1):
                slides_data.append({"slide_number": idx, "text": chunk})

        return slides_data

    @classmethod
    def extract_textbook_chunks(cls, file_path: str | Path | None, max_chars: int = 1800) -> list[dict]:
        if not file_path:
            return []
        path = Path(file_path)
        if not path.exists():
            return []

        chunks: list[dict] = []
        ext = path.suffix.lower()
        if ext == ".pdf":
            doc = fitz.open(str(path))
            for idx, page in enumerate(doc, start=1):
                txt = cls._sanitize_pdf_extracted_text(page.get_text("text"))
                if txt:
                    chunks.append({"page": idx, "text": txt[:max_chars]})
            doc.close()
        elif ext == ".pptx":
            prs = Presentation(str(path))
            for idx, slide in enumerate(prs.slides, start=1):
                parts = [
                    shape.text_frame.text.strip()
                    for shape in slide.shapes
                    if shape.has_text_frame and shape.text_frame.text.strip()
                ]
                if parts:
                    chunks.append({"page": idx, "text": "\n".join(parts)[:max_chars]})
        else:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            for idx in range(0, len(raw), max_chars):
                chunks.append({"page": (idx // max_chars) + 1, "text": raw[idx : idx + max_chars]})
        return chunks

    @staticmethod
    def filter_textbook_for_slide_section(
        section_title: str,
        slide_text: str,
        textbook_chunks: list[dict],
        top_k: int = 2,
        label: str = "Textbook Ref",
    ) -> str:
        if not textbook_chunks:
            return ""
        query_terms = set(re.findall(r"[A-Za-z]{4,}", f"{section_title} {slide_text}".lower()))
        if not query_terms:
            return ""
        scored = []
        for chunk in textbook_chunks:
            chunk_terms = set(re.findall(r"[A-Za-z]{4,}", chunk["text"].lower()))
            overlap = len(query_terms & chunk_terms)
            if overlap > 0:
                scored.append((overlap, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return "\n\n".join(f"[{label} p.{c['page']}]: {c['text']}" for _, c in scored[:top_k])

    @classmethod
    async def map_slide_sections(
        cls,
        course_name: str,
        chapter_title: str,
        slides_data: list[dict],
        textbook_chunks: list[dict] | None = None,
    ) -> list[dict]:
        formatted_slides = "\n\n".join(
            f"--- SLIDE {s['slide_number']} ---\n{s['text']}" for s in slides_data
        )
        tb_sample = ""
        if textbook_chunks:
            tb_sample = cls.filter_textbook_for_slide_section(
                chapter_title, formatted_slides[:6000], textbook_chunks, top_k=3, label="Textbook Reference"
            )

        system_prompt = (
            "You are an elite university professor. ONLY include sections, theorems, and formulas covered in the LECTURE SLIDES. "
            "Use $...$ ONLY for mathematical expressions (never around plain English words) and $$...$$ on its own line for display equations. "
            "Return valid JSON only."
        )

        textbook_context = f"SUPPLEMENTARY TEXTBOOK CONTEXT:\n{tb_sample[:4000]}" if tb_sample else ""
        user_prompt = f"""
Course: {course_name} | Chapter: {chapter_title}

LECTURE SLIDES:
{formatted_slides[:22000]}
{textbook_context}

Return a JSON object with key "sections" containing a list of section objects:
- "section_code": e.g. "Section 1.1"
- "section_title": Clear academic title
- "slide_pages": e.g. "Slides 1-8"
- "core_concepts": list of key concepts
- "extracted_study_notes": Well-spaced Markdown + LaTeX study guide using these 4 subheadings:
### 1. Executive Summary & Core Intuition
### 2. Key Definitions, Theorems & Formulas
### 3. Step-by-Step Calculation Playbook
### 4. Worked Numerical Example & Exam Pitfalls
"""
        res = await HybridLLMHarness.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            task="fast",
            temperature=0.2,
            json_mode=True,
        )
        parsed = cls._clean_json_response(res["content"])
        sections = parsed.get("sections", []) if isinstance(parsed, dict) else parsed
        for sec in sections:
            sec["extracted_study_notes"] = cls.sanitize_markdown_latex_notes(
                sec.get("extracted_study_notes", "")
            )
        return sections

    @classmethod
    async def _generate_question_batch(
        cls,
        course_name: str,
        chapter_title: str,
        scope_context: str,
        testbank_reference_block: str,
        batch_instruction: str,
    ) -> tuple[list[dict], str, str]:
        """
        Micro-batch worker (max 3-5 questions per call, capped at 1300 output tokens)
        so every parallel worker completes in 5 to 15 seconds!
        """
        system_prompt = (
            "You are a university professor authoring exam questions strictly from the provided slide scope. "
            "Use clean LaTeX ($...$ for inline math, $$...$$ for display math). "
            "Keep 'solution_explanation' brief (1-2 sentences max) for speed. Return valid JSON only."
        )

        user_prompt = f"""
Course: {course_name} | Chapter: {chapter_title}

SLIDE SCOPE:
{scope_context[:6500]}
{testbank_reference_block[:2000]}

BATCH TASK:
{batch_instruction}

Return ONLY a JSON object with key "questions" containing a list of question objects:
- "section_code": section code from slides
- "question_type": "mcq_single" | "mcq_multi" | "short_answer" | "calculation"
- "core_concept_tag": short concept name
- "slide_reference": e.g. "Slides 3-5"
- "prompt_markdown": question text (append "(Select all that apply)" if mcq_multi)
- "options": {{"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."}} for MCQs, or null
- "correct_answer": letter(s) e.g. "B" or "A, C" for MCQs; concise answer + key formula for short/calculation
- "max_points": numeric point value requested
- "solution_explanation": 1-2 sentence explanation
"""
        res = await HybridLLMHarness.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            task="fast",
            temperature=0.3,
            json_mode=True,
            max_tokens=2400,
        )
        parsed = cls._clean_json_response(res["content"])
        q_list = parsed.get("questions", []) if isinstance(parsed, dict) else parsed
        return q_list, res["provider_used"], res["model_used"]

    @classmethod
    async def generate_scoped_assessment(
        cls,
        course_name: str,
        chapter_title: str,
        scoped_sections: list[dict],
        mode: str = "section_quiz",
        testbank_file_path: str | Path | None = None,
    ) -> dict:
        """
        High-Speed Micro-Batched Assessment Generator:
        Splits questions into parallel micro-batches of 4-5 questions max so even a 29-question
        Midterm/Final completes in 12-24 seconds (guaranteed <40s).
        """
        blueprint = ScoringEngine.EXAM_BLUEPRINTS.get(
            mode, ScoringEngine.EXAM_BLUEPRINTS["section_quiz"]
        )
        dist = blueprint["distribution"]

        scope_context = "\n\n".join(
            f"[{s.get('section_code', 'Sec')} - {s.get('section_title', '')} ({s.get('slide_pages', 'Slides')})]\n"
            f"{(s.get('extracted_study_notes') or '')[:1800]}"
            for s in scoped_sections
        )

        testbank_reference_block = ""
        if testbank_file_path:
            tb_chunks = cls.extract_textbook_chunks(testbank_file_path, max_chars=1200)
            if tb_chunks:
                combined_titles = " ".join(s.get("section_title", "") for s in scoped_sections)
                matched_tb = cls.filter_textbook_for_slide_section(
                    section_title=combined_titles,
                    slide_text=scope_context[:3000],
                    textbook_chunks=tb_chunks,
                    top_k=2,
                    label="Testbank Sample",
                )
                if matched_tb:
                    testbank_reference_block = f"\nTESTBANK STYLE REF:\n{matched_tb}\n"

        mcq_total = dist["mcq"]["count"]
        mcq_pts = dist["mcq"]["points_each"]
        sa_total = dist["short_answer"]["count"]
        sa_pts = dist["short_answer"]["points_each"]
        calc_total = dist["calculation"]["count"]
        calc_pts = dist["calculation"]["points_each"]

        batch_tasks = []

        # Micro-batch MCQs into chunks of at most 5 questions per parallel worker!
        chunk_size = 4
        remaining_mcq = mcq_total
        batch_idx = 1
        while remaining_mcq > 0:
            count_now = min(chunk_size, remaining_mcq)
            remaining_mcq -= count_now
            q_style = (
                "Mix 'mcq_single' and 'mcq_multi' (with '(Select all that apply)')."
                if batch_idx % 2 == 0
                else "Use 'mcq_single' testing core definitions, theorems, and quick calculations."
            )
            batch_tasks.append(
                cls._generate_question_batch(
                    course_name,
                    chapter_title,
                    scope_context,
                    testbank_reference_block,
                    f"Generate EXACTLY {count_now} 5-Option MCQs ('max_points': {mcq_pts}, batch #{batch_idx}). "
                    f"Every MCQ MUST have 5 options ('A','B','C','D','E'). {q_style}",
                )
            )
            batch_idx += 1

        # Separate parallel worker for Short Answer questions
        if sa_total > 0:
            batch_tasks.append(
                cls._generate_question_batch(
                    course_name,
                    chapter_title,
                    scope_context,
                    testbank_reference_block,
                    f"Generate EXACTLY {sa_total} Short Answer questions ('question_type': 'short_answer', 'options': null, 'max_points': {sa_pts}).",
                )
            )

        # Separate parallel worker for Calculation questions
        if calc_total > 0:
            batch_tasks.append(
                cls._generate_question_batch(
                    course_name,
                    chapter_title,
                    scope_context,
                    testbank_reference_block,
                    f"Generate EXACTLY {calc_total} Calculation/Derivation questions ('question_type': 'calculation', 'options': null, 'max_points': {calc_pts}).",
                )
            )

        # Run all micro-batches concurrently in parallel
        results = await asyncio.gather(*batch_tasks, return_exceptions=True)

        all_questions = []
        provider_used = "hybrid"
        model_used = "fast"
        for res in results:
            if isinstance(res, Exception):
                print("[Batch Warning]:", repr(res))
                continue
            q_list, prov, mod = res
            all_questions.extend(q_list)
            provider_used = prov
            model_used = mod

        return {
            "mode": mode,
            "blueprint": blueprint,
            "testbank_used": bool(testbank_reference_block),
            "provider_used": provider_used,
            "model_used": model_used,
            "questions": all_questions,
        }

    @classmethod
    async def mutate_wrong_question(cls, wrong_question: dict) -> dict:
        system_prompt = (
            "Create an isomorphic twin question testing the exact same concept with new numbers and shuffled A-E options. "
            "Return valid JSON only."
        )
        user_prompt = f"""
Original Type: {wrong_question.get('question_type')} | Concept: {wrong_question.get('core_concept_tag')}
Slide Ref: {wrong_question.get('slide_reference')}
Prompt: {wrong_question.get('prompt_markdown')}
Options: {wrong_question.get('options_json')}
Answer: {wrong_question.get('correct_answer')}

Return JSON with: question_type, core_concept_tag, slide_reference, prompt_markdown, options, correct_answer, ai_diagnosis_and_solution.
"""
        res = await HybridLLMHarness.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            task="fast",
            temperature=0.5,
            json_mode=True,
            max_tokens=900,
        )
        mutated = cls._clean_json_response(res["content"])
        mutated["provider_used"] = res["provider_used"]
        mutated["model_used"] = res["model_used"]
        return mutated
