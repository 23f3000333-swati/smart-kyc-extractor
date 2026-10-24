"""smart-kyc-extractor: classify, extract, validate, score and flag KYC /
insurance onboarding documents.

    python run.py                    # offline (default): EasyOCR + TrOCR only
    python run.py --mode hybrid      # offline, then Groq LLM for flagged docs
    python run.py --mode llm         # Groq LLM for every document

Outputs (in output/): extractions.json, flag_report.md, notes.md, plus a
per-mode copy extractions_<mode>.json used by evaluate.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import time

import config
from src import llm_client
from src.classify import classify_document, page_text
from src.crosscheck import cross_check
from src.extract import extract_document
from src.flag import apply_flags, write_flag_report
from src.notes import write_notes
from src.ocr import full_page_ocr
from src.preprocess import list_inputs, load_pages

log = logging.getLogger("run")


def process_offline(path) -> dict:
    """Classify + extract one file with offline OCR only."""
    pages = load_pages(path)
    # Classification needs one OCR pass (enhanced); the second pass on the
    # original image is only paid for documents we actually extract.
    enhanced = [full_page_ocr(p.enhanced, path, p.index, "enhanced") for p in pages]
    doc_type, cls_conf, detail = classify_document([page_text(b) for b in enhanced])
    log.info("%s -> %s (%.2f, %s)", path.name, doc_type, cls_conf, detail)
    doc = {"file": path.name, "pages": len(pages), "doc_type": doc_type,
           "classification_confidence": cls_conf, "classification_detail": detail,
           "fields": {}, "auxiliary": {}}
    if doc_type != "OTHER":
        # In-scope documents are single-page: extract from the first page.
        ocr_page = {"original": full_page_ocr(pages[0].original, path, 0, "original"),
                    "enhanced": enhanced[0]}
        doc["fields"], doc["auxiliary"] = extract_document(doc_type, pages[0], ocr_page)
    return doc


def process_llm_only(path) -> dict:
    """Classify + extract one file with the LLM (mode=llm)."""
    pages = load_pages(path)
    result = llm_client.classify_and_extract(pages[0].original)
    doc_type = result["doc_type"] if result["doc_type"] in config.FIELDS else "OTHER"
    doc = {"file": path.name, "pages": len(pages), "doc_type": doc_type,
           "classification_confidence": result.get("doc_type_confidence", 0.0),
           "classification_detail": result["doc_type"], "fields": {}, "auxiliary": {}}
    if doc_type != "OTHER":
        doc["fields"] = llm_client.to_field_results(doc_type, result["fields"])
    return doc


def run(mode: str) -> list[dict]:
    """Run the full pipeline and write all outputs."""
    if mode in ("llm", "hybrid") and not llm_client.available():
        log.warning("GROQ_API_KEY not set (or groq not installed): running offline only")
        mode = "offline"
    files = list_inputs()
    log.info("%d input files, mode=%s", len(files), mode)
    docs = []
    for path in files:
        t0 = time.time()
        doc = process_llm_only(path) if mode == "llm" else process_offline(path)
        doc["seconds"] = round(time.time() - t0, 1)
        docs.append(doc)

    conflicts = cross_check(docs)
    apply_flags(docs)

    if mode == "hybrid":
        # Second opinion only for documents that still have flagged fields.
        for doc in docs:
            if doc["doc_type"] != "OTHER" and doc["flagged"]:
                pages = load_pages(config.INPUT_DIR / doc["file"])
                llm_client.merge_second_opinion(doc, pages[0].original)
        conflicts = cross_check(docs)  # re-run with merged values
        apply_flags(docs)

    write_outputs(docs, conflicts, mode)
    return docs


def write_outputs(docs: list[dict], conflicts: list[dict], mode: str) -> None:
    """extractions.json (+ per-mode copy), flag_report.md, notes.md."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode,
               "thresholds": {"printed": config.PRINTED_THRESHOLD,
                              "handwritten_high_value": config.HANDWRITTEN_THRESHOLD},
               "documents": [public_view(d) for d in docs],
               "cross_document_conflicts": conflicts}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    (config.OUTPUT_DIR / "extractions.json").write_text(text)
    (config.OUTPUT_DIR / f"extractions_{mode}.json").write_text(text)
    write_flag_report(docs, conflicts, mode, config.OUTPUT_DIR / "flag_report.md")
    write_notes(docs, conflicts, mode, config.OUTPUT_DIR / "notes.md")
    n = sum(len(d["fields"]) for d in docs)
    flagged = sum(f["flagged"] for d in docs for f in d["fields"].values())
    log.info("done: %d docs, %d fields, %d flagged -> %s", len(docs), n, flagged, config.OUTPUT_DIR)


FIELD_KEYS = ["value", "raw", "confidence", "handwritten", "raw_readings", "corrections",
              "validator", "flagged", "flag_reasons", "threshold", "read_conf",
              "two_pass", "cross_doc"]


def public_view(doc: dict) -> dict:
    """The per-document JSON written to extractions.json."""
    def clean(f: dict) -> dict:
        out = {k: f.get(k) for k in FIELD_KEYS}
        out["raw_readings"] = [{k: v for k, v in r.items() if k != "crop"}
                               for r in f.get("raw_readings", [])]
        return out
    return {"file": doc["file"], "doc_type": doc["doc_type"],
            "classification_confidence": doc["classification_confidence"],
            "classification_detail": doc.get("classification_detail"),
            "flagged": doc.get("flagged"), "flag_reasons": doc.get("flag_reasons"),
            "fields": {k: clean(f) for k, f in doc["fields"].items()},
            "auxiliary": {k: {"value": f.get("value"), "raw": f.get("raw")}
                          for k, f in doc.get("auxiliary", {}).items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["offline", "llm", "hybrid"], default="offline")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "urllib3", "PIL", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    run(args.mode)


if __name__ == "__main__":
    main()
