# Notes: handwritten vs printed text, failure cases, limitations

## How handwritten text is handled differently from printed text

| | Printed fields (ID cards, form labels) | Handwritten fields (filled forms) |
|---|---|---|
| Where | EasyOCR full-page boxes; the value is the OCR text inside a window next to the printed label (or a format regex, e.g. PAN / Aadhaar / DL numbers, or MRZ) | The printed **label** is located with EasyOCR, then the window to its right/below is **cropped** and tightened to the ink (ruled lines removed) |
| Engines | EasyOCR (full page) on 2 image versions | **TrOCR** (`microsoft/trocr-small-handwritten`) **and** EasyOCR on the crop, each on 2 image versions = 4 readings |
| Alphabet | free | EasyOCR restricted to digits for account/application numbers/dates, A-Z0-9 for IFSC/PAN |
| Choice | vote over readings | vote over readings, validator-passing values first |
| Confidence | as formula | formula **-0.05 handwriting penalty**, and a stricter **0.85** threshold for IFSC/TIN/account/date/place |
| Ticks | - | checkbox fields: the option whose box contains the most ink wins (pixel density), margin = confidence |

Image versions: *original* = deskewed grayscale, *enhanced* = + CLAHE + light
non-local-means denoise. Same geometry, so a box found on one is cropped from
both. Format-aware corrections (O->0, I->1, S->5, Z->2, B->8 in digit slots
and the reverse in letter slots) are applied only where the field format
demands a digit/letter; each one is recorded and costs 0.05 confidence.

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

## Failure cases observed in this run (`offline` mode)

