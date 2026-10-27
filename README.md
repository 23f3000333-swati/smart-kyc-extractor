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
