from google import genai
from google.genai import types
from app.config import settings
import logging

logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.GEMINI_API_KEY)

_MODELS = {
    "flash": "gemini-2.0-flash",
    "pro": "gemini-2.0-pro",
}


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
    try:
        response = await client.aio.models.generate_content(
            model=_MODELS[model],
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini call failed (model={model}): {e}")
        raise