- **AADHAAR.aadhaar_number** (printed) -> `123456789012` (conf 0.89). validity warning: Aadhaar cannot start with 0/1 (sample card?); Verhoeff checksum fails (sample card?). Readings: `1234 5678 9012`, `12345678 9012`
- **DRIVING_LICENCE.dl_number** (printed) -> `MH1220210001234` (conf 0.95). cross-doc: DL number prefix MH = MAHARASHTRA, but the licence address/authority mentions BIHAR. Readings: `MH12 2021 0001234`
- **PASSPORT.mrz_line_2** (printed) -> `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<<<<<<08` (conf 0.59). confidence 0.59 < 0.80; validator failed: length 50 != 44 (non-standard TD3 line); date of birth check digit '5' != computed 2; date of expiry check digit '0' != computed 9. Readings: `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<<<<<<08`
- **NACH_MANDATE.bank_account_number** (handwritten) -> `1704258912` (conf 0.68). confidence 0.68 < 0.85. Readings: `1704258912`, `1904262122`, `514`, `57`, `BOLDOBIBAYALLY OF RETAIFORMMENTATION`, `BOLDOMBBOARDAL OF STATEMENTMENTATION`
- **NACH_MANDATE.ifsc_code** (handwritten) -> `BIN6227012` (conf 0.22). confidence 0.22 < 0.85; validator failed: IFSC format ^[A-Z]{4}0[A-Z0-9]{6}$ fails. Readings: `81N6227012`, `HDE1`, `SZPPF`, `[S`, `is a more low in a`, `is its wholesalers .`
- **NACH_MANDATE.bank_name** (handwritten) -> `State Bank of India` (conf 0.46). confidence 0.46 < 0.80. Readings: `' State- " Home . ' ' ' I don't`, `6LQ1014I2L51211LLZLL LL Stale Bank pLInia`, `BLQ1014I216I2 !4LLZLLLL Stale Bank Dl India`, `HelpLearn to edit`
- **NACH_MANDATE.amount_figures** (handwritten) -> `350006` (conf 0.47). confidence 0.47 < 0.80; validator failed: amount in words (50000) != figures (350006). Readings: `1/2 50,000 .`, `350,006`, `JIRE00000 .`
- **NACH_MANDATE.frequency** (handwritten) -> `As & when presented` (conf 0.90). validity warning: option labels not found: ['H. Yrly', 'Monthly', 'Qly', 'Yrly']. Readings: `As & when presented`
- **FATCA_ANNEXURE.policy_number** (handwritten) -> `65131125` (conf 0.64). confidence 0.64 < 0.80; cross-doc: application_number differs from BENEFIT_ILLUSTRATION.application_number = '150013161095'; cross-doc: application_number differs from MORAL_HAZARD.application_number = '1500137601025'; cross-doc: application_number differs from SUITABILITY_PROFILER.application_number = '150013161025'. Readings: `11571376126`, `65131125`, `Insolidation . .`, `Missouri37601025 -`
- **FATCA_ANNEXURE.tin_pan** (handwritten) -> `BPQPD3051R` (conf 0.72). confidence 0.72 < 0.85; cross-doc: pan differs from PAN.pan_number = 'ABCDE1234F'. Readings: `BPQPD 305I R.`, `BPQPD305 P`, `BPQPD3051R`
- **FATCA_ANNEXURE.fathers_name** (handwritten) -> `Arjun , Das Kuma` (conf 0.69). confidence 0.69 < 0.80; cross-doc: fathers_name differs from PAN.fathers_name = 'KUMAR'. Readings: `Ariun Doc Kim`, `Ariun Doc Kimm`, `Arjun , Das Kuma`, `Arjun , Dog Kuma`
- **FATCA_ANNEXURE.place_of_birth** (handwritten) -> `won together` (conf 0.62). confidence 0.62 < 0.85. Readings: `WJeq + Behx`, `Weq 4 Behax`, `Woot Behar .`, `won together .`
- **FATCA_ANNEXURE.nationality** (handwritten) -> `IMLEN` (conf 0.46). confidence 0.46 < 0.80; validator failed: unknown nationality 'IMLEN'. Readings: `Imlen ,`, `Imlen .`, `Lrleon`, `rleon`
- **PAN.pan_number** (printed) -> `ABCDE1234F` (conf 0.90). validity warning: 4th char 'D' is not a valid PAN holder type; cross-doc: pan differs from FATCA_ANNEXURE.tin_pan = 'BPQPD3051R'. Readings: `ABCDE1234F`
- **PAN.fathers_name** (printed) -> `KUMAR` (conf 0.90). cross-doc: fathers_name differs from FATCA_ANNEXURE.fathers_name = 'Arjun , Das Kuma'. Readings: `S/O KUMAR`
- **BENEFIT_ILLUSTRATION.application_number** (handwritten) -> `150013161095` (conf 0.58). confidence 0.58 < 0.80; cross-doc: application_number differs from FATCA_ANNEXURE.policy_number = '65131125'; cross-doc: application_number differs from MORAL_HAZARD.application_number = '1500137601025'. Readings: `150013161095-`, `50013711021`, `500137116217`, `legislation .`
- **BENEFIT_ILLUSTRATION.date** (handwritten) -> `/-6 01` (conf 0.27). confidence 0.27 < 0.85; validator failed: not a valid DD/MM/YYYY date. Readings: `/-25 0`, `/-6 01`, `advantages . .`, `advantages of age`
- **BENEFIT_ILLUSTRATION.place** (handwritten) -> `hles A Bikax` (conf 0.49). confidence 0.49 < 0.85; cross-doc: signing_place differs from MORAL_HAZARD.place = 'West Rams'; cross-doc: signing_place differs from MULTIPLE_POLICIES_CONSENT.place = 'West Bihar'; cross-doc: signing_place differs from SUITABILITY_PROFILER.place = 'most extra'. Readings: `display #`, `displaystyle`, `hles A Bikax`, `obhrdkiat ~loc 4 Rsha LDiGia`, `ophurdkiat ~loc 4 Rshar Az Sa`
- **MORAL_HAZARD.application_number** (handwritten) -> `1500137601025` (conf 0.84). cross-doc: application_number differs from FATCA_ANNEXURE.policy_number = '65131125'; cross-doc: application_number differs from BENEFIT_ILLUSTRATION.application_number = '150013161095'; cross-doc: application_number differs from SUITABILITY_PROFILER.application_number = '150013161025'. Readings: `# 150013761025`, `1500137601025`
- **MORAL_HAZARD.name_of_life_assured** (handwritten) -> `Asbok` (conf 0.79). confidence 0.79 < 0.80; cross-doc: applicant_name differs from AADHAAR.full_name = 'Mr. Ashok'; cross-doc: applicant_name differs from PAN.full_name = 'MR. ASHOK'; cross-doc: applicant_name differs from DRIVING_LICENCE.name = 'MR. ASHOK'; cross-doc: applicant_name differs from BENEFIT_ILLUSTRATION.policyholder_name = 'Ashok'; cross-doc: applicant_name differs from MULTIPLE_POLICIES_CONSENT.proposer_name = 'Ashok'; cross-doc: applicant_name differs from SUITABILITY_PROFILER.name_of_life_assured = 'Ashok'. Readings: `Asbok`, `Ashak . .`, `Ashok . .`
- **MORAL_HAZARD.nominee_relationship** (handwritten) -> `of nominee Klepheu` (conf 0.38). confidence 0.38 < 0.80; validator failed: 'of nominee Klepheu' is not a known relationship. Readings: `' promises ... Help how ...`, `* of nominee`, `a member`, `of nominee "Kiepheu`, `of nominee 'Klepheu`
- **MORAL_HAZARD.date** (handwritten) -> `Dommryry Places .` (conf 0.22). confidence 0.22 < 0.85; validator failed: not a valid DD/MM/YYYY date. Readings: `03- 8.--`, `03/0 8--`, `Dommryry Places .`, `consumer places .`
- **MORAL_HAZARD.place** (handwritten) -> `West Rams` (conf 0.65). confidence 0.65 < 0.85; cross-doc: signing_place differs from BENEFIT_ILLUSTRATION.place = 'hles A Bikax'; cross-doc: signing_place differs from MULTIPLE_POLICIES_CONSENT.place = 'West Bihar'; cross-doc: signing_place differs from SUITABILITY_PROFILER.place = 'most extra'. Readings: `Ilos / Rimr`, `Inlos / Rimr`, `West Rams .`
- **MULTIPLE_POLICIES_CONSENT.date** (handwritten) -> `26/04/2026` (conf 0.77). confidence 0.77 < 0.85. Readings: `26`, `26 104 12026`, `26 104 2026`, `2610412026`
- **MULTIPLE_POLICIES_CONSENT.place** (handwritten) -> `West Bihar` (conf 0.76). confidence 0.76 < 0.85; cross-doc: signing_place differs from BENEFIT_ILLUSTRATION.place = 'hles A Bikax'; cross-doc: signing_place differs from MORAL_HAZARD.place = 'West Rams'; cross-doc: signing_place differs from SUITABILITY_PROFILER.place = 'most extra'. Readings: `WesE B; har`, `WesE Bi har`, `West Bihar .`
- **SUITABILITY_PROFILER.application_number** (handwritten) -> `150013161025` (conf 0.77). confidence 0.77 < 0.80; cross-doc: application_number differs from FATCA_ANNEXURE.policy_number = '65131125'; cross-doc: application_number differs from MORAL_HAZARD.application_number = '1500137601025'. Readings: `10031601025`, `150013161025`, `500131601025`
- **SUITABILITY_PROFILER.date** (handwritten) -> `9/424` (conf 0.19). confidence 0.19 < 0.85; validator failed: not a valid DD/MM/YYYY date. Readings: `9/424`, `colourful ,`
- **SUITABILITY_PROFILER.place** (handwritten) -> `most extra` (conf 0.62). confidence 0.62 < 0.85; cross-doc: signing_place differs from BENEFIT_ILLUSTRATION.place = 'hles A Bikax'; cross-doc: signing_place differs from MORAL_HAZARD.place = 'West Rams'; cross-doc: signing_place differs from MULTIPLE_POLICIES_CONSENT.place = 'West Bihar'. Readings: `+loc L Bkx`, `most Ethan`, `most extra`, `~loc[ Bhar`

