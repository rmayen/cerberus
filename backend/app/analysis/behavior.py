"""Behavior analyzers.

Each analyzer inspects a run's normalized telemetry and, when its pattern is
present, emits one explainable finding with the supporting evidence. Findings
describe what was *observed*; they avoid asserting certainty.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Finding:
    category: str
    title: str
    severity: str  # low | medium | high
    explanation: str
    evidence: list[dict[str, Any]]


class _Event(Protocol):
    @property
    def category(self) -> str: ...
    @property
    def action(self) -> str: ...
    @property
    def target(self) -> str: ...


def _evidence(events: Sequence[_Event]) -> list[dict[str, Any]]:
    return [{"category": e.category, "action": e.action, "target": e.target} for e in events]


def _by_category(events: Sequence[_Event], *categories: str) -> list[_Event]:
    return [e for e in events if e.category in categories]


def _network(events: Sequence[_Event]) -> list[Finding]:
    matched = _by_category(events, "dns", "network", "http", "tls")
    if not matched:
        return []
    return [
        Finding(
            "network",
            "Outbound network communication",
            "medium",
            "The sample performed DNS lookups and/or outbound connections, which "
            "may indicate command-and-control or data exfiltration.",
            _evidence(matched),
        )
    ]


def _files(events: Sequence[_Event]) -> list[Finding]:
    matched = _by_category(events, "file")
    if not matched:
        return []
    return [
        Finding(
            "file_modification",
            "File system modification",
            "low",
            "The sample created or modified files on disk.",
            _evidence(matched),
        )
    ]


def _registry(events: Sequence[_Event]) -> list[Finding]:
    matched = _by_category(events, "registry")
    if not matched:
        return []
    return [
        Finding(
            "registry_modification",
            "Registry modification",
            "low",
            "The sample created or modified registry keys.",
            _evidence(matched),
        )
    ]


def _persistence(events: Sequence[_Event]) -> list[Finding]:
    matched = list(_by_category(events, "persistence"))
    # Registry autostart (Run keys) is a persistence signal too.
    matched += [e for e in events if e.category == "registry" and "\\run" in e.target.lower()]
    if not matched:
        return []
    return [
        Finding(
            "persistence",
            "Persistence mechanism",
            "high",
            "The sample established a persistence mechanism (such as a registry "
            "autostart entry), which may let it survive reboots.",
            _evidence(matched),
        )
    ]


def _services(events: Sequence[_Event]) -> list[Finding]:
    matched = _by_category(events, "service")
    if not matched:
        return []
    return [
        Finding(
            "service_creation",
            "Service creation",
            "medium",
            "The sample created or modified a system service.",
            _evidence(matched),
        )
    ]


def _scheduled_tasks(events: Sequence[_Event]) -> list[Finding]:
    matched = _by_category(events, "scheduled_task")
    if not matched:
        return []
    return [
        Finding(
            "scheduled_task_creation",
            "Scheduled task creation",
            "medium",
            "The sample created a scheduled task, a common persistence and "
            "execution technique.",
            _evidence(matched),
        )
    ]


def _privilege_escalation(events: Sequence[_Event]) -> list[Finding]:
    markers = {"elevate", "runas", "token_manipulation", "getsystem"}
    matched = [e for e in events if e.category == "process" and e.action in markers]
    if not matched:
        return []
    return [
        Finding(
            "privilege_escalation",
            "Privilege escalation attempt",
            "high",
            "The sample attempted an operation associated with elevating "
            "privileges.",
            _evidence(matched),
        )
    ]


_ANALYZERS = (
    _network,
    _files,
    _registry,
    _persistence,
    _services,
    _scheduled_tasks,
    _privilege_escalation,
)


def analyze(events: Sequence[_Event]) -> list[Finding]:
    findings: list[Finding] = []
    for analyzer in _ANALYZERS:
        findings.extend(analyzer(events))
    return findings
