from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum
import uuid


class PipelineStatus(str, Enum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class PipelineRun(BaseModel):
    run_id:           str  = Field(default_factory=lambda: str(uuid.uuid4()))
    repo_id:          int
    commit_sha:       str
    status:           PipelineStatus = PipelineStatus.RUNNING
    docs_updated:     List[str] = []
    mr_url:           Optional[str] = None
    mr_id:            Optional[int] = None
    duration_seconds: Optional[float] = None
    error_message:    Optional[str] = None
    agent_session_id: Optional[str] = None
    merged_at:        Optional[datetime] = None
    skip_reason:      Optional[str] = None
    error_type:       Optional[str] = None
    stage_ms:         dict = {}
    tokens_total:     int = 0
    cost_usd:         float = 0.0
    gemini_calls:     int = 0
    run_id:           Optional[str] = None
    created_at:       datetime = Field(default_factory=datetime.utcnow)


class CorrectionPattern(BaseModel):
    repo_id:          int
    repo_key:         Optional[str] = None  # Added for GitHub: "owner/repo" format
    run_id: Optional[str] = None
    mr_id:            int
    doc_path:         str
    doc_type:         str
    ai_written:       str
    human_corrected:  str
    correction_delta: str
    created_at:       datetime = Field(default_factory=datetime.utcnow)