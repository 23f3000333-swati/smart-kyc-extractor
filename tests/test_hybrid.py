"""Hybrid-mode merge logic, with the Groq call mocked (no key needed)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import llm_client  # noqa: E402
from src.schemas import LLMResponse  # noqa: E402


def _field(value, passed, read_conf=0.5, kind="ifsc"):
    return {"value": value, "raw": value, "kind": kind, "handwritten": True,
            "raw_readings": [], "corrections": [], "read_conf": read_conf,
            "two_pass": 0.3, "validator": {"passed": passed, "messages": []}}


def _doc():
    return {"file": "ECS.jpeg", "doc_type": "NACH_MANDATE", "fields": {
        "bank_name": _field("State Bank of India", True, kind="bank"),
        "ifsc_code": _field("BIN6227012", False),
        "bank_account_number": _field("31004258912", True, kind="account"),
        "amount_figures": _field("50000", True, kind="amount"),
        "frequency": _field("As & when presented", True, kind="choice"),
    }}


def test_merge_agree_boosts_and_disagree_flags(monkeypatch):
    monkeypatch.setattr(llm_client, "extract_fields", lambda t, img: {
        "bank_name": {"value": "State Bank of India", "confidence": 0.9},
        "ifsc_code": {"value": "SBIN0227112", "confidence": 0.9},
        "bank_account_number": {"value": "31004258912", "confidence": 0.9},
        "amount_figures": {"value": "50,000", "confidence": 0.9},
        "frequency": {"value": "Monthly", "confidence": 0.4},
    })
    doc = _doc()
    llm_client.merge_second_opinion(doc, np.zeros((10, 10), np.uint8))
    f = doc["fields"]
    assert f["bank_account_number"]["two_pass"] == 1.0          # agreement = boost
    assert f["amount_figures"]["two_pass"] == 1.0               # '50,000' normalises to 50000
    assert f["ifsc_code"]["value"] == "SBIN0227112"             # only the LLM value validates
    assert f["ifsc_code"]["llm_messages"]                       # ... but it is still flagged
    assert f["frequency"]["value"] == "As & when presented"     # offline kept (higher conf)
    assert "disagree" in f["frequency"]["llm_messages"][0]


def test_no_key_means_offline(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm_client.available() is False


def test_schema_coerces_bad_values():
    r = LLMResponse.model_validate({"fields": {"a": {"value": None, "confidence": 95}}})
    assert r.fields["a"].value == "" and r.fields["a"].confidence == 0.95
