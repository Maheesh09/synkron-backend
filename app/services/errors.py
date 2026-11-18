"""Decide whether a pipeline failure is worth retrying.

/internal/run-pipeline answers Cloud Tasks with 5xx only for errors that might
succeed on another attempt (rate limits, timeouts, upstream 5xx, a Mongo
blip). Everything else is permanent: the run is marked failed and the task is
acknowledged with 200 so the queue doesn't retry pointlessly.
"""

import asyncio

import httpx
from pymongo.errors import ConnectionFailure

from app.services.gemini import TransientGeminiError

try:
    from google.genai import errors as _genai_errors
except ImportError:  # pragma: no cover
    _genai_errors = None


class PipelineRetry(Exception):
    """Raised by the orchestrator to ask Cloud Tasks for another attempt."""

    def __init__(self, cause: BaseException):
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.cause = cause


def _retryable_status(code) -> bool:
    return code == 429 or (isinstance(code, int) and 500 <= code < 600)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TransientGeminiError, asyncio.TimeoutError, TimeoutError)):
        return True
    # Timeouts, connection resets, DNS failures talking to GitHub or Gemini.
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return _retryable_status(exc.response.status_code)
    if _genai_errors is not None and isinstance(exc, _genai_errors.APIError):
        return _retryable_status(getattr(exc, "code", None))
    # Mongo unreachable / failover in progress.
    if isinstance(exc, ConnectionFailure):
        return True
    return False
