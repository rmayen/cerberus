"""Differential comparison of two runs.

Given the normalized telemetry of a baseline run and a variant run (identical
except for one changed condition), this reports which events appeared or
disappeared and how strong the dependency looks. It reports *observed*
dependencies with a confidence level; it never asserts certainty.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class _Event(Protocol):
    @property
    def category(self) -> str: ...
    @property
    def action(self) -> str: ...
    @property
    def target(self) -> str: ...


@dataclass(frozen=True)
class DiffResult:
    confidence: str  # high | medium | low
    summary: str
    added: list[dict[str, str]]
    removed: list[dict[str, str]]


def _key(event: _Event) -> tuple[str, str, str]:
    return (event.category, event.action, event.target)


def _as_dicts(keys: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [{"category": c, "action": a, "target": t} for (c, a, t) in keys]


def compare(
    axis: str,
    baseline_value: Any,
    variant_value: Any,
    baseline_events: Sequence[_Event],
    variant_events: Sequence[_Event],
) -> DiffResult | None:
    """Compare a variant run against the baseline. Returns None if identical."""
    base = {_key(e) for e in baseline_events}
    var = {_key(e) for e in variant_events}
    added = sorted(var - base)
    removed = sorted(base - var)
    if not added and not removed:
        return None

    base_categories = {c for (c, _, _) in base}
    var_categories = {c for (c, _, _) in var}
    category_shift = (base_categories - var_categories) | (var_categories - base_categories)
    changed = len(added) + len(removed)

    # An entire category appearing or disappearing is a strong dependency;
    # otherwise scale confidence with the number of differing events.
    if category_shift:
        confidence = "high"
    elif changed >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    summary = (
        f"Observed behavioral dependency: changing {axis!r} from {baseline_value!r} to "
        f"{variant_value!r} produced {len(added)} new and {len(removed)} absent event(s)."
    )
    return DiffResult(confidence, summary, _as_dicts(added), _as_dicts(removed))
