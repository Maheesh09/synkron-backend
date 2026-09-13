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
import contextvars

_usage_ctx = contextvars.ContextVar("gemini_usage", default=None)

_PRICING = {
    "gemini-3.1-flash-lite": {"in": 0.10, "out": 0.40},
    "gemini-3.5-flash":      {"in": 0.30, "out": 2.50},
}

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


def start_usage_tracking() -> dict:
    bucket = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0,
              "total_tokens": 0, "cost_usd": 0.0, "by_model": {}}
    _usage_ctx.set(bucket)
    return bucket


def get_usage() -> dict:
    return _usage_ctx.get() or {}


def _record_usage(model_name: str, usage) -> None:
    bucket = _usage_ctx.get()
    if bucket is None or usage is None:
        return
    p = getattr(usage, "prompt_token_count", 0) or 0
    o = getattr(usage, "candidates_token_count", 0) or 0
    t = getattr(usage, "total_token_count", 0) or (p + o)
    price = _PRICING.get(model_name, {"in": 0.0, "out": 0.0})

    bucket["calls"] += 1
    bucket["prompt_tokens"] += p
    bucket["output_tokens"] += o
    bucket["total_tokens"] += t
    bucket["cost_usd"] = round(
        bucket["cost_usd"] + (p * price["in"] + o * price["out"]) / 1_000_000, 6
    )
    m = bucket["by_model"].setdefault(model_name, {"calls": 0, "tokens": 0})
    m["calls"] += 1
    m["tokens"] += t

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
    _record_usage(_MODELS[model], getattr(response, "usage_metadata", None))
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