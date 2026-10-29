from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    Confidence,
    IocType,
    JobStatus,
    Role,
    SampleStatus,
    Severity,
    TelemetryCategory,
)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.viewer


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    username: str = Field(max_length=64)


class PasswordResetIssued(BaseModel):
    # Local implementation: no email transport, so the token is returned directly.
    # In a production deployment this would be delivered out of band instead.
    reset_token: str
    expires_at: datetime


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor_user_id: int | None
    action: str
    detail: str | None
    ip: str | None


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_by: int | None
    created_at: datetime


class SampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sha256: str
    filename: str
    size_bytes: int
    content_type: str | None
    detected_type: str | None
    status: SampleStatus
    # Read-only. Derived from the sample's latest analysis job; never stored on the sample.
    analysis_status: Literal["not_analyzed", "analyzing", "analyzed", "failed"] = "not_analyzed"
    tags: list[str]
    case_id: int | None
    uploaded_by: int | None
    created_at: datetime


class SampleUploadResult(BaseModel):
    sample: SampleRead
    duplicate: bool


class TagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=50)


class IocRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: IocType
    value: str
    source_job_id: int | None
    first_seen: datetime


class JobCreate(BaseModel):
    sample_id: int
    executor: str = "simulated"
    conditions: dict[str, object] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sample_id: int
    executor: str
    conditions: dict[str, object]
    status: JobStatus
    result: dict[str, object] | None
    error: str | None
    duration_ms: int | None
    submitted_by: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TelemetryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    sequence: int
    category: TelemetryCategory
    action: str
    target: str
    raw: dict[str, object]
    created_at: datetime


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    category: str
    title: str
    severity: Severity
    explanation: str
    evidence: list[dict[str, object]]
    created_at: datetime


class AttackMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    technique_id: str
    technique_name: str
    tactic: str
    explanation: str
    evidence: list[dict[str, object]]
    created_at: datetime


class DifferentialCreate(BaseModel):
    sample_id: int
    baseline_conditions: dict[str, object] = Field(default_factory=dict)
    variations: list[dict[str, object]] = Field(min_length=1, max_length=20)
    executor: str = "simulated"
    timeout_seconds: int = Field(default=60, ge=1, le=3600)


class DifferentialFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    axis: str
    baseline_value: object | None
    variant_value: object | None
    summary: str
    confidence: Confidence
    added: list[dict[str, object]]
    removed: list[dict[str, object]]
    created_at: datetime


class DifferentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sample_id: int
    executor: str
    baseline_conditions: dict[str, object]
    status: JobStatus
    created_by: int | None
    created_at: datetime
    finished_at: datetime | None
    findings: list[DifferentialFindingRead]
