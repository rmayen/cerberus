"""Render an analysis report as HTML or PDF from gathered, primitive data."""

import html
from dataclasses import dataclass

from fpdf import FPDF
from fpdf.enums import WrapMode, XPos, YPos

from app.reports.containment import Recommendation


@dataclass
class ReportData:
    sample_sha256: str
    filename: str
    job_id: int
    status: str
    conditions: dict[str, object]
    timeline: list[tuple[int, str, str, str]]  # sequence, category, action, target
    findings: list[tuple[str, str, str, str]]  # category, title, severity, explanation
    iocs: list[tuple[str, str]]  # type, value
    attack: list[tuple[str, str, str, str]]  # id, name, tactic, explanation
    containment: list[Recommendation]
    notes: str | None = None


def _summary(d: ReportData) -> str:
    highs = sum(1 for (_, _, sev, _) in d.findings if sev == "high")
    return (
        f"Analysis job {d.job_id} for sample {d.sample_sha256[:16]}… ({d.filename}). "
        f"Status: {d.status}. Observed {len(d.findings)} behavioral finding(s) "
        f"({highs} high severity), {len(d.iocs)} indicator(s), and {len(d.attack)} "
        f"ATT&CK technique(s). Findings and mappings describe observed behavior and "
        f"do not assert certainty."
    )


def build_html(d: ReportData) -> str:
    e = html.escape

    def rows(items: list[list[str]], headers: list[str]) -> str:
        head = "".join(f"<th>{e(h)}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row) + "</tr>" for row in items
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    findings_html = rows(
        [[cat, title, sev, expl] for (cat, title, sev, expl) in d.findings],
        ["Category", "Finding", "Severity", "Explanation"],
    )
    ioc_html = rows([[t, v] for (t, v) in d.iocs], ["Type", "Value"])
    attack_html = rows(
        [[tid, name, tactic, expl] for (tid, name, tactic, expl) in d.attack],
        ["Technique", "Name", "Tactic", "Explanation"],
    )
    timeline_html = rows(
        [[str(seq), cat, action, target] for (seq, cat, action, target) in d.timeline],
        ["#", "Category", "Action", "Target"],
    )
    containment_html = "".join(
        f"<li><strong>{e(r.action)}</strong><br><span>{e(r.rationale)}</span></li>"
        for r in d.containment
    )
    notes_html = e(d.notes) if d.notes else "<em>No analyst notes provided.</em>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Cerberus Report — Job {d.job_id}</title>
<style>
 body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#1a1a1a;margin:2rem}}
 body{{line-height:1.5}}
 h1{{font-size:1.5rem}}
 h2{{font-size:1.1rem;border-bottom:1px solid #ddd;padding-bottom:.2rem;margin-top:1.6rem}}
 table{{border-collapse:collapse;width:100%;font-size:.85rem;margin-top:.4rem}}
 th,td{{border:1px solid #e0e0e0;padding:6px 8px;text-align:left;vertical-align:top}}
 th{{background:#f4f4f4}} .muted{{color:#666}} ul{{padding-left:1.2rem}} li{{margin-bottom:.5rem}}
</style></head><body>
<h1>Cerberus Analysis Report</h1>
<p class="muted">Sample {e(d.sample_sha256)} &middot; job {d.job_id} &middot;
 conditions {e(str(d.conditions))}</p>
<h2>Executive Summary</h2><p>{e(_summary(d))}</p>
<h2>Behavior Findings</h2>{findings_html}
<h2>MITRE ATT&amp;CK Mapping</h2>{attack_html}
<h2>Indicators of Compromise</h2>{ioc_html}
<h2>Timeline</h2>{timeline_html}
<h2>Containment Recommendations</h2><ul>{containment_html}</ul>
<h2>Analyst Notes</h2><p>{notes_html}</p>
</body></html>"""


def _latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def build_pdf(d: ReportData) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def cell(text: str, size: int, style: str, line: int) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(
            0, line, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT, wrapmode=WrapMode.CHAR
        )

    def heading(text: str) -> None:
        cell(text, 13, "B", 7)
        pdf.ln(1)

    def body(text: str) -> None:
        cell(text, 10, "", 5)

    cell("Cerberus Analysis Report", 16, "B", 9)
    body(f"Sample {d.sample_sha256}")
    body(f"Job {d.job_id} | status {d.status} | conditions {d.conditions}")
    pdf.ln(2)

    heading("Executive Summary")
    body(_summary(d))
    pdf.ln(1)

    heading("Behavior Findings")
    for cat, title, sev, expl in d.findings:
        body(f"[{sev.upper()}] {title} ({cat}): {expl}")

    heading("MITRE ATT&CK Mapping")
    for tid, name, tactic, expl in d.attack:
        body(f"{tid} {name} ({tactic}): {expl}")

    heading("Indicators of Compromise")
    for t, v in d.iocs:
        body(f"{t}: {v}")

    heading("Containment Recommendations")
    for r in d.containment:
        body(f"- {r.action}\n  {r.rationale}")

    heading("Analyst Notes")
    body(d.notes or "No analyst notes provided.")

    return bytes(pdf.output())
