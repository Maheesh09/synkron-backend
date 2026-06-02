import google.generativeai as genai
from app.config import settings
import logging

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.GEMINI_API_KEY)

# Flash: fast, efficient — used for analysis and scoring
_flash = genai.GenerativeModel("gemini-2.0-flash")

# Pro: higher quality — used for documentation writing
_pro   = genai.GenerativeModel("gemini-2.0-pro")


async def call_gemini(
    prompt: str,
    model: str = "flash",
    temperature: float = 0.2,
    max_tokens: int = 8192
) -> str:
    """
    Unified Gemini call.

    model:
      "flash" — Gemini 2.0 Flash  (analysis, scoring, JSON extraction)
      "pro"   — Gemini 2.0 Pro    (doc section rewriting)

    temperature:
      0.1  → very deterministic (good for JSON output)
      0.15 → slightly creative  (good for doc writing while staying accurate)
      0.4+ → more creative      (not recommended for Synkron tasks)
    """
    gen_model = _flash if model == "flash" else _pro
    config = genai.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_tokens
    )
    try:
        response = await gen_model.generate_content_async(
            prompt,
            generation_config=config
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini call failed (model={model}): {e}")
        raise