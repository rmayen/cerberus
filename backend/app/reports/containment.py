"""Generate containment recommendations from a run's findings and indicators.

Recommendations are framed as evidence-based suggestions ("observed evidence
suggests ..."), never as guaranteed remediations.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Recommendation:
    action: str
    rationale: str


class _Finding(Protocol):
    @property
    def category(self) -> str: ...


class _Ioc(Protocol):
    @property
    def value(self) -> str: ...

    @property
    def type(self) -> object: ...  # StrEnum; compared by str(...)


def recommend(findings: Sequence[_Finding], iocs: Sequence[_Ioc]) -> list[Recommendation]:
    recs: list[Recommendation] = [
        Recommendation(
            "Isolate the affected host from the network",
            "Observed evidence suggests active malicious behavior; isolation limits "
            "further impact while analysis continues.",
        )
    ]

    network = [i for i in iocs if str(i.type) in ("domain", "ip", "url")]
    if network:
        destinations = ", ".join(i.value for i in network[:5])
        recs.append(
            Recommendation(
                f"Block outbound traffic to the observed destinations ({destinations})",
                "The sample attempted outbound communication to these indicators, "
                "consistent with command-and-control.",
            )
        )
        recs.append(
            Recommendation(
                "Create detection content (for example a Sigma rule) for these destinations",
                "The observed indicators can be monitored across the network to detect "
                "related activity.",
            )
        )

    if any(f.category == "persistence" for f in findings):
        recs.append(
            Recommendation(
                "Remove the observed persistence mechanism (registry autostart entry)",
                "A persistence artifact was observed that could let the sample survive "
                "reboots.",
            )
        )

    recs.append(
        Recommendation(
            "Monitor the extracted indicators of compromise across the environment",
            "Watching for these indicators helps surface related infections.",
        )
    )
    return recs
