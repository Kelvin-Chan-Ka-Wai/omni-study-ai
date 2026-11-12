import base64
import json
import mimetypes
import re
from pathlib import Path
from services.llm_harness import HybridLLMHarness


class VisionSolutionGrader:
    @staticmethod
    def encode_image_to_data_url(image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Handwritten solution image not found: {path}")
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/png"
        b64_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{b64_data}"

    @staticmethod
    def _try_local_latex_ocr(image_path: str | Path) -> str | None:
        try:
            from PIL import Image
            import importlib
            LatexOCR = importlib.import_module("pix2tex.cli").LatexOCR

            img = Image.open(str(image_path))
            model = LatexOCR()
            latex_str = model(img)
            return f"$$ {latex_str} $$"
        except Exception:
            return None

    @classmethod
    async def transcribe_handwritten_image(cls, image_path: str | Path) -> dict:
        data_url = cls.encode_image_to_data_url(image_path)

        ocr_prompt = (
            "Transcribe all handwritten text, mathematical equations, matrices, and derivation steps "
            "from this image into clean Markdown and LaTeX ($...$ for inline, $$...$$ for display equations). "
            "Preserve the exact line-by-line step order written by the student. Do not solve or correct errors yet."
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ocr_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]

        try:
            res = await HybridLLMHarness.chat(
                messages=messages,
                task="vision",
                temperature=0.1,
                json_mode=False,
            )
            return {
                "transcribed_latex": res["content"].strip(),
                "ocr_provider": res["provider_used"],
                "ocr_model": res["model_used"],
            }
        except Exception as vision_err:
            local_tex = cls._try_local_latex_ocr(image_path)
            if local_tex:
                return {
                    "transcribed_latex": local_tex,
                    "ocr_provider": "local_pix2tex",
                    "ocr_model": "pix2tex-latex-ocr",
                }
            raise RuntimeError(f"Vision OCR failed: {vision_err}") from vision_err

    @classmethod
    async def grade_written_solution(
        cls,
        question_prompt: str,
        official_rubric_and_answer: str,
        max_points: float,
        typed_answer: str | None = None,
        handwritten_image_path: str | Path | None = None,
    ) -> dict:
        ocr_info = {
            "transcribed_latex": "",
            "ocr_provider": "none",
            "ocr_model": "none",
        }

        if handwritten_image_path:
            try:
                ocr_info = await cls.transcribe_handwritten_image(handwritten_image_path)
            except Exception as e:
                ocr_info["transcribed_latex"] = f"(Image OCR unavailable: {e})"

        combined_student_work = "\n\n".join(
            part
            for part in [
                f"[Typed Solution]:\n{typed_answer}" if typed_answer else "",
                f"[Handwritten Solution OCR]:\n{ocr_info['transcribed_latex']}"
                if ocr_info["transcribed_latex"]
                else "",
            ]
            if part
        ).strip()

        if not combined_student_work:
            return {
                "score_awarded": 0.0,
                "max_points": max_points,
                "transcribed_student_work": "(No answer submitted)",
                "step_breakdown": [],
                "error_diagnosis": "Unanswered question.",
                "ai_feedback_and_solution": f"No solution provided. Official solution:\n{official_rubric_and_answer}",
                "ocr_provider": ocr_info["ocr_provider"],
                "grading_provider": "none",
            }

        system_prompt = (
            "You are a fair, rigorous university mathematics and data science grader. "
            "Evaluate the student's step-by-step work against the official rubric. "
            "Award partial credit for correct setup, theorems, and intermediate derivation steps even if there is a minor arithmetic slip at the end. "
            "Return valid JSON only."
        )

        user_prompt = f"""
Question Prompt:
{question_prompt}

Official Solution & Rubric (Max Points: {max_points}):
{official_rubric_and_answer}

Student's Submitted Work:
{combined_student_work}

Evaluate the student's work and return a JSON object with these exact keys:
- "score_awarded": float between 0.0 and {max_points} (rounded to 1 decimal place)
- "step_breakdown": list of strings showing points awarded per step
- "error_diagnosis": concise 1-2 sentence explanation of the exact mistake made (or "No errors—full mastery!" if full marks)
- "ai_feedback_and_solution": comprehensive Markdown + LaTeX feedback comparing the student's steps with the complete official derivation.
"""

        res = await HybridLLMHarness.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            task="reasoning",
            temperature=0.2,
            json_mode=True,
        )

        raw = res["content"].strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fence:
            raw = fence.group(1).strip()
        graded = json.loads(raw)

        score = float(graded.get("score_awarded", 0.0))
        score = max(0.0, min(round(score, 2), float(max_points)))

        return {
            "score_awarded": score,
            "max_points": max_points,
            "transcribed_student_work": combined_student_work,
            "step_breakdown": graded.get("step_breakdown", []),
            "error_diagnosis": graded.get("error_diagnosis", ""),
            "ai_feedback_and_solution": graded.get("ai_feedback_and_solution", ""),
            "ocr_provider": ocr_info["ocr_provider"],
            "ocr_model": ocr_info["ocr_model"],
            "grading_provider": res["provider_used"],
            "grading_model": res["model_used"],
        }
