from google import genai
from google.genai import types
from google.genai import errors
from tenacity import (
    retry, wait_exponential, stop_after_attempt,
    retry_if_exception, before_sleep_log,
)
from app.config import settings
import asyncio
import logging

logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.GEMINI_API_KEY)

_MODELS = {
    "flash": "gemini-3.1-flash-lite",   # cheap: analysis, scoring, JSON extraction
    "pro":   "gemini-3.5-flash",        # most capable: doc rewriting
}


class TransientGeminiError(Exception):
    """Empty/blocked response — worth retrying."""


class GeminiTruncatedError(Exception):
    """Output hit max_output_tokens — retrying won't help; fail loudly."""


def _is_transient(exc: Exception) -> bool:
    """Retry ONLY on things that might succeed on a second attempt."""
    if isinstance(exc, (asyncio.TimeoutError, TransientGeminiError)):
        return True
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        return code == 429 or (isinstance(code, int) and 500 <= code < 600)
    return False


@retry(
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception(_is_transient),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def call_gemini(
    prompt: str,
    model: str = "flash",
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> str:
    """
    Unified Gemini call.
      model="flash" -> gemini-3.1-flash-lite (analysis/scoring/JSON)
      model="pro"   -> gemini-3.5-flash      (doc rewriting)
    Retries only on 429 / 5xx / timeouts. Raises on truncation so callers
    never commit a half-written file.
    """
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=_MODELS[model],
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        ),
        timeout=90.0,
    )

    candidate = (response.candidates or [None])[0]
    finish = getattr(candidate, "finish_reason", None)
    finish_name = getattr(finish, "name", str(finish))

    try:
        text = response.text
    except Exception:
        text = None

    if not text:
        # No usable text (often a safety block) — let tenacity retry it.
        raise TransientGeminiError(f"empty response (finish_reason={finish_name})")

    if finish_name == "MAX_TOKENS":
        # Partial output: do NOT return a truncated document.
        raise GeminiTruncatedError(
            f"output truncated at max_tokens={max_tokens} (model={model})"
        )

    return text.strip()