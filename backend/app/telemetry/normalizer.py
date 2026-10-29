"""Turn raw executor observations into normalized telemetry events.

Normalization canonicalizes volatile fields — usernames, temp-file numbers,
random PIDs — so that two runs of the same sample can be compared meaningfully.
The original values are preserved in each event's `raw` payload.
"""

import re
from dataclasses import dataclass
from typing import Any

_USER_PATH = re.compile(r"(?i)(\\Users\\)[^\\]+")
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class NormalizedEvent:
    category: str
    action: str
    target: str
    raw: dict[str, Any]


def canonicalize(category: str, target: str) -> str:
    """Replace volatile parts of a target so runs are comparable."""
    value = target
    if category in ("file", "mutex", "registry", "persistence", "service", "scheduled_task"):
        value = _USER_PATH.sub(r"\1<user>", value)
        value = _DIGITS.sub("<n>", value)
    elif category in ("dns", "network", "http", "tls"):
        value = value.lower()
    return value


def normalize(observations: dict[str, Any]) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []

    for proc in observations.get("processes", []):
        action = str(proc.get("action", "start"))
        name = str(proc.get("name", ""))
        events.append(NormalizedEvent("process", action, name, proc))

    for net in observations.get("network", []):
        if net.get("type") == "dns":
            domain = canonicalize("dns", str(net.get("domain", "")))
            events.append(NormalizedEvent("dns", "query", domain, net))
        else:
            target = canonicalize("network", f"{net.get('dest', '')}:{net.get('port', '')}")
            events.append(NormalizedEvent("network", "connect", target, net))

    for path in observations.get("files_written", []):
        target = canonicalize("file", str(path))
        events.append(NormalizedEvent("file", "write", target, {"path": path}))

    for mutex in observations.get("mutexes_created", []):
        target = canonicalize("mutex", str(mutex))
        events.append(NormalizedEvent("mutex", "create", target, {"name": mutex}))

    for key in observations.get("registry_keys", []):
        target = canonicalize("registry", str(key))
        events.append(NormalizedEvent("registry", "set", target, {"key": key}))

    for artifact in observations.get("persistence", []):
        target = canonicalize("persistence", str(artifact))
        events.append(NormalizedEvent("persistence", "install", target, {"artifact": artifact}))

    for svc in observations.get("services", []):
        target = canonicalize("service", str(svc))
        events.append(NormalizedEvent("service", "create", target, {"service": svc}))

    for task in observations.get("scheduled_tasks", []):
        target = canonicalize("scheduled_task", str(task))
        events.append(NormalizedEvent("scheduled_task", "create", target, {"task": task}))

    return events
