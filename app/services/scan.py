"""
POST /api/scan/exam
Accepts a PDF or image file, converts pages to base64 images,
sends to OpenRouter vision model, returns structured questions JSON.

Install requirements:
  pip install openai pdf2image pillow
  # Also needs poppler for pdf2image:
  # Windows: download from https://github.com/oschwartz10612/poppler-windows/releases
  #           extract and add bin/ to PATH
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
import base64
import json
import io
import time
from typing import List

from ..database import get_db
from ..routers.auth import get_current_user
from .. import models
from ..config import settings

router = APIRouter(prefix="/scan", tags=["Scan"])

GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# ── Helpers ───────────────────────────────────────────────────────────────────

def pdf_to_base64_images(pdf_bytes: bytes) -> List[str]:
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=150, fmt="PNG")
        result = []
        for img in images[:6]:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
        return result
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="pdf2image суулгаагүй байна. 'pip install pdf2image' ажиллуулна уу."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF боловсруулах алдаа: {str(e)}")


def image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


SCAN_PROMPT = """You are an exam parser. Analyze this exam document image and extract ALL questions.

For each question, determine its type and return structured JSON.

Question types:
- "multiple_choice": has lettered/numbered options (A/B/C/D or 1/2/3/4)
- "true_false": asks true or false / үнэн эсвэл худал
- "short_answer": expects a short text answer, fill-in-the-blank
- "essay": asks for a longer written response, explanation, or analysis
- "code": asks to write or analyze code

Return ONLY a valid JSON array, no markdown, no explanation, just the raw JSON array.

Each question object must follow this exact schema:
{
  "type": "multiple_choice" | "true_false" | "short_answer" | "essay" | "code",
  "question": "The full question text",
  "points": 10,
  "options": ["option1", "option2", ...],        // only for multiple_choice, without letter prefix
  "correct_answer": "the correct option text",   // for MC, true_false, short_answer (omit if unknown)
  "min_words": 100,                              // only for essay
  "language": "python",                          // only for code questions
  "starter_code": ""                             // only for code questions
}

Rules:
- "points" default to 10 if not specified in the document
- For multiple_choice, "options" must be an array without the letter prefix (A/B/C/D)
- For multiple_choice, "correct_answer" should match exactly one of the option strings
- If the correct answer is not shown, omit "correct_answer"
- For true_false, "correct_answer" is either "true" or "false" (lowercase), omit if unknown
- Preserve the original language of the questions (Mongolian, English, etc.)
- Include ALL questions you can find
- Do not add questions that don't exist in the document"""


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/exam")
async def scan_exam(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Зөвхөн багш ашиглах боломжтой")

    if not settings.GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY тохируулагдаагүй байна")

    file_bytes = await file.read()
    content_type = file.content_type or ""

    if "pdf" in content_type or (file.filename or "").lower().endswith(".pdf"):
        b64_images = pdf_to_base64_images(file_bytes)
    elif content_type.startswith("image/"):
        b64_images = [image_to_base64(file_bytes)]
    else:
        raise HTTPException(
            status_code=400,
            detail="PDF эсвэл зураг (PNG, JPG) файл оруулна уу"
        )

    if not b64_images:
        raise HTTPException(status_code=400, detail="Файлаас зураг гарсангүй")

    # Build message content with all page images
    content = []
    for b64 in b64_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })
    content.append({"type": "text", "text": SCAN_PROMPT})

    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=settings.GROQ_API_KEY,
        )
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
        )
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openai суулгаагүй байна. 'pip install openai' ажиллуулна уу."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Groq API алдаа: {str(e)}")

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        questions = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Хариултыг задлах амжилтгүй. Дахин оролдоно уу."
        )

    if not isinstance(questions, list):
        raise HTTPException(status_code=500, detail="Хүлээгдсэн формат биш байна")

    for i, q in enumerate(questions):
        q["id"] = f"q{int(time.time())}_{i}"
        q["points"] = int(round(float(q.get("points", 10))))
        q.setdefault("type", "short_answer")

    return {"questions": questions, "page_count": len(b64_images)}
