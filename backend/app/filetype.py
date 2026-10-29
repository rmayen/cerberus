"""Lightweight file-type detection from magic bytes.

Malware samples can be arbitrary binaries, so this classifies inputs into broad
categories for the analyst rather than trying to identify an exact format. An
empty input is reported as "empty" so it can be rejected upstream.
"""


def detect(data: bytes) -> str:
    if not data:
        return "empty"

    if data[:2] == b"MZ":
        return "pe"
    if data[:4] == b"\x7fELF":
        return "elf"
    macho_magics = (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xce\xfa\xed\xfe",
    )
    if data[:4] in macho_magics:
        return "macho"
    if data[:4] == b"\xca\xfe\xba\xbe":
        return "java_or_macho_universal"
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:6] in (b"Rar!\x1a\x07",):
        return "rar"
    if data[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"
    if data[:2] in (b"#!",):
        return "script"

    # Heuristic: mostly-printable input is treated as text.
    sample = data[:1024]
    printable = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126)
    if printable / len(sample) > 0.95:
        return "text"

    return "binary"
