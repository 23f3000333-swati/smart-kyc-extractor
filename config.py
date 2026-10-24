"""Central configuration: paths, thresholds, confidence weights, classification
anchors and per-document field specifications.

Everything that is "tuning" lives here so the pipeline code stays generic.
No ground-truth values appear in this file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "data" / "input"
GROUND_TRUTH = ROOT / "data" / "ground_truth.json"  # used ONLY by evaluate.py
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = OUTPUT_DIR / ".cache"  # OCR results cached here to speed up re-runs

PDF_DPI = 200   # PyMuPDF render resolution for PDF pages
MAX_SIDE = 2000  # pages are downscaled to this longest side before OCR

# --------------------------------------------------------------------------- #
# Flagging thresholds (see flag_report.md for the rationale)
# --------------------------------------------------------------------------- #
PRINTED_THRESHOLD = 0.80
HANDWRITTEN_THRESHOLD = 0.85  # applied to the high-value handwritten fields
HIGH_VALUE_KINDS = {"ifsc", "pan", "account", "date", "place"}

# --------------------------------------------------------------------------- #
# Confidence formula
#   conf = 0.4*read + 0.3*validator + 0.2*two_pass + 0.1*cross_doc
# --------------------------------------------------------------------------- #
W_READ, W_VALID, W_TWO_PASS, W_CROSS = 0.4, 0.3, 0.2, 0.1
CROSS_DOC_NO_SOURCE = 0.5     # no other document carries this entity
HANDWRITTEN_PENALTY = 0.05
CORRECTION_PENALTY = 0.05     # per corrected character ...
MAX_CORRECTION_PENALTY = 0.15  # ... capped
NO_VALIDATOR_SCORE = 0.5      # validator term when a field has no rule

# --------------------------------------------------------------------------- #
# OCR / LLM settings
# --------------------------------------------------------------------------- #
EASYOCR_LANGS = ["en"]
# trocr-base-handwritten (1.3 GB) is more accurate; trocr-small-handwritten
# (250 MB) is the default here because the dev machine had <1 GB free disk.
# Override with: TROCR_MODEL=microsoft/trocr-base-handwritten python run.py
TROCR_MODEL = os.getenv("TROCR_MODEL", "microsoft/trocr-small-handwritten")
LLM_MAX_SIDE = 1600
LLM_JPEG_QUALITY = 85
LLM_MAX_RETRIES = 5
LLM_CALL_DELAY_S = 2.0
DEFAULT_GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# --------------------------------------------------------------------------- #
# Classification anchors: (phrase, weight). Matched fuzzily against the
# full-page printed OCR text. "OTHER_*" types are recognised but not extracted.
# --------------------------------------------------------------------------- #
CLASS_ANCHORS: dict[str, list[tuple[str, float]]] = {
    "AADHAAR": [("aadhaar", 2), ("unique identification authority", 3),
                ("uidai", 2), ("enrollment no", 1), ("mera aadhaar", 1)],
    "PAN": [("permanent account number", 3), ("income tax department", 2)],
    "DRIVING_LICENCE": [("driving licence", 3), ("licencing authority", 2),
                        ("classes of vehicles", 2), ("valid till", 1)],
    "PASSPORT": [("passport", 2), ("republic of india", 1), ("country code", 1),
                 ("p<ind", 2), ("date of expiry", 1)],
    "NACH_MANDATE": [("nach mandate", 3), ("mandate instruction", 3), ("umrn", 2),
                     ("ifsc", 1), ("micr", 1), ("sponsor bank code", 2)],
    "FATCA_ANNEXURE": [("annexure form", 3), ("285ba", 3), ("tax residency", 2),
                       ("tax identification number", 2)],
    "BENEFIT_ILLUSTRATION": [("benefit illustration", 4)],
    "MORAL_HAZARD": [("moral hazard questionnaire", 4), ("moral hazard", 2)],
    "MULTIPLE_POLICIES_CONSENT": [("multiple policies", 3), ("customer consent form", 2),
                                  ("reason for buying multiple policies", 2)],
    "SUITABILITY_PROFILER": [("suitability profiler", 4)],
    # Out-of-scope forms (recognised so they are not mistaken for in-scope ones)
    "OTHER_ASSIGNMENT": [("assignment request form", 4), ("details of assignee", 2),
                         ("assignor", 2)],
    "OTHER_PROPOSAL": [("type of plan", 3), ("premium paying term", 3),
                       ("sum assured", 1), ("name of insurance plan", 3)],
}
MIN_CLASS_SCORE = 2.0  # below this the page is OTHER (unknown)


# --------------------------------------------------------------------------- #
# Field specifications
# --------------------------------------------------------------------------- #
@dataclass
class FieldSpec:
    """How to find and validate one field.

    name        output key
    kind        drives normalisation + validation (see src/validate.py)
    handwritten True if the value is handwritten on the form
    labels      printed anchor phrases; the value is searched near them
    direction   "right" (same row), "below" (next lines) or "right_or_below"
    width       search-window width as a fraction of page width
    height      search-window height in multiples of the label height
    stop        printed phrases that end the window on the right
    method      "anchor" (default), "regex", "mrz", "checkbox"
    options     checkbox option labels (method="checkbox")
    x_from      optional window start as a fraction of page width (overrides
                "just right of the label", e.g. the amount box at the far right)
    aux         auxiliary field: used as validator context, not a target
    """
    name: str
    kind: str
    handwritten: bool = False
    labels: list[str] = field(default_factory=list)
    direction: str = "right"
    width: float = 0.45
    height: float = 2.2
    stop: list[str] = field(default_factory=list)
    method: str = "anchor"
    options: list[str] = field(default_factory=list)
    x_from: float | None = None
    aux: bool = False
    left_of: list[str] = field(default_factory=list)  # value is LEFT of these labels


F = FieldSpec  # short alias for the table below

FIELDS: dict[str, list[FieldSpec]] = {
    "AADHAAR": [
        F("aadhaar_number", "aadhaar", method="regex"),
        F("full_name", "name", labels=["Name"], direction="right_or_below"),
        F("date_of_birth", "date", labels=["Date of Birth", "DOB"], direction="right_or_below"),
        F("address", "address", labels=["Address"], direction="below", height=6.0, width=0.4),
    ],
    "PAN": [
        F("pan_number", "pan", method="regex"),
        F("full_name", "name", labels=["Name"], direction="below"),
        F("fathers_name", "father", labels=["Father's Name", "Fathers Name"], direction="below"),
        F("date_of_birth", "date", labels=["Date of Birth"], direction="below"),
    ],
    "DRIVING_LICENCE": [
        F("dl_number", "dl", method="regex"),
        F("name", "name", labels=["Name"], direction="right", width=0.35),
        F("date_of_issue", "date", labels=["Date of Issue", "DOI"], direction="right_or_below", width=0.25),
        F("valid_till", "date", labels=["Valid Till"], direction="right", width=0.25),
        # auxiliary: only used for the DL-state consistency check
        F("address", "address", labels=["Address"], direction="right_down", height=5.0,
          width=0.3, aux=True),
        F("licencing_authority", "text", labels=["Licencing Authority"], direction="below",
          height=2.5, width=0.25, aux=True),
    ],
    "PASSPORT": [
        F("passport_number", "passport", method="regex"),
        F("date_of_birth", "date", labels=["Date of Birth"], direction="below", width=0.25),
        F("date_of_expiry", "date", labels=["Date of Expiry"], direction="below", width=0.2),
        F("mrz_line_2", "mrz", method="mrz"),
    ],
    "NACH_MANDATE": [
        F("bank_account_number", "account", True, ["Bank a/c number", "Bank alc number"],
          width=0.55, height=1.8),
        F("ifsc_code", "ifsc", True, ["IFSC"], width=0.32, height=1.8, stop=["or MICR", "MICR"]),
        F("bank_name", "bank", True, ["with bank"], width=0.33, height=1.8, stop=["IFSC"],
          left_of=["IFSC"]),
        F("amount_words", "words", True, ["an amount of Rupees"], width=0.5, height=1.8,
          aux=True),
        F("amount_figures", "amount", True, ["an amount of Rupees"], width=0.22, height=1.8,
          x_from=0.74),
        F("frequency", "choice", True, ["FREQUENCY"], method="checkbox", stop=["DEBIT TYPE"],
          options=["Monthly", "Qly", "H. Yrly", "Yrly", "As & when presented"]),
    ],
    "FATCA_ANNEXURE": [
        F("policy_number", "appno", True, ["Policy No"], width=0.35, height=2.0),
        F("tin_pan", "pan", True, ["Tax Identification Number"], direction="below",
          width=0.25, height=6.0),
        F("fathers_name", "father", True, ["Father's Name", "Fathers Name"], width=0.3,
          stop=["Spouse"]),
        F("place_of_birth", "place", True, ["Place of birth"], width=0.2),
        F("nationality", "nationality", True, ["Nationality"], width=0.25, stop=["Occupation"]),
    ],
    "BENEFIT_ILLUSTRATION": [
        F("application_number", "appno", True, ["Application/ Proposal Form Number",
                                                "Proposal Form Number"], width=0.5),
        F("policyholder_name", "name", True, ["Name of Policyhoder", "Name of Policyholder"],
          width=0.4),
        F("date", "date", True, ["Date"], width=0.18),
        F("place", "place", True, ["Place"], width=0.18),
    ],
    "MORAL_HAZARD": [
        F("application_number", "appno", True, ["Application No"], width=0.5),
        F("name_of_life_assured", "name", True, ["Name of the Life to be Assured"], width=0.45),
        F("nominee_relationship", "relation", True, ["Please confirm exact relationship"],
          width=0.5, height=1.6),
        F("date", "date", True, ["Date"], width=0.25),
        F("place", "place", True, ["Place"], width=0.25),
    ],
    "MULTIPLE_POLICIES_CONSENT": [
        F("proposer_name", "name", True, ["Proposer / Life Assured Name", "Life Assured Name"],
          width=0.4),
        F("reason_for_multiple_policies", "choice", True, ["Reason for buying"],
          method="checkbox",
          options=["Financial Planning", "Different investment", "Separate policy", "Others"]),
        F("date", "date", True, ["Date"], width=0.25),
        F("place", "place", True, ["Place"], width=0.25),
    ],
    "SUITABILITY_PROFILER": [
        F("application_number", "appno", True, ["Application/ Proposal Form Number",
                                                "Proposal Form Number"], width=0.5),
        F("name_of_life_assured", "name", True, ["Name of Life Assured"], width=0.4),
        F("name_of_agent_sp", "name", True, ["Name of Agent/SP", "Name of Agent"], width=0.4),
        F("date", "date", True, ["Date"], width=0.15),
        F("place", "place", True, ["Place"], width=0.15),
    ],
}

# Cross-document entities: which (doc_type, field) pairs describe the same fact.
CROSS_ENTITIES: dict[str, list[tuple[str, str]]] = {
    "application_number": [("FATCA_ANNEXURE", "policy_number"),
                           ("BENEFIT_ILLUSTRATION", "application_number"),
                           ("MORAL_HAZARD", "application_number"),
                           ("SUITABILITY_PROFILER", "application_number")],
    "applicant_name": [("AADHAAR", "full_name"), ("PAN", "full_name"),
                       ("DRIVING_LICENCE", "name"),
                       ("BENEFIT_ILLUSTRATION", "policyholder_name"),
                       ("MORAL_HAZARD", "name_of_life_assured"),
                       ("MULTIPLE_POLICIES_CONSENT", "proposer_name"),
                       ("SUITABILITY_PROFILER", "name_of_life_assured")],
    "date_of_birth": [("AADHAAR", "date_of_birth"), ("PAN", "date_of_birth"),
                      ("PASSPORT", "date_of_birth")],
    "fathers_name": [("PAN", "fathers_name"), ("FATCA_ANNEXURE", "fathers_name")],
    "pan": [("PAN", "pan_number"), ("FATCA_ANNEXURE", "tin_pan")],
    "signing_place": [("BENEFIT_ILLUSTRATION", "place"), ("MORAL_HAZARD", "place"),
                      ("MULTIPLE_POLICIES_CONSENT", "place"),
                      ("SUITABILITY_PROFILER", "place")],
    "signing_date": [("BENEFIT_ILLUSTRATION", "date"), ("MORAL_HAZARD", "date"),
                     ("MULTIPLE_POLICIES_CONSENT", "date"),
                     ("SUITABILITY_PROFILER", "date")],
}
