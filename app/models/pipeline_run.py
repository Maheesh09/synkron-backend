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
    created_at:       datetime = Field(default_factory=datetime.utcnow)


class CorrectionPattern(BaseModel):
    repo_id:          int
    mr_id:            int
    doc_path:         str
    doc_type:         str
    ai_written:       str
    human_corrected:  str
    correction_delta: str
    created_at:       datetime = Field(default_factory=datetime.utcnow)