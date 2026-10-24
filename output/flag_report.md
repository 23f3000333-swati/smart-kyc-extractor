# Flag report (mode: `offline`)

## Thresholds

| Field group | Threshold |
|---|---|
| Printed fields (ID cards, printed labels) | **0.80** |
| High-value handwritten fields (IFSC, TIN/PAN, account number, dates, places) | **0.85** |

**Rationale.** The cost of an error is very asymmetric. A wrong IFSC or account
number means a failed NACH debit or money sent to the wrong account; a wrong
TIN/PAN breaks FATCA/CRS reporting; a wrong date or place on a declaration can
invalidate a signed consent. A human check of a flagged field costs a few
seconds. So the pipeline deliberately **over-flags**: handwritten high-value
fields need a higher score (0.85) because handwriting OCR is less reliable and
its engine confidence is less well calibrated than printed OCR. Confidence is
`0.4*read + 0.3*validator + 0.2*two-pass agreement + 0.1*cross-doc agreement`,
minus 0.05 for handwriting and 0.05 per character correction (max 0.15), so a
field can only clear 0.85 if the engines agree *and* the format validates.

Fields are also flagged, whatever their score, when a validator fails or warns
(e.g. checksum failures on sample IDs), when another document disagrees, or
(hybrid mode) when the offline and LLM readings disagree.

## Flagged fields

| file | doc_type | field | value | confidence | reason |
|---|---|---|---|---|---|
| Aadhar.png | AADHAAR | aadhaar_number | `123456789012` | 0.89 | validity warning: Aadhaar cannot start with 0/1 (sample card?); Verhoeff checksum fails (sample card?) |
| ChatGPT Image May 2, 2026, 03_43_11 PM.png | DRIVING_LICENCE | dl_number | `MH1220210001234` | 0.95 | cross-doc: DL number prefix MH = MAHARASHTRA, but the licence address/authority mentions BIHAR |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | PASSPORT | mrz_line_2 | `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<<<<<<08` | 0.59 | confidence 0.59 < 0.80; validator failed: length 50 != 44 (non-standard TD3 line); date of birth check digit '5' != computed 2; date of expiry check digit '0' != computed 9 |
| ECS.jpeg | NACH_MANDATE | bank_account_number | `1704258912` | 0.68 | confidence 0.68 < 0.85 |
| ECS.jpeg | NACH_MANDATE | ifsc_code | `BIN6227012` | 0.22 | confidence 0.22 < 0.85; validator failed: IFSC format ^[A-Z]{4}0[A-Z0-9]{6}$ fails |
| ECS.jpeg | NACH_MANDATE | bank_name | `State Bank of India` | 0.46 | confidence 0.46 < 0.80 |
| ECS.jpeg | NACH_MANDATE | amount_figures | `350006` | 0.47 | confidence 0.47 < 0.80; validator failed: amount in words (50000) != figures (350006) |
| ECS.jpeg | NACH_MANDATE | frequency | `As & when presented` | 0.90 | validity warning: option labels not found: ['H. Yrly', 'Monthly', 'Qly', 'Yrly'] |
| Fatca.jpeg | FATCA_ANNEXURE | policy_number | `65131125` | 0.64 | confidence 0.64 < 0.80; cross-doc: application_number differs from BENEFIT_ILLUSTRATION.application_number = '150013161095'; cross-doc: application_number differs from MORAL_HAZARD.application_number = '1500137601025'; cross-doc: application_number differs from SUITABILITY_PROFILER.application_number = '150013161025' |
| Fatca.jpeg | FATCA_ANNEXURE | tin_pan | `BPQPD3051R` | 0.72 | confidence 0.72 < 0.85; cross-doc: pan differs from PAN.pan_number = 'ABCDE1234F' |
| Fatca.jpeg | FATCA_ANNEXURE | fathers_name | `Arjun , Das Kuma` | 0.69 | confidence 0.69 < 0.80; cross-doc: fathers_name differs from PAN.fathers_name = 'KUMAR' |
| Fatca.jpeg | FATCA_ANNEXURE | place_of_birth | `won together` | 0.62 | confidence 0.62 < 0.85 |
| Fatca.jpeg | FATCA_ANNEXURE | nationality | `IMLEN` | 0.46 | confidence 0.46 < 0.80; validator failed: unknown nationality 'IMLEN' |
| ID.png | PAN | pan_number | `ABCDE1234F` | 0.90 | validity warning: 4th char 'D' is not a valid PAN holder type; cross-doc: pan differs from FATCA_ANNEXURE.tin_pan = 'BPQPD3051R' |
| ID.png | PAN | fathers_name | `KUMAR` | 0.90 | cross-doc: fathers_name differs from FATCA_ANNEXURE.fathers_name = 'Arjun , Das Kuma' |
| Illustration.jpeg | BENEFIT_ILLUSTRATION | application_number | `150013161095` | 0.58 | confidence 0.58 < 0.80; cross-doc: application_number differs from FATCA_ANNEXURE.policy_number = '65131125'; cross-doc: application_number differs from MORAL_HAZARD.application_number = '1500137601025' |
| Illustration.jpeg | BENEFIT_ILLUSTRATION | date | `/-6 01` | 0.27 | confidence 0.27 < 0.85; validator failed: not a valid DD/MM/YYYY date |
| Illustration.jpeg | BENEFIT_ILLUSTRATION | place | `hles A Bikax` | 0.49 | confidence 0.49 < 0.85; cross-doc: signing_place differs from MORAL_HAZARD.place = 'West Rams'; cross-doc: signing_place differs from MULTIPLE_POLICIES_CONSENT.place = 'West Bihar'; cross-doc: signing_place differs from SUITABILITY_PROFILER.place = 'most extra' |
| Moral.jpeg | MORAL_HAZARD | application_number | `1500137601025` | 0.84 | cross-doc: application_number differs from FATCA_ANNEXURE.policy_number = '65131125'; cross-doc: application_number differs from BENEFIT_ILLUSTRATION.application_number = '150013161095'; cross-doc: application_number differs from SUITABILITY_PROFILER.application_number = '150013161025' |
| Moral.jpeg | MORAL_HAZARD | name_of_life_assured | `Asbok` | 0.79 | confidence 0.79 < 0.80; cross-doc: applicant_name differs from AADHAAR.full_name = 'Mr. Ashok'; cross-doc: applicant_name differs from PAN.full_name = 'MR. ASHOK'; cross-doc: applicant_name differs from DRIVING_LICENCE.name = 'MR. ASHOK'; cross-doc: applicant_name differs from BENEFIT_ILLUSTRATION.policyholder_name = 'Ashok'; cross-doc: applicant_name differs from MULTIPLE_POLICIES_CONSENT.proposer_name = 'Ashok'; cross-doc: applicant_name differs from SUITABILITY_PROFILER.name_of_life_assured = 'Ashok' |
| Moral.jpeg | MORAL_HAZARD | nominee_relationship | `of nominee Klepheu` | 0.38 | confidence 0.38 < 0.80; validator failed: 'of nominee Klepheu' is not a known relationship |
| Moral.jpeg | MORAL_HAZARD | date | `Dommryry Places .` | 0.22 | confidence 0.22 < 0.85; validator failed: not a valid DD/MM/YYYY date |
| Moral.jpeg | MORAL_HAZARD | place | `West Rams` | 0.65 | confidence 0.65 < 0.85; cross-doc: signing_place differs from BENEFIT_ILLUSTRATION.place = 'hles A Bikax'; cross-doc: signing_place differs from MULTIPLE_POLICIES_CONSENT.place = 'West Bihar'; cross-doc: signing_place differs from SUITABILITY_PROFILER.place = 'most extra' |
| split.jpeg | MULTIPLE_POLICIES_CONSENT | date | `26/04/2026` | 0.77 | confidence 0.77 < 0.85 |
| split.jpeg | MULTIPLE_POLICIES_CONSENT | place | `West Bihar` | 0.76 | confidence 0.76 < 0.85; cross-doc: signing_place differs from BENEFIT_ILLUSTRATION.place = 'hles A Bikax'; cross-doc: signing_place differs from MORAL_HAZARD.place = 'West Rams'; cross-doc: signing_place differs from SUITABILITY_PROFILER.place = 'most extra' |
| suitability.jpeg | SUITABILITY_PROFILER | application_number | `150013161025` | 0.77 | confidence 0.77 < 0.80; cross-doc: application_number differs from FATCA_ANNEXURE.policy_number = '65131125'; cross-doc: application_number differs from MORAL_HAZARD.application_number = '1500137601025' |
| suitability.jpeg | SUITABILITY_PROFILER | date | `9/424` | 0.19 | confidence 0.19 < 0.85; validator failed: not a valid DD/MM/YYYY date |
| suitability.jpeg | SUITABILITY_PROFILER | place | `most extra` | 0.62 | confidence 0.62 < 0.85; cross-doc: signing_place differs from BENEFIT_ILLUSTRATION.place = 'hles A Bikax'; cross-doc: signing_place differs from MORAL_HAZARD.place = 'West Rams'; cross-doc: signing_place differs from MULTIPLE_POLICIES_CONSENT.place = 'West Bihar' |

