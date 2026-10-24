"""Per-field confidence.

    conf = 0.4*read_conf + 0.3*validator + 0.2*two_pass + 0.1*cross_doc
           - 0.05 if handwritten
           - 0.05 per corrected character (max 0.15)
    missing value -> 0

read_conf  OCR engine confidence of the chosen reading (TrOCR: geometric mean
           token probability; EasyOCR: its box score; checkbox: ink margin)
validator  1 pass / 0 fail / 0.5 no rule for this kind
two_pass   how much the other readings (other engine / other image version /
           LLM in hybrid mode) agree with the chosen value
cross_doc  agreement with the same fact on other documents (0.5 if none)
"""
from __future__ import annotations

import config


def field_confidence(field: dict) -> float:
    """Compute and return the confidence for one field result."""
    if not field.get("value"):
        return 0.0
    passed = field.get("validator", {}).get("passed")
    valid = 1.0 if passed is True else 0.0 if passed is False else config.NO_VALIDATOR_SCORE
    conf = (config.W_READ * field.get("read_conf", 0.0)
            + config.W_VALID * valid
            + config.W_TWO_PASS * field.get("two_pass", 0.0)
            + config.W_CROSS * field.get("cross_doc", config.CROSS_DOC_NO_SOURCE))
    if field.get("handwritten"):
        conf -= config.HANDWRITTEN_PENALTY
    conf -= min(config.MAX_CORRECTION_PENALTY, config.CORRECTION_PENALTY * count_corrections(field))
    return round(max(0.0, min(1.0, conf)), 3)


def count_corrections(field: dict) -> int:
    """Corrections that changed what OCR read. Expanding a 2-digit year is a
    formatting rule, not a misread, so it does not cost confidence."""
    return sum(1 for c in field.get("corrections", []) if not c.startswith("2-digit year"))


def threshold_for(field: dict) -> float:
    """0.85 for high-value handwritten fields, 0.80 otherwise."""
    if field.get("handwritten") and field.get("kind") in config.HIGH_VALUE_KINDS:
        return config.HANDWRITTEN_THRESHOLD
    return config.PRINTED_THRESHOLD
