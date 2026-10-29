"""Extract indicators of compromise (IOCs) from a run's telemetry.

IOCs are pulled from each event's original (raw) values, not the canonicalized
target, so the real domains, paths, and keys are preserved.
"""

import ipaddress
import re
from collections.abc import Sequence
from typing import Any, Protocol

_DOMAIN = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.IGNORECASE)


class _Event(Protocol):
    @property
    def category(self) -> str: ...
    @property
    def raw(self) -> dict[str, Any]: ...


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def extract(sample_sha256: str, events: Sequence[_Event]) -> list[tuple[str, str]]:
    """Return sorted, de-duplicated (type, value) IOC pairs."""
    iocs: set[tuple[str, str]] = {("file_hash", sample_sha256)}

    for event in events:
        raw = event.raw
        category = event.category
        if category == "dns" and raw.get("domain"):
            iocs.add(("domain", str(raw["domain"])))
        elif category == "network":
            dest = str(raw.get("dest", ""))
            if _is_ip(dest):
                iocs.add(("ip", dest))
            elif _DOMAIN.match(dest):
                iocs.add(("domain", dest))
        elif category == "http" and raw.get("url"):
            iocs.add(("url", str(raw["url"])))
        elif category == "registry" and raw.get("key"):
            iocs.add(("registry_key", str(raw["key"])))
        elif category == "mutex" and raw.get("name"):
            iocs.add(("mutex", str(raw["name"])))
        elif category == "service" and raw.get("service"):
            iocs.add(("service", str(raw["service"])))
        elif category == "file" and raw.get("path"):
            iocs.add(("file_path", str(raw["path"])))

    return sorted(iocs)