**28 of 44 fields flagged.**

## Document-level flags

| file | doc_type | reason |
|---|---|---|
| Assignment Ashok.pdf | OTHER (OTHER_ASSIGNMENT) | out of scope, not extracted |
| Proposal Ashok.pdf | OTHER (OTHER_PROPOSAL) | out of scope, not extracted |

## Cross-document conflicts (flagged, never auto-fixed)

- **application_number**: FATCA_ANNEXURE.policy_number='65131125' vs BENEFIT_ILLUSTRATION.application_number='150013161095' vs MORAL_HAZARD.application_number='1500137601025' vs SUITABILITY_PROFILER.application_number='150013161025'
- **applicant_name**: AADHAAR.full_name='Mr. Ashok', PAN.full_name='MR. ASHOK', DRIVING_LICENCE.name='MR. ASHOK', BENEFIT_ILLUSTRATION.policyholder_name='Ashok', MULTIPLE_POLICIES_CONSENT.proposer_name='Ashok', SUITABILITY_PROFILER.name_of_life_assured='Ashok' vs MORAL_HAZARD.name_of_life_assured='Asbok'
- **fathers_name**: PAN.fathers_name='KUMAR' vs FATCA_ANNEXURE.fathers_name='Arjun , Das Kuma'
- **pan**: PAN.pan_number='ABCDE1234F' vs FATCA_ANNEXURE.tin_pan='BPQPD3051R'
- **signing_place**: BENEFIT_ILLUSTRATION.place='hles A Bikax' vs MORAL_HAZARD.place='West Rams' vs MULTIPLE_POLICIES_CONSENT.place='West Bihar' vs SUITABILITY_PROFILER.place='most extra'
- **dl_state**: DL number prefix MH = MAHARASHTRA, but the licence address/authority mentions BIHAR
