"""
Typed payloads for the /internal/* endpoints.

These are the one untrusted entry point that reaches MongoDB - the webhook is
already signature-verified, so its payloads are trusted GitHub data. We strictly
type only the fields that flow into database filters or GitHub API paths
(repository.id, installation.id, the SHAs, the PR number), so a value like
{"$ne": null} is rejected as a 422 instead of becoming a Mongo query operator.
extra="allow" keeps every other GitHub field intact for the pipeline downstream.
"""

from pydantic import BaseModel, ConfigDict


class _Owner(BaseModel):
    model_config = ConfigDict(extra="allow")
    login: str


class _Repository(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    name: str
    full_name: str
    default_branch: str = "main"
    owner: _Owner | None = None


class _Installation(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int


class _PullRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    number: int


class RunPipelinePayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    repository: _Repository
    installation: _Installation
    before: str | None = None
    after: str


class FeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    repository: _Repository
    installation: _Installation
    pull_request: _PullRequest