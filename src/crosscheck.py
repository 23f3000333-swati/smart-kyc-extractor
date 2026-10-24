"""Cross-document consistency checks.

The same applicant appears on every document, so facts such as the
application number, name, DOB, father's name and PAN should agree. Agreement
raises confidence; disagreement is FLAGGED and never auto-fixed.
"""
from __future__ import annotations

import re

import config
from src.validate import similarity

# DL / vehicle registration state codes -> state names (used for the DL rule).
STATE_CODES = {
    "AP": "ANDHRA PRADESH", "AR": "ARUNACHAL PRADESH", "AS": "ASSAM", "BR": "BIHAR",
    "CG": "CHHATTISGARH", "DL": "DELHI", "GA": "GOA", "GJ": "GUJARAT", "HR": "HARYANA",
    "HP": "HIMACHAL PRADESH", "JH": "JHARKHAND", "KA": "KARNATAKA", "KL": "KERALA",
    "MP": "MADHYA PRADESH", "MH": "MAHARASHTRA", "OD": "ODISHA", "PB": "PUNJAB",
    "RJ": "RAJASTHAN", "TN": "TAMIL NADU", "TS": "TELANGANA", "UP": "UTTAR PRADESH",
    "UK": "UTTARAKHAND", "WB": "WEST BENGAL", "JK": "JAMMU AND KASHMIR",
}
SAME_THRESHOLD = 0.9


def comparable(entity: str, value: str) -> str:
    """Normalise a value for comparison across documents."""
    v = (value or "").upper()
    if entity in ("applicant_name", "fathers_name"):
        v = re.sub(r"\b(MR|MRS|MS|MISS|SHRI|SMT)\b\.?", "", v)
    return re.sub(r"[^A-Z0-9]", "", v)


def cross_check(docs: list[dict]) -> list[dict]:
    """Set field["cross_doc"] (0..1) on every entity field; return conflicts.

    cross_doc = share of OTHER documents whose value agrees; 0.5 when no
    other document carries the entity.
    """
    by_type = {d["doc_type"]: d for d in docs if d["doc_type"] in config.FIELDS}
    for d in docs:  # reset, so the check can be re-run after hybrid merging
        for field in d.get("fields", {}).values():
            field.pop("cross_doc", None)
            field.pop("cross_messages", None)
    conflicts = []
    for entity, members in config.CROSS_ENTITIES.items():
        # Only values that pass their own validator take part: an unreadable
        # date ("Dommryry") is an OCR failure, not evidence of a conflict.
        present = [(t, f, by_type[t]["fields"][f]) for t, f in members
                   if t in by_type and f in by_type[t]["fields"]
                   and by_type[t]["fields"][f]["value"]
                   and by_type[t]["fields"][f]["validator"].get("passed") is not False]
        for t, f, field in present:
            others = [(t2, f2, x) for t2, f2, x in present if t2 != t]
            if not others:
                field["cross_doc"] = config.CROSS_DOC_NO_SOURCE
                continue
            mine = comparable(entity, field["value"])
            agree = [similarity(mine, comparable(entity, x["value"])) >= SAME_THRESHOLD
                     for _, _, x in others]
            field["cross_doc"] = round(sum(agree) / len(agree), 3)
            # Flag the odd one out: a field that disagrees with at least half
            # of the other sources (with 2 sources both sides are flagged).
            if field["cross_doc"] <= 0.5:
                for (t2, f2, x), ok in zip(others, agree):
                    if not ok:
                        msg = f"cross-doc: {entity} differs from {t2}.{f2} = '{x['value']}'"
                        field.setdefault("cross_messages", []).append(msg)
        # One conflict entry per entity with all distinct values.
        distinct = {}
        for t, f, field in present:
            distinct.setdefault(comparable(entity, field["value"]), []).append(
                f"{t}.{f}='{field['value']}'")
        if len(distinct) > 1:
            conflicts.append({"entity": entity, "values": list(distinct.values())})
    # Fields of an entity that no other doc carries still need the neutral score.
    for d in docs:
        for field in d.get("fields", {}).values():
            field.setdefault("cross_doc", config.CROSS_DOC_NO_SOURCE)
    conflicts += dl_state_check(by_type.get("DRIVING_LICENCE"))
    return conflicts


def dl_state_check(dl: dict | None) -> list[dict]:
    """A DL's state code should match the state in its address / authority."""
    if not dl:
        return []
    number = dl["fields"].get("dl_number", {}).get("value", "")
    state = STATE_CODES.get(number[:2])
    text = " ".join(v.get("value", "") for v in dl.get("auxiliary", {}).values()).upper()
    mentioned = [s for s in STATE_CODES.values() if s in text]
    if state and mentioned and state not in mentioned:
        msg = (f"DL number prefix {number[:2]} = {state}, but the licence address/"
               f"authority mentions {', '.join(mentioned)}")
        dl["fields"]["dl_number"].setdefault("cross_messages", []).append("cross-doc: " + msg)
        return [{"entity": "dl_state", "values": [msg]}]
    return []
