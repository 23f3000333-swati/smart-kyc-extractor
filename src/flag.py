"""Flagging: decide which fields/documents need human review and write
output/flag_report.md."""
from __future__ import annotations

from pathlib import Path

import config
from src.confidence import field_confidence, threshold_for


def apply_flags(docs: list[dict]) -> None:
    """Compute final confidence and flags for every field, in place."""
    for doc in docs:
        doc_reasons = []
        if doc["doc_type"] == "OTHER":
            doc_reasons.append("out of scope, not extracted")
        elif doc["classification_confidence"] < config.PRINTED_THRESHOLD:
            doc_reasons.append(f"low classification confidence "
                               f"{doc['classification_confidence']:.2f}")
        for field in doc.get("fields", {}).values():
            field["confidence"] = field_confidence(field)
            reasons = []
            thr = threshold_for(field)
            field["threshold"] = thr
            if not field["value"]:
                reasons.append("missing / not found")
            elif field["confidence"] < thr:
                reasons.append(f"confidence {field['confidence']:.2f} < {thr:.2f}")
            v = field.get("validator", {})
            if v.get("passed") is False:
                reasons.append("validator failed: " + "; ".join(v.get("messages", [])))
            elif v.get("messages") and not all(m.startswith("matches") for m in v["messages"]):
                reasons.append("validity warning: " + "; ".join(v["messages"]))
            reasons += field.get("cross_messages", [])
            reasons += field.get("llm_messages", [])
            field["flagged"] = bool(reasons)
            field["flag_reasons"] = reasons
        doc["flagged"] = bool(doc_reasons) or any(
            f["flagged"] for f in doc.get("fields", {}).values())
        doc["flag_reasons"] = doc_reasons


RATIONALE = f"""\
## Thresholds

| Field group | Threshold |
|---|---|
| Printed fields (ID cards, printed labels) | **{config.PRINTED_THRESHOLD:.2f}** |
| High-value handwritten fields (IFSC, TIN/PAN, account number, dates, places) | **{config.HANDWRITTEN_THRESHOLD:.2f}** |

**Rationale.** The cost of an error is very asymmetric. A wrong IFSC or account
number means a failed NACH debit or money sent to the wrong account; a wrong
TIN/PAN breaks FATCA/CRS reporting; a wrong date or place on a declaration can
invalidate a signed consent. A human check of a flagged field costs a few
seconds. So the pipeline deliberately **over-flags**: handwritten high-value
fields need a higher score (0.85) because handwriting OCR is less reliable and
its engine confidence is less well calibrated than printed OCR. Confidence is
`0.4*read + 0.3*validator + 0.2*two-pass agreement + 0.1*cross-doc agreement`,
minus 0.05 for handwriting and 0.05 per character correction (max 0.15), so a
field can only clear 0.85 if the engines agree *and* the format validates.

Fields are also flagged, whatever their score, when a validator fails or warns
(e.g. checksum failures on sample IDs), when another document disagrees, or
(hybrid mode) when the offline and LLM readings disagree.
"""


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_flag_report(docs: list[dict], conflicts: list[dict], mode: str, path: Path) -> None:
    """Markdown report: thresholds + rationale, then a table of flagged items."""
    lines = [f"# Flag report (mode: `{mode}`)", "", RATIONALE, "## Flagged fields", "",
             "| file | doc_type | field | value | confidence | reason |",
             "|---|---|---|---|---|---|"]
    n_fields = n_flagged = 0
    for doc in docs:
        for name, f in doc.get("fields", {}).items():
            n_fields += 1
            if f["flagged"]:
                n_flagged += 1
                lines.append(f"| {_cell(doc['file'])} | {doc['doc_type']} | {name} | "
                             f"`{_cell(f['value'])}` | {f['confidence']:.2f} | "
                             f"{_cell('; '.join(f['flag_reasons']))} |")
    lines += ["", f"**{n_flagged} of {n_fields} fields flagged.**", "",
              "## Document-level flags", "", "| file | doc_type | reason |", "|---|---|---|"]
    for doc in docs:
        if doc["flag_reasons"]:
            lines.append(f"| {_cell(doc['file'])} | {doc['doc_type']} "
                         f"({doc.get('classification_detail', '')}) | "
                         f"{_cell('; '.join(doc['flag_reasons']))} |")
    lines += ["", "## Cross-document conflicts (flagged, never auto-fixed)", ""]
    if not conflicts:
        lines.append("None found.")
    for c in conflicts:
        lines.append(f"- **{c['entity']}**: " + " vs ".join(
            ", ".join(group) if isinstance(group, list) else group for group in c["values"]))
    path.write_text("\n".join(lines) + "\n")
