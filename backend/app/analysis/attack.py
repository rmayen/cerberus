"""Map observed behaviors to MITRE ATT&CK techniques.

Each behavior category maps to a well-known technique. Mappings are explained and
carry the finding's evidence; they describe what was *observed*, not certainty.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Technique:
    technique_id: str
    name: str
    tactic: str
    rationale: str


_MAP: dict[str, Technique] = {
    "network": Technique(
        "T1071", "Application Layer Protocol", "Command and Control",
        "outbound communication consistent with command-and-control",
    ),
    "persistence": Technique(
        "T1547.001", "Registry Run Keys / Startup Folder", "Persistence",
        "an autostart entry that would let the sample survive a reboot",
    ),
    "registry_modification": Technique(
        "T1112", "Modify Registry", "Defense Evasion",
        "creation or modification of registry keys",
    ),
    "service_creation": Technique(
        "T1543.003", "Create or Modify System Process: Windows Service", "Persistence",
        "creation or modification of a system service",
    ),
    "scheduled_task_creation": Technique(
        "T1053.005", "Scheduled Task/Job: Scheduled Task", "Execution",
        "creation of a scheduled task",
    ),
    "privilege_escalation": Technique(
        "T1134", "Access Token Manipulation", "Privilege Escalation",
        "an operation associated with elevating privileges",
    ),
}


@dataclass(frozen=True)
class AttackMappingResult:
    technique_id: str
    technique_name: str
    tactic: str
    explanation: str
    evidence: list[dict[str, Any]]


class _Finding(Protocol):
    @property
    def category(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def evidence(self) -> list[dict[str, Any]]: ...


def map_findings(findings: Sequence[_Finding]) -> list[AttackMappingResult]:
    results: list[AttackMappingResult] = []
    seen: set[str] = set()
    for finding in findings:
        technique = _MAP.get(finding.category)
        if technique is None or technique.technique_id in seen:
            continue
        seen.add(technique.technique_id)
        explanation = (
            f"Observed behavior {finding.title!r} maps to {technique.technique_id} "
            f"({technique.name}, {technique.tactic} tactic): {technique.rationale}."
        )
        results.append(
            AttackMappingResult(
                technique.technique_id,
                technique.name,
                technique.tactic,
                explanation,
                list(finding.evidence),
            )
        )
    return results
