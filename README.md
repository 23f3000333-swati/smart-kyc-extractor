# smart-kyc-extractor

A document pipeline for insurance onboarding. It classifies KYC documents and
proposal forms, extracts the required fields, scores each field with a
confidence value, and flags uncertain fields for human review.

Supported documents: Aadhaar, PAN, Driving Licence, Passport, NACH mandate,
FATCA annexure, Benefit Illustration, Moral Hazard Questionnaire, Multiple
Policies Consent and Suitability Profiler. Other documents are classified as
`OTHER` and are not extracted.

The default mode runs fully offline. A vision LLM (Groq API) can optionally be
used as a second opinion.

## Setup

Requires Python 3.10+ (tested on Ubuntu).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env    # optional, only for hybrid / llm modes
```

The first run downloads the EasyOCR and TrOCR models (about 350 MB).

## Usage

```bash
python run.py                  # offline mode (default)
python run.py --mode hybrid    # offline, then LLM review of flagged documents
python run.py --mode llm       # LLM for every document
python evaluate.py             # compare results with data/ground_truth.json
streamlit run app.py           # review interface
pytest -q                      # unit tests
```

Input files go in `data/input/` (images or PDFs). If `GROQ_API_KEY` is not set,
the hybrid and llm modes fall back to offline mode.

## Output

All results are written to `output/`.

| File | Content |
|---|---|
| `extractions.json` | Document type and, for each field: value, confidence, OCR readings, corrections, validation result and review flags |
| `flag_report.md` | Review thresholds with rationale, all flagged fields and cross-document conflicts |
| `notes.md` | Handling of handwritten text, observed failure cases and limitations |
| `eval_report.md` | Field-level accuracy, split by printed and handwritten fields |

## How it works

```
input files
  -> preprocess   grayscale, deskew, contrast enhancement (2 image versions)
  -> classify     keyword matching on printed headings
  -> extract      printed: OCR text next to the field label
                  handwritten: crop next to the label, read with TrOCR and EasyOCR
                  checkboxes: ticked box detected by ink density
  -> validate     format and checksum rules (PAN, IFSC, Aadhaar, MRZ, dates)
  -> cross-check  same applicant details compared across documents
  -> score        confidence per field, flag if below threshold
  -> output       JSON and reports
```

## Confidence and review

Each field receives a confidence between 0 and 1:

```
confidence = 0.4 x OCR confidence
           + 0.3 x validation result
           + 0.2 x agreement between independent readings
           + 0.1 x agreement with other documents
```

Handwritten fields and character corrections reduce the score slightly.

A field is flagged for review when:

- its confidence is below **0.80** (printed fields) or **0.85** (handwritten
  IFSC, PAN/TIN, account number, dates and places),
- it fails validation, or
- it conflicts with the same detail on another document.

The higher threshold applies to fields where an error has a direct financial
or compliance impact. Conflicts between documents are reported and never
corrected automatically.

## Design principles

- **Offline by default.** Personal data stays on the machine. In hybrid mode,
  only documents with flagged fields are sent to the LLM.
- **No hardcoded answers.** Fields are located through labels defined in
  `config.py`. The ground truth file is used only by `evaluate.py`.
- **Traceable results.** Every value keeps its raw OCR readings and any
  corrections applied.

## Project structure

```
run.py           pipeline entry point
evaluate.py      accuracy evaluation
app.py           review interface
config.py        thresholds, field definitions, classification keywords
src/             preprocessing, OCR, classification, extraction,
                 validation, cross-checks, scoring, reports, LLM client
tests/           unit tests
data/input/      input documents
output/          results
```
