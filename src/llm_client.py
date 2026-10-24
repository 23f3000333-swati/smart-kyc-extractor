"""Optional vision-LLM second opinion via the free Groq API.

Never required: if GROQ_API_KEY is missing or `groq` is not installed,
available() is False and the pipeline stays fully offline.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time

import cv2
import numpy as np

import config
from src.schemas import LLMResponse
from src.validate import normalize, similarity, validate

log = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
except ImportError:  # python-dotenv is optional
    pass

# Short descriptions that tell the model exactly what each key means.
FIELD_HINTS = {
    "aadhaar_number": "12-digit Aadhaar number", "full_name": "full name as printed",
    "date_of_birth": "date of birth DD/MM/YYYY", "address": "full address as printed",
    "pan_number": "10-char PAN", "fathers_name": "father's name as written",
    "dl_number": "driving licence number", "name": "holder name as printed",
    "date_of_issue": "date of issue DD/MM/YYYY", "valid_till": "valid till DD/MM/YYYY",
    "passport_number": "passport number", "date_of_expiry": "date of expiry DD/MM/YYYY",
    "mrz_line_2": "second MRZ line, exactly 44 chars including every '<'",
    "bank_account_number": "bank account number (digits written in the boxes)",
    "ifsc_code": "11-char IFSC code written in the boxes", "bank_name": "bank name",
    "amount_figures": "amount in figures (digits only)",
    "frequency": "the ticked frequency option (Monthly/Qly/H. Yrly/Yrly/As & when presented)",
    "policy_number": "policy number", "tin_pan": "TIN / PAN written in the residency table",
    "place_of_birth": "place of birth", "nationality": "nationality",
    "application_number": "application / proposal form number",
    "policyholder_name": "name of policyholder", "date": "the filled date DD/MM/YYYY",
    "place": "the filled place", "name_of_life_assured": "name of the life assured",
    "nominee_relationship": "exact relationship of the nominee",
    "proposer_name": "proposer / life assured name",
    "reason_for_multiple_policies": "the ticked reason option text",
    "name_of_agent_sp": "name of agent / SP",
}

RULES = """Rules:
- Return STRICT JSON only, no prose.
- Copy exactly what is written; do not guess or "correct" values. Read
  handwritten codes box by box, character by character.
- Struck-through options are NOT selected; a ticked box is selected.
- Dates as DD/MM/YYYY. Empty string if a field is absent or illegible.
- confidence: your probability (0-1) that the value is exactly right.
- is_handwritten: true if the value is handwritten."""


def available() -> bool:
    """True when the Groq client can be used."""
    if not os.getenv("GROQ_API_KEY"):
        return False
    try:
        import groq  # noqa: F401
    except ImportError:
        return False
    return True


def model_name() -> str:
    return os.getenv("GROQ_VISION_MODEL", "").split("#")[0].strip() or config.DEFAULT_GROQ_MODEL


def image_data_url(gray_or_bgr: np.ndarray) -> str:
    """Resize (longest side ~1600px), JPEG-compress, base64 data URL."""
    img = gray_or_bgr
    h, w = img.shape[:2]
    scale = config.LLM_MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, config.LLM_JPEG_QUALITY])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _call(prompt: str, image: np.ndarray) -> LLMResponse | None:
    """One chat completion with backoff on 429 and one retry on bad JSON."""
    import groq
    client = groq.Groq()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data_url(image)}}]}]
    bad_json_retry = True
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        try:
            time.sleep(config.LLM_CALL_DELAY_S)
            resp = client.chat.completions.create(
                model=model_name(), messages=messages, temperature=0,
                response_format={"type": "json_object"}, max_tokens=1500)
            content = resp.choices[0].message.content or ""
            return LLMResponse.model_validate(json.loads(content))
        except groq.RateLimitError:
            wait = 2 ** (attempt + 1)
            log.warning("Groq 429, retrying in %ss", wait)
            time.sleep(wait)
        except (json.JSONDecodeError, ValueError) as exc:
            if not bad_json_retry:
                log.error("LLM returned invalid JSON twice: %s", exc)
                return None
            bad_json_retry = False
            log.warning("LLM JSON invalid (%s), retrying once", exc)
        except groq.APIError as exc:
            log.error("Groq API error: %s", exc)
            return None
    return None


def _field_block(doc_type: str) -> str:
    keys = [s.name for s in config.FIELDS[doc_type] if not s.aux]
    return "\n".join(f'  "{k}": {FIELD_HINTS.get(k, k)}' for k in keys)


def extract_fields(doc_type: str, image: np.ndarray) -> dict:
    """Ask the LLM for the fields of a known document type."""
    prompt = (f"You are reading an Indian KYC / insurance document of type {doc_type}.\n"
              f"Extract these fields:\n{_field_block(doc_type)}\n\n{RULES}\n"
              'Answer as {"fields": {"<key>": {"value": "...", "confidence": 0.0, '
              '"is_handwritten": false}}}')
    resp = _call(prompt, image)
    return {k: v.model_dump() for k, v in resp.fields.items()} if resp else {}


def classify_and_extract(image: np.ndarray) -> dict:
    """mode=llm: classify the page and extract that type's fields."""
    types = "\n".join(f"- {t}:\n{_field_block(t)}" for t in config.FIELDS)
    prompt = (f"Classify this document as one of the types below, or OTHER, and extract "
              f"the fields listed for that type.\n{types}\n\n{RULES}\n"
              'Answer as {"doc_type": "...", "doc_type_confidence": 0.0, "fields": '
              '{"<key>": {"value": "...", "confidence": 0.0, "is_handwritten": false}}}')
    resp = _call(prompt, image)
    if not resp:
        return {"doc_type": "OTHER", "doc_type_confidence": 0.0, "fields": {}}
    return {"doc_type": resp.doc_type.upper(), "doc_type_confidence": resp.doc_type_confidence,
            "fields": {k: v.model_dump() for k, v in resp.fields.items()}}


