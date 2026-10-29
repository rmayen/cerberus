from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    viewer = "viewer"
    analyst = "analyst"
    administrator = "administrator"


class SampleStatus(StrEnum):
    quarantined = "quarantined"
    approved = "approved"
    analyzing = "analyzing"
    analyzed = "analyzed"
    failed = "failed"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
    cancelled = "cancelled"


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class IocType(StrEnum):
    domain = "domain"
    ip = "ip"
    url = "url"
    file_hash = "file_hash"
    registry_key = "registry_key"
    mutex = "mutex"
    service = "service"
    file_path = "file_path"


class TelemetryCategory(StrEnum):
    process = "process"
    file = "file"
    registry = "registry"
    service = "service"
    scheduled_task = "scheduled_task"
    dll = "dll"
    dns = "dns"
    network = "network"
    http = "http"
    tls = "tls"
    mutex = "mutex"
    persistence = "persistence"


# Allowed forward transitions; enforced by job_service to keep lifecycle safe.
JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.pending: {JobStatus.running, JobStatus.cancelled},
    JobStatus.running: {
        JobStatus.completed,
        JobStatus.failed,
        JobStatus.timed_out,
        JobStatus.cancelled,
    },
    JobStatus.completed: set(),
    JobStatus.failed: set(),
    JobStatus.timed_out: set(),
    JobStatus.cancelled: set(),
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.viewer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    """Server-side refresh tokens, stored hashed, so sessions can be revoked."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisJob(Base):
    """One execution of a sample under a set of environmental conditions."""

    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), index=True
    )
    executor: Mapped[str] = mapped_column(String(32), default="simulated")
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.pending, nullable=False, index=True
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    differential_id: Mapped[int | None] = mapped_column(
        ForeignKey("differential_analyses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DifferentialAnalysis(Base):
    """A set of runs of one sample that vary conditions to reveal dependencies."""

    __tablename__ = "differential_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), index=True
    )
    executor: Mapped[str] = mapped_column(String(32), default="simulated")
    baseline_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.pending, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    findings: Mapped[list["DifferentialFinding"]] = relationship(
        cascade="all, delete-orphan", order_by="DifferentialFinding.id"
    )


class DifferentialFinding(Base):
    """One observed behavioral dependency between the baseline and a variant."""

    __tablename__ = "differential_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("differential_analyses.id", ondelete="CASCADE"), index=True
    )
    axis: Mapped[str] = mapped_column(String(64))
    baseline_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    variant_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Confidence] = mapped_column(Enum(Confidence), default=Confidence.low)
    added: Mapped[list] = mapped_column(JSON, default=list)
    removed: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelemetryEvent(Base):
    """A single normalized observation from one analysis run.

    `target` is canonicalized (volatile fields like temp names and usernames
    replaced with placeholders) so runs can be compared by the differential
    engine; `raw` preserves the original detail.
    """

    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    category: Mapped[TelemetryCategory] = mapped_column(Enum(TelemetryCategory), index=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(1024))
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BehaviorFinding(Base):
    """An explainable behavioral observation derived from a job's telemetry."""

    __tablename__ = "behavior_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    severity: Mapped[Severity] = mapped_column(Enum(Severity), default=Severity.low)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ioc(Base):
    """An indicator of compromise extracted from a sample's analysis runs."""

    __tablename__ = "iocs"
    __table_args__ = (UniqueConstraint("sample_id", "type", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[IocType] = mapped_column(Enum(IocType), index=True)
    value: Mapped[str] = mapped_column(String(1024))
    source_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True
    )
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttackMapping(Base):
    """A MITRE ATT&CK technique observed in a run, with explanation and evidence."""

    __tablename__ = "attack_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True
    )
    technique_id: Mapped[str] = mapped_column(String(16), index=True)
    technique_name: Mapped[str] = mapped_column(String(255))
    tactic: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only record of security-relevant actions."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Case(Base):
    """An investigation grouping related samples and analysis."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Sample(Base):
    """An uploaded artifact under analysis. Stored encrypted and quarantined."""

    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detected_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stored_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[SampleStatus] = mapped_column(
        Enum(SampleStatus), default=SampleStatus.quarantined, nullable=False
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmergencyStop(Base):
    """Single-row platform switch. While active, no new analysis jobs or differential runs start.

    Existing job records are never changed by it.
    """

    __tablename__ = "emergency_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