### Data conflicts surfaced (not OCR errors)

- application_number: FATCA_ANNEXURE.policy_number='65131125' vs BENEFIT_ILLUSTRATION.application_number='150013161095' vs MORAL_HAZARD.application_number='1500137601025' vs SUITABILITY_PROFILER.application_number='150013161025'
- applicant_name: AADHAAR.full_name='Mr. Ashok', PAN.full_name='MR. ASHOK', DRIVING_LICENCE.name='MR. ASHOK', BENEFIT_ILLUSTRATION.policyholder_name='Ashok', MULTIPLE_POLICIES_CONSENT.proposer_name='Ashok', SUITABILITY_PROFILER.name_of_life_assured='Ashok' vs MORAL_HAZARD.name_of_life_assured='Asbok'
- fathers_name: PAN.fathers_name='KUMAR' vs FATCA_ANNEXURE.fathers_name='Arjun , Das Kuma'
- pan: PAN.pan_number='ABCDE1234F' vs FATCA_ANNEXURE.tin_pan='BPQPD3051R'
- signing_place: BENEFIT_ILLUSTRATION.place='hles A Bikax' vs MORAL_HAZARD.place='West Rams' vs MULTIPLE_POLICIES_CONSENT.place='West Bihar' vs SUITABILITY_PROFILER.place='most extra'
- dl_state: DL number prefix MH = MAHARASHTRA, but the licence address/authority mentions BIHAR

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
