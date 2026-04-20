from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..config import settings
from ..routers.auth import get_current_user
from .. import models
import anthropic
import json

router = APIRouter(prefix="/ai-detect", tags=["AI Detection"])


class AnalyzeRequest(BaseModel):
    text: str
    lang: str


def neutral_fallback(lang: str) -> dict:
    """
    Returns zeroed-out Claude scores so the frontend falls through
    to Pass B + Pass C statistical analysis only.
    The 'claude_unavailable' flag lets the frontend show a note if needed.
    """
    return {
        "formulaicStructureScore": 0,
        "emotionalAuthenticityScore": 0,
        "voiceConsistencyScore": 0,
        "specificityScore": 0,
        "phraseArtificialityScore": 0,
        "grammaticalPerfectionScore": 0,
        "language": lang,
        "mongolianAIPhrases": [],
        "englishAIPhrases": [],
        "hasPersonalMemory": False,
        "hasOpinionWithReasoning": False,
        "hasEmotionalVariance": False,
        "hasTypicalStudentErrors": False,
        "hasMongolianStudentPatterns": False,
        "claude_unavailable": True,
    }


@router.post("/analyze")
async def analyze_text(
    req: AnalyzeRequest,
    current_user: models.User = Depends(get_current_user),
):
    if not req.text or len(req.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Текст хэт богино байна")

    # If no API key configured, skip straight to fallback
    if not settings.ANTHROPIC_API_KEY:
        return neutral_fallback(req.lang)

    is_mongolian = req.lang in ("mongolian", "mixed")

    prompt = f"""You are a forensic linguistics expert specializing in distinguishing AI-generated text from student writing. You are analyzing a text that may be in English, Mongolian, or mixed.

CRITICAL RULES:
- You are ONLY extracting observable linguistic features. Do NOT decide if it's AI or human.
- Score every dimension honestly. Do not be lenient.
- Mongolian AI writing has its own patterns — do not penalize Mongolian writers for lacking English-language contractions.
- "Typical student errors" means mistakes REAL students make: wrong word choice, calque translations from native language, inconsistent formality, sentence fragments, repeated words.

TEXT LANGUAGE: {req.lang}
TEXT:
\"\"\"
{req.text}
\"\"\"

{"MONGOLIAN AI SIGNATURE PHRASES (copy exact occurrences if found): нэн тэргүүнд, юуны өмнө, дүгнэж хэлбэл, нэгтгэн дүгнэвэл, чухал үүрэг гүйцэтгэдэг, ихээхэн ач холбогдолтой, өнөөгийн нийгэмд, дараах байдлаар, нэн чухал асуудал, энэхүү асуудал, үүний зэрэгцээ, нэмж дурдвал, ерөнхийдөө авч үзвэл, дээр дурдсанчлан" if is_mongolian else ""}

Respond with ONLY raw JSON — no markdown fences, no preamble:

{{
  "formulaicStructureScore": <0-10>,
  "emotionalAuthenticityScore": <0-10>,
  "voiceConsistencyScore": <0-10>,
  "specificityScore": <0-10>,
  "phraseArtificialityScore": <0-10>,
  "grammaticalPerfectionScore": <0-10>,
  "language": "{req.lang}",
  "mongolianAIPhrases": [],
  "englishAIPhrases": [],
  "hasPersonalMemory": false,
  "hasOpinionWithReasoning": false,
  "hasEmotionalVariance": false,
  "hasTypicalStudentErrors": false,
  "hasMongolianStudentPatterns": false
}}"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return json.loads(raw)

    except anthropic.APIError:
        # Credit exhausted, invalid key, rate limit, etc. — silently fall back
        return neutral_fallback(req.lang)
    except Exception:
        return neutral_fallback(req.lang)