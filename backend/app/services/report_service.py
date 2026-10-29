from sqlalchemy.orm import Session

from app.models import AnalysisJob, Sample
from app.reports.builder import ReportData, build_html, build_pdf
from app.reports.containment import recommend
from app.services import attack_service, behavior_service, ioc_service, telemetry_service


def gather(db: Session, job: AnalysisJob, notes: str | None = None) -> ReportData:
    sample = db.get(Sample, job.sample_id)
    sha = sample.sha256 if sample else ""
    filename = sample.filename if sample else ""

    telemetry = telemetry_service.list_events(db, job.id)
    findings = behavior_service.list_findings(db, job.id)
    iocs = ioc_service.list_iocs(db, job.sample_id)
    attack = attack_service.list_mappings(db, job.id)

    return ReportData(
        sample_sha256=sha,
        filename=filename,
        job_id=job.id,
        status=job.status.value,
        conditions=job.conditions,
        timeline=[(e.sequence, e.category.value, e.action, e.target) for e in telemetry],
        findings=[(f.category, f.title, f.severity.value, f.explanation) for f in findings],
        iocs=[(i.type.value, i.value) for i in iocs],
        attack=[(m.technique_id, m.technique_name, m.tactic, m.explanation) for m in attack],
        containment=recommend(findings, iocs),
        notes=notes,
    )


def render_html(db: Session, job: AnalysisJob, notes: str | None = None) -> str:
    return build_html(gather(db, job, notes))


def render_pdf(db: Session, job: AnalysisJob, notes: str | None = None) -> bytes:
    return build_pdf(gather(db, job, notes))
