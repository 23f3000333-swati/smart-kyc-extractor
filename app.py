"""Streamlit review UI for the extraction results.

    streamlit run app.py

Reads output/extractions.json (written by run.py); it never re-runs OCR, so
it opens instantly. One document at a time: the image, its fields with
confidence and status, and the evidence behind a selected field.
"""
from __future__ import annotations

import json

import streamlit as st

import config
from src.preprocess import load_images

st.set_page_config(page_title="KYC Extraction Review", layout="wide")


@st.cache_data
def load_results() -> dict | None:
    """extractions.json, or None if run.py has not been run yet."""
    path = config.OUTPUT_DIR / "extractions.json"
    return json.loads(path.read_text()) if path.exists() else None


@st.cache_data
def first_page(file_name: str):
    """First page of an input file as a BGR image (PDFs via PyMuPDF)."""
    return load_images(config.INPUT_DIR / file_name)[0]


def status(field: dict) -> str:
    if not field["value"]:
        return "Missing"
    return "Review" if field["flagged"] else "OK"


def fields_table(doc: dict) -> None:
    """One row per field; confidence drawn as a bar."""
    rows = [{"Field": name.replace("_", " ").capitalize(), "Value": f["value"] or "-",
             "Confidence": f["confidence"], "Threshold": f["threshold"],
             "Type": "Handwritten" if f["handwritten"] else "Printed", "Status": status(f)}
            for name, f in doc["fields"].items()]
    st.dataframe(rows, width="stretch", hide_index=True, column_config={
        "Confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
        "Threshold": st.column_config.NumberColumn(format="%.2f")})


def field_details(doc: dict) -> None:
    """Evidence for one selected field."""
    names = list(doc["fields"])
    name = st.selectbox("Field details", names, format_func=lambda n: n.replace("_", " ").capitalize())
    f = doc["fields"][name]
    validator = {True: "Pass", False: "Fail", None: "n/a"}[f["validator"]["passed"]]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, [("OCR read", f"{f['read_conf']:.2f}"),
                                           ("Validator", validator),
                                           ("Reading agreement", f"{f['two_pass']:.2f}"),
                                           ("Cross-document", f"{f['cross_doc']:.2f}")]):
        col.metric(label, value)
    if f["flag_reasons"]:
        st.markdown("**Review reasons**\n" + "\n".join(f"- {r}" for r in f["flag_reasons"]))
    if f["corrections"]:
        st.markdown("**Corrections applied:** " + "; ".join(f["corrections"]))
    st.markdown("**OCR readings**")
    st.dataframe([{"Engine": r.get("engine"), "Image": r.get("version"),
                   "Text": r.get("text"), "Confidence": r.get("conf")}
                  for r in f["raw_readings"]], width="stretch", hide_index=True)


def document_view(docs: list[dict]) -> None:
    options = list(range(len(docs)))
    idx = st.selectbox("Document", options,
                       format_func=lambda i: f"{docs[i]['doc_type']}  |  {docs[i]['file']}")
    doc = docs[idx]
    left, right = st.columns([2, 3], gap="large")
    with left:
        st.image(first_page(doc["file"]), channels="BGR", width="stretch")
        st.caption(f"Classified as {doc['doc_type']} "
                   f"(confidence {doc['classification_confidence']:.2f})")
    with right:
        if not doc["fields"]:
            st.info("Out of scope for extraction. Listed in the flag report for manual handling.")
            return
        fields_table(doc)
        field_details(doc)


def conflicts_view(conflicts: list[dict]) -> None:
    if not conflicts:
        st.write("No conflicts between documents.")
        return
    st.caption("Values that disagree across documents. These are flagged for review and never auto-corrected.")
    rows = [{"Entity": c["entity"].replace("_", " ").capitalize(),
             "Values": " / ".join(", ".join(v) if isinstance(v, list) else v for v in c["values"])}
            for c in conflicts]
    st.dataframe(rows, width="stretch", hide_index=True)


def main() -> None:
    st.title("KYC Extraction Review")
    data = load_results()
    if data is None:
        st.error("No results found. Run `python run.py` first.")
        return

    docs = data["documents"]
    fields = [f for d in docs for f in d["fields"].values()]
    cols = st.columns(4)
    cols[0].metric("Documents", len(docs))
    cols[1].metric("Fields extracted", len(fields))
    cols[2].metric("Fields to review", sum(f["flagged"] for f in fields))
    cols[3].metric("Mode", data["mode"].capitalize())
    st.caption(f"Review thresholds: printed {data['thresholds']['printed']:.2f}, "
               f"handwritten high-value {data['thresholds']['handwritten_high_value']:.2f}")

    review, conflicts = st.tabs(["Documents", "Cross-document conflicts"])
    with review:
        document_view(docs)
    with conflicts:
        conflicts_view(data.get("cross_document_conflicts", []))


main()
