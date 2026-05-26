from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "dry_run_completed", "rejected"]


@dataclass(frozen=True)
class JobDefinition:
    job_type: str
    label: str
    description: str
    category: str
    dry_run_default: bool = True
    write_capable: bool = False
    confirmation_required: str | None = None
    triggerable_from_api: bool = False
    adapter: str = "manual_command"
    command: str | None = None
    current_status: str = "available"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobRunRequest(BaseModel):
    job_type: str
    dry_run: bool = True
    write: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    confirm: str | None = None


class JobRunRecord(BaseModel):
    job_run_id: str
    job_type: str
    status: JobStatus
    dry_run: bool
    write_requested: bool
    confirm: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
    created_by: str = "system"
    source: str = "jobs_v1"
    version: str = "job_registry_v1"
