"""Rule-based knowledge-domain recognition (VECTOR spec section 3).

classify_knowledge_type(filename, source) -> one of
project|engineering|standard|contract|method|site|document|lesson, or None.

- Priority-ordered: distinctive codes first (standards), generic last.
- Matches against filename + source path (folder names like lessons/, methods/
  also classify, so watch-folder trees map to domains automatically).
- Returns None when nothing matches -> caller keeps DOCUMENT default bucket.
- Deterministic, dependency-free; tuned on real LongThink filenames
  (datasheets, drawings, TRD/TBE, ITP, procedures, transmittals, lectures).
"""

from __future__ import annotations

import re

# (knowledge_type, [regex patterns]) — first match wins.
RULES: list[tuple[str, list[str]]] = [
    ("standard", [
        r"tcvn", r"qcvn", r"\biso\b", r"\biec\b", r"astm", r"asme", r"nfpa",
        r"legislation", r"code[_\s-]?digest", r"guidance[_\s-]?notes?",
        r"model[_\s-]?code", r"\bstandard(s)?\b",
    ]),
    ("method", [
        r"(?<![A-Za-z])itp(?![A-Za-z])", r"inspection[_\s-]?and[_\s-]?test[_\s-]?plan",
        r"procedure", r"fat[_\s-]?procedure", r"\biom\b",
        r"installation[_\s-]?operation", r"maintenance[_\s-]?manual",
        r"method[_\s-]?statement", r"\bsop\b", r"work[_\s-]?instruction",
    ]),
    ("site", [
        r"progress[_\s-]?report", r"shop[_\s-]?inspection",
        r"(test|inspection)[_\s-]?reports?", r"fat[_\s-]?report",
        r"daily[_\s-]?report", r"punch[_\s-]?list", r"\bncr\b", r"\brfi\b",
        r"handover", r"site[_\s-]?report",
    ]),
    ("lesson", [
        r"lesson", r"learned", r"best[_\s-]?practice", r"retrospective",
        r"lecture", r"\blec\d", r"training", r"tutorial", r"course",
        r"question[_\s-]?bank", r"\bexam\b", r"đề[_\s-]?thi", r"de[_\s-]?thi",
        r"\bintro\b", r"basics?", r"fundamentals?", r"reference",
        r"measurement", r"handbook", r"week\d{1,2}",
    ]),
    ("contract", [
        r"contract", r"\bboq\b", r"tender", r"\bbid\b", r"claim",
        r"variation", r"scope[_\s-]?of[_\s-]?work", r"\bsow\b",
    ]),
    ("engineering", [
        r"datasheet", r"data[_\s-]?sheet", r"drawing", r"diagram",
        r"hook[_\s-]?up", r"schematic", r"calculation", r"\btrd\b",
        r"\btbe\b", r"\bdas\b", r"specification", r"\bspc\b",
        r"technical", r"\bfat\b", r"\breport\b", r"\bdraft\b",
        r"design", r"layout", r"arrangement", r"\bpid\b", r"\bpfd\b",
        r"\bbim\b", r"instrument",
    ]),
    ("document", [
        r"transmittal", r"comment[_\s-]?sheet", r"packing",
        r"vendor[_\s-]?list", r"certificate", r"correspondence",
        r"memo", r"\bletter\b", r"email", r"đơn", r"mẫu[_\s-]?đơn",
        r"tố[_\s-]?cáo", r"kiến[_\s-]?nghị",
        r"don[_\s-]?kien", r"mau[_\s-]?don", r"to[_\s-]?cao",
    ]),
    ("project", [
        r"charter", r"\bwbs\b", r"project[_\s-]?plan", r"master[_\s-]?plan",
        r"project[_\s-]?profile",
    ]),
]

_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (kt, [re.compile(p, re.IGNORECASE) for p in patterns]) for kt, patterns in RULES
]

# Folder-name shortcuts: knowledge/<domain>/... maps directly.
FOLDER_DOMAINS = {
    "projects": "project", "project": "project",
    "engineering": "engineering",
    "standards": "standard", "standard": "standard",
    "contracts": "contract", "contract": "contract",
    "methods": "method", "method": "method",
    "site": "site",
    "documents": "document", "document": "document",
    "lessons": "lesson", "lesson": "lesson",
}


def classify_knowledge_type(filename: str | None, source: str | None = None) -> str | None:
    """Return knowledge_type or None (caller keeps default bucket)."""
    text = " ".join(t for t in (filename or "", source or "") if t)
    if not text.strip():
        return None
    # Folder shortcut first: an explicit domain folder always wins.
    segments = re.split(r"[/\\:]+", text.lower())
    for seg in segments:
        if seg in FOLDER_DOMAINS:
            return FOLDER_DOMAINS[seg]
    for kt, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            return kt
    return None