def _llm_reading(spec, llm: dict) -> dict:
    return {"engine": "groq:" + model_name(), "version": "original",
            "text": llm.get("value", ""), "conf": round(llm.get("confidence", 0.0), 3)}


def to_field_results(doc_type: str, llm_fields: dict) -> dict:
    """mode=llm: build field results from LLM answers (no second reading,
    so two-pass agreement is neutral 0.5)."""
    results, context = {}, {}
    for spec in config.FIELDS[doc_type]:
        if spec.aux:
            continue
        llm = llm_fields.get(spec.name, {})
        value, corr = normalize(spec.kind, llm.get("value", ""))
        ctx = dict(context, options=spec.options)
        passed, msgs = validate(spec.kind, value, ctx) if value else (False, ["empty"])
        results[spec.name] = {
            "value": value, "raw": llm.get("value", ""), "kind": spec.kind,
            "handwritten": spec.handwritten, "raw_readings": [_llm_reading(spec, llm)],
            "corrections": corr, "read_conf": llm.get("confidence", 0.0), "two_pass": 0.5,
            "validator": {"passed": passed, "messages": msgs}}
        context[spec.name] = value
    return results


def merge_second_opinion(doc: dict, image: np.ndarray) -> None:
    """hybrid: compare each offline field with the LLM reading.

    agree    -> two_pass agreement = 1.0 (confidence boost)
    disagree -> flagged; keep the value that passes its validator (if only
                one does), otherwise the one with the higher read confidence.
    """
    log.info("hybrid: asking %s about %s", model_name(), doc["file"])
    llm_fields = extract_fields(doc["doc_type"], image)
    if not llm_fields:
        for f in doc["fields"].values():
            f.setdefault("llm_messages", []).append("LLM second opinion unavailable")
        return
    context = {k: f["value"] for k, f in doc["fields"].items()}
    specs = {s.name: s for s in config.FIELDS[doc["doc_type"]]}
    for name, field in doc["fields"].items():
        spec, llm = specs[name], llm_fields.get(name, {})
        llm_value, llm_corr = normalize(spec.kind, llm.get("value", ""))
        field["raw_readings"].append(_llm_reading(spec, llm))
        field["llm_messages"] = []
        if not llm_value:
            field["llm_messages"].append("LLM returned no value")
            continue
        if similarity(llm_value, field["value"]) >= 0.999:
            field["two_pass"] = 1.0
            continue
        ctx = dict(context, options=spec.options)
        llm_passed, llm_msgs = validate(spec.kind, llm_value, ctx)
        off_passed = field["validator"]["passed"] if field["value"] else False
        take_llm = (llm_passed and not off_passed) or (
            llm_passed == off_passed and llm.get("confidence", 0) > field["read_conf"])
        field["llm_messages"].append(
            f"offline/LLM disagree: offline='{field['value']}' llm='{llm_value}' "
            f"-> kept {'LLM' if take_llm else 'offline'}")
        if take_llm:
            field.update(value=llm_value, raw=llm.get("value", ""), corrections=llm_corr,
                         read_conf=round(llm.get("confidence", 0.0), 3), two_pass=0.0,
                         validator={"passed": llm_passed, "messages": llm_msgs})
            context[name] = llm_value
        else:
            field["two_pass"] = min(field["two_pass"], 0.5)
