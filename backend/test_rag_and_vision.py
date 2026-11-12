import asyncio
from pathlib import Path
from PIL import Image, ImageDraw
from services.slide_scope_rag import SlideScopeRAG
from services.vision_grader import VisionSolutionGrader

async def main():
    print("=== 1. Testing Strict Slide-Prioritized Section Mapping ===")
    sample_slides = [
        {"slide_number": 1, "text": "Chapter 4: Matrix Algebra\nSection 4.1: Gauss-Jordan Elimination\nRow operations: R_i <-> R_j, k*R_i, R_i + k*R_j."},
        {"slide_number": 2, "text": "Section 4.1 (cont.): Reduced Row Echelon Form (RREF) and solving Ax = b."},
        {"slide_number": 3, "text": "Section 4.3: Matrix Inverses via [A | I] -> [I | A^-1]. (Note: Section 4.2 Determinants is skipped in this course)."}
    ]
    sections = await SlideScopeRAG.map_slide_sections(
        course_name="College Mathematics",
        chapter_title="Chapter 4: Matrix Algebra",
        slides_data=sample_slides,
    )
    for s in sections:
        print(f" -> Mapped: {s.get('section_code')} | {s.get('section_title')} ({s.get('slide_pages')})")

    print("\n=== 2. Testing Wrong Question Concept Mutation (5-Option A-E) ===")
    sample_wrong = {
        "question_type": "mcq_multi",
        "core_concept_tag": "Elementary Row Operations & RREF",
        "slide_reference": "Slides 1-2",
        "prompt_markdown": "Which of the following matrices are in Reduced Row Echelon Form (RREF)? (Select all that apply)",
        "options_json": '{"A": "[[1, 0], [0, 1]]", "B": "[[1, 2], [0, 1]]", "C": "[[1, 3], [0, 0]]", "D": "[[0, 1], [1, 0]]", "E": "[[2, 0], [0, 1]]"}',
        "correct_answer": "A, C",
    }
    mutated = await SlideScopeRAG.mutate_wrong_question(sample_wrong)
    print(f" -> Mutated Prompt: {mutated.get('prompt_markdown')}")
    print(f" -> New Correct Answer: {mutated.get('correct_answer')} (via {mutated.get('provider_used')})")

    print("\n=== 3. Testing Handwritten Solution OCR & Step-by-Step Partial Credit Grader ===")
    snap_dir = Path(__file__).resolve().parent / "storage" / "handwritten_snaps"
    snap_dir.mkdir(parents=True, exist_ok=True)
    img_path = snap_dir / "sample_solution.png"

    # Generate a synthetic handwritten-style math image for testing
    img = Image.new("RGB", (680, 220), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((25, 25), "Student Work: Find derivative of f(x) = x^3 + 4x^2 - 5x + 2", fill=(0, 0, 0))
    draw.text((25, 75), "Step 1: Apply power rule term by term: d/dx(x^n) = n*x^(n-1)", fill=(20, 20, 120))
    draw.text((25, 120), "Step 2: f'(x) = 3x^2 + 8x - 5 + 2  (forgot derivative of constant 2 is 0)", fill=(20, 20, 120))
    draw.text((25, 165), "Final Answer: f'(x) = 3x^2 + 8x - 3", fill=(180, 0, 0))
    img.save(img_path)

    grade_res = await VisionSolutionGrader.grade_written_solution(
        question_prompt="Differentiate f(x) = x^3 + 4x^2 - 5x + 2 with respect to x.",
        official_rubric_and_answer="Step 1 (4 pts): Power rule on x^3 -> 3x^2 and 4x^2 -> 8x. Step 2 (3 pts): -5x -> -5 and constant 2 -> 0. Final Answer: f'(x) = 3x^2 + 8x - 5 (Total: 7 pts).",
        max_points=7.0,
        handwritten_image_path=img_path,
    )
    print(f" -> Score Awarded: {grade_res['score_awarded']} / {grade_res['max_points']} pts")
    print(f" -> Step Breakdown: {grade_res['step_breakdown']}")
    print(f" -> Error Diagnosis: {grade_res['error_diagnosis']}")

if __name__ == "__main__":
    asyncio.run(main())
