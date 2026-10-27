# smart-kyc-extractor

A document classification and field extraction pipeline for insurance onboarding.

## Problem Statement

Insurance companies like HDFC Life receive a stack of documents from every new customer: identity proofs (Aadhaar, PAN, Driving Licence, Passport) and handwritten forms (NACH mandate, FATCA Annexure, Benefit Illustration, Moral Hazard Questionnaire, Multiple Policies Consent, Suitability Profiler). Today, a human reads all 10 documents and types the important fields into their system. This is slow, expensive and error-prone. A wrong digit in an IFSC or account number means a failed premium debit or money sent to the wrong account.

The goal of this project is to build a pipeline that:

1. Classifies each document by its type
2. Extracts the required fields for each type
3. Scores how confident it is in every field
4. Flags low-confidence fields so a human only reviews the risky ones

Particular weight is given to the handwritten high-value fields: IFSC, TIN, bank account numbers, dates and place names.

## Solution

An offline-first pipeline that reads the documents locally with open-source OCR, so no personal data leaves the machine and nothing costs money. An optional free vision LLM (Groq) can be switched on as a second opinion for low-confidence fields.

The pipeline:

- Reads printed ID cards with EasyOCR and handwritten form fields with Microsoft's TrOCR handwriting model
- Validates every value against its expected format (IFSC regex, PAN regex, Aadhaar checksum, passport MRZ check digits, dates, amounts)
- Cross-checks the same facts across documents (name, date of birth, PAN vs TIN, application number) and flags conflicts
- Scores each field from four pieces of evidence: OCR confidence, format check, agreement between two readings, and consistency across documents
- Flags anything below the threshold (0.80 for printed fields, 0.85 for high-value handwritten fields) for human review

Classification was 100% accurate. Printed fields were 100% accurate. On handwritten fields, every wrong value was caught by the flagging system, so no incorrect value was ever auto-accepted.

## Tech Stack

**Language**
- Python

**Image handling**
- OpenCV: deskewing, contrast enhancement, box detection
- PyMuPDF (fitz): converting PDFs to images
- Pillow: basic image operations

**OCR**
- EasyOCR: reads printed text
- TrOCR (microsoft/trocr-base-handwritten): reads handwriting, via Hugging Face Transformers
- PyTorch: the deep-learning engine underneath TrOCR

**Validation and data**
- Pydantic: defines the field schemas
- Standard Python regex: format checks

**Optional LLM mode**
- Groq official Python client: calls the free Groq vision LLM
- python-dotenv: loads the API key from a .env file

**Testing**
- pytest: runs validator tests

## Pipeline

The pipeline runs each document through seven stages.

Document → [1] Preprocess → [2] Classify → [3] Extract → [4] Validate
→ [5] Cross-check → [6] Score → [7] Flag → JSON + Reports

**1. Preprocess.** PDFs are converted to images with PyMuPDF. Each page is deskewed, converted to grayscale and contrast-enhanced with CLAHE. Two versions are kept: original and enhanced.

**2. Classify.** EasyOCR reads the whole page, then the pipeline matches printed anchor headings ("AADHAAR", "NACH MANDATE", "Section 285BA" and so on) to one of the 10 document types. Unknown pages are tagged as OTHER.

**3. Extract.** For printed fields, the value is found by its label or by its format pattern. For handwritten fields, the printed label is located first, the area next to it is cropped, and the crop is read by both TrOCR and EasyOCR on both image versions, giving four readings. Checkbox fields are read by detecting which box has the most ink.

**4. Validate.** Each value is checked against its format: IFSC regex, PAN regex, Aadhaar Verhoeff checksum, MRZ check digits, valid dates, amount in figures vs words. Format-aware corrections (O to 0, I to 1, S to 5) are applied only where the format demands a specific character type. Every correction is logged and lowers confidence.

**5. Cross-check.** The same facts are compared across documents: application number, name, date of birth, PAN vs TIN, father's name, place. Mismatches are flagged, never auto-fixed.

**6. Score.** Confidence per field is calculated as:
`0.4 x OCR confidence + 0.3 x validator passed + 0.2 x two readings agree + 0.1 x cross-document match`
Minus 0.05 for handwriting, and minus 0.05 for each character correction (up to 0.15).

**7. Flag.** Threshold is 0.80 for printed fields and 0.85 for high-value handwritten fields. Anything below the threshold, any validator failure, and any cross-document conflict is sent to human review.

**Output files** in the `output/` folder:
- `extractions.json`: every field with value, confidence, raw readings, corrections and flags
- `flag_report.md`: all flagged fields with reasons
- `notes.md`: handwriting handling and failure cases
- `eval_report.md`: field-level accuracy against the answer key

## Running the Project Locally

Tested on Ubuntu, macOS and Windows. Needs about 3 to 4 GB of free disk space for the OCR models.

**1. Clone the repository**

```bash
git clone <your-repo-url>
cd smart-kyc-extractor
```

**2. Create a virtual environment**

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows
```

**3. Install the dependencies**

```bash
pip install -r requirements.txt
```

The first run downloads the OCR models (about 1.5 GB), so keep the internet on.

**4. Add your documents**

Put the 10 identity and insurance documents into `data/input/`.

**5. Run the pipeline**

Offline mode (default, no API key needed):

```bash
python run.py --mode offline
```

Hybrid mode (uses the free Groq vision LLM for low-confidence fields):

- Get a free API key from console.groq.com
- Copy `.env.example` to `.env` and paste your key:
