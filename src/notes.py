"""Writes output/notes.md: method notes (static) + failure cases observed in
this run (generated from the results, so they are always current)."""
from __future__ import annotations

from pathlib import Path

import config

METHOD = f"""\
# Notes: handwritten vs printed text, failure cases, limitations

## How handwritten text is handled differently from printed text

| | Printed fields (ID cards, form labels) | Handwritten fields (filled forms) |
|---|---|---|
| Where | EasyOCR full-page boxes; the value is the OCR text inside a window next to the printed label (or a format regex, e.g. PAN / Aadhaar / DL numbers, or MRZ) | The printed **label** is located with EasyOCR, then the window to its right/below is **cropped** and tightened to the ink (ruled lines removed) |
| Engines | EasyOCR (full page) on 2 image versions | **TrOCR** (`{config.TROCR_MODEL}`) **and** EasyOCR on the crop, each on 2 image versions = 4 readings |
| Alphabet | free | EasyOCR restricted to digits for account/application numbers/dates, A-Z0-9 for IFSC/PAN |
| Choice | vote over readings | vote over readings, validator-passing values first |
| Confidence | as formula | formula **-0.05 handwriting penalty**, and a stricter **{config.HANDWRITTEN_THRESHOLD:.2f}** threshold for IFSC/TIN/account/date/place |
| Ticks | - | checkbox fields: the option whose box contains the most ink wins (pixel density), margin = confidence |

Image versions: *original* = deskewed grayscale, *enhanced* = + CLAHE + light
non-local-means denoise. Same geometry, so a box found on one is cropped from
both. Format-aware corrections (O->0, I->1, S->5, Z->2, B->8 in digit slots
and the reverse in letter slots) are applied only where the field format
demands a digit/letter; each one is recorded and costs 0.05 confidence.
"""

PATTERNS = """\
## Failure patterns seen while tuning (2 improvement rounds)

| Pattern | Example in this data | What was done |
|---|---|---|
| Printed label mis-OCR'd on blurred scans | "with bank" -> `Kiih bant`, "IFSC" merged with the first handwritten letter (`Jirsc [S`) | fuzzy label match (75% for short labels), value may also be searched LEFT of a neighbouring label |
| Label phrase found inside a sentence | "Policy No" inside "Proposer/Policyholder" | labels must start their OCR box; short labels must be short boxes |
| Crop picks up printed header / neighbour line | FATCA TIN cell under a 2-line shaded header | header continuation lines skipped; densest *fully-contained* ink band; grey shading excluded from "ink" |
| Ruled lines / box borders through handwriting | dates written on dotted lines, policy no. inside a rectangle | horizontal lines erased; vertical lines erased only at crop edges (keeps 'd', '1') |
| Boxed one-char-per-cell codes | NACH account number, IFSC | cell borders detected, each cell recognised alone with a restricted alphabet; still the weakest offline field |
| TrOCR hallucinating dictionary words | digits read as `responsibility`, dates as `colourful` | shape score (digits for dates/numbers) ranks such readings last; validators reject them |
| TrOCR repetition loops | `000 000 000 ...` | `no_repeat_ngram_size=3`, max 24 tokens |
| '/' in handwritten dates read as '1' | `2610412026` | slash-slot rule for 10-digit runs (recorded correction) |
| Crossed-out options next to the ticked one | NACH frequency row | strike-through detection removes crossed options before the density vote |
| Overwritten / smudged values | Benefit-Illustration date | not recoverable offline: low confidence, flagged |
| Non-standard sample documents | MRZ of 50 chars with wrong check digits; Aadhaar starting with 1; PAN 4th char 'D' | extracted as printed, validity warnings raised (never "fixed") |
"""

LIMITS = """\
## Limitations

- TrOCR is a single-line model; multi-line or very wide crops degrade it, and
  its beam probability is over-confident on short garbage strings, which is
  why validators and agreement carry 50% of the confidence.
- Boxed handwriting (NACH account number / IFSC cells) is the hardest case:
  cell borders and digits touching them confuse both engines.
- Label anchoring depends on EasyOCR reading the printed label; on blurred
  photocopies a label can be missed and the field becomes "not found".
- Checkbox density cannot distinguish a tick from a heavy strike-through
  that crosses the box; low margins are flagged.
- English-only OCR: Hindi text on ID cards is ignored (not needed for targets).
- `trocr-small-handwritten` was used because of disk space on the dev
  machine; `trocr-base-handwritten` is a drop-in, more accurate option.

## What I would do with more time

- Fine-tune TrOCR (or PARSeq) on a few hundred labelled form crops,
  especially boxed digits; segment boxed fields cell-by-cell and read each
  cell with a digit/char classifier.
- Template registration (align each form to a blank template) instead of
  label search, which gives exact field crops for known HDFC forms.
- Calibrate the confidence weights on a labelled set (isotonic regression),
  so 0.85 really means 85% precision.
- Signature presence / match checks and photo-face match across IDs.
"""


def observed_failures(docs: list[dict], conflicts: list[dict], mode: str) -> list[str]:
    """Bullet list of problems seen in this run, grouped by type."""
    out = [f"## Failure cases observed in this run (`{mode}` mode)", ""]
    for doc in docs:
        for name, f in doc.get("fields", {}).items():
            if not f.get("flagged"):
                continue
            readings = [r.get("text", "") for r in f.get("raw_readings", []) if r.get("text")]
            distinct = sorted(set(readings))[:6]
            reason = "; ".join(f.get("flag_reasons", []))
            out.append(f"- **{doc['doc_type']}.{name}** "
                       f"({'handwritten' if f.get('handwritten') else 'printed'}) -> "
                       f"`{f.get('value', '')}` (conf {f.get('confidence', 0):.2f}). "
                       f"{reason}. Readings: {', '.join(f'`{t}`' for t in distinct) or 'none'}")
    out += ["", "### Data conflicts surfaced (not OCR errors)", ""]
    out += [f"- {c['entity']}: " + " vs ".join(
        ", ".join(v) if isinstance(v, list) else v for v in c["values"]) for c in conflicts] or ["- none"]
    return out


def write_notes(docs: list[dict], conflicts: list[dict], mode: str, path: Path) -> None:
    text = "\n".join([METHOD, PATTERNS, *observed_failures(docs, conflicts, mode), "", LIMITS])
    path.write_text(text)
