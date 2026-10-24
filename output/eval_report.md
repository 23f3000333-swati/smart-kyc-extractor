# Evaluation report

Field-level exact match after normalisation (case, spaces, Mr./MR., punctuation, commas). Ground truth: `data/ground_truth.json`.

## Mode comparison

| metric | offline |
|---|---|
| classification | 12/12 (100.0%) |
| all fields | 27/44 (61.4%) |
| printed fields | 16/16 (100.0%) |
| handwritten fields | 11/28 (39.3%) |
| fields flagged for review | 28 |
| wrong fields caught by a flag | 17/17 |
| correct and auto-accepted (not flagged) | 16 |

_Not run yet: hybrid (hybrid needs GROQ_API_KEY in .env; then `python run.py --mode hybrid && python evaluate.py`)._

## Per-field results: `offline`

| doc_type | field | hw | expected | got | conf | flagged | ok |
|---|---|---|---|---|---|---|---|
| AADHAAR | aadhaar_number | P | `123456789012` | `123456789012` | 0.89 | yes | ✅ |
| AADHAAR | full_name | P | `Mr. Ashok` | `Mr. Ashok` | 0.86 | no | ✅ |
| AADHAAR | date_of_birth | P | `18/12/1979` | `18/12/1979` | 0.98 | no | ✅ |
| AADHAAR | address | P | `S/O Kumar, Kataia, West Bihar, India - 841543` | `S/O Kumar, Kataia, West Bihar India 841543` | 0.83 | no | ✅ |
| DRIVING_LICENCE | dl_number | P | `MH12 2021 0001234` | `MH1220210001234` | 0.95 | yes | ✅ |
| DRIVING_LICENCE | name | P | `MR. ASHOK` | `MR. ASHOK` | 0.91 | no | ✅ |
| DRIVING_LICENCE | date_of_issue | P | `15/06/2021` | `15/06/2021` | 0.95 | no | ✅ |
| DRIVING_LICENCE | valid_till | P | `14/06/2041` | `14/06/2041` | 0.95 | no | ✅ |
| PASSPORT | passport_number | P | `X1234567` | `X1234567` | 0.95 | no | ✅ |
| PASSPORT | date_of_birth | P | `18/12/1979` | `18/12/1979` | 0.99 | no | ✅ |
| PASSPORT | date_of_expiry | P | `01/01/2030` | `01/01/2030` | 0.93 | no | ✅ |
| PASSPORT | mrz_line_2 | P | `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<<<<<<08` | `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<<<<<<08` | 0.59 | yes | ✅ |
| NACH_MANDATE | bank_account_number | H | `31004258912` | `1704258912` | 0.68 | yes | ❌ |
| NACH_MANDATE | ifsc_code | H | `SBIN0227112` | `BIN6227012` | 0.22 | yes | ❌ |
| NACH_MANDATE | bank_name | H | `State Bank of India` | `State Bank of India` | 0.46 | yes | ✅ |
| NACH_MANDATE | amount_figures | H | `50000` | `350006` | 0.47 | yes | ❌ |
| NACH_MANDATE | frequency | H | `As & when presented` | `As & when presented` | 0.90 | yes | ✅ |
| FATCA_ANNEXURE | policy_number | H | `1500137601025` | `65131125` | 0.64 | yes | ❌ |
| FATCA_ANNEXURE | tin_pan | H | `BPQPD3051R` | `BPQPD3051R` | 0.72 | yes | ✅ |
| FATCA_ANNEXURE | fathers_name | H | `Arjun Das Kumar` | `Arjun , Das Kuma` | 0.69 | yes | ❌ |
| FATCA_ANNEXURE | place_of_birth | H | `West Bihar` | `won together` | 0.62 | yes | ❌ |
| FATCA_ANNEXURE | nationality | H | `Indian` | `IMLEN` | 0.46 | yes | ❌ |
| PAN | pan_number | P | `ABCDE1234F` | `ABCDE1234F` | 0.90 | yes | ✅ |
| PAN | full_name | P | `MR. ASHOK` | `MR. ASHOK` | 0.86 | no | ✅ |
| PAN | fathers_name | P | `KUMAR` | `KUMAR` | 0.90 | yes | ✅ |
| PAN | date_of_birth | P | `18/12/1979` | `18/12/1979` | 0.95 | no | ✅ |
| BENEFIT_ILLUSTRATION | application_number | H | `1500137601025` | `150013161095` | 0.58 | yes | ❌ |
| BENEFIT_ILLUSTRATION | policyholder_name | H | `Ashok` | `Ashok` | 0.81 | no | ✅ |
| BENEFIT_ILLUSTRATION | date | H | `26/04/2026` | `/-6 01` | 0.27 | yes | ❌ |
| BENEFIT_ILLUSTRATION | place | H | `West Bihar` | `hles A Bikax` | 0.49 | yes | ❌ |
| MORAL_HAZARD | application_number | H | `1500137601025` | `1500137601025` | 0.84 | yes | ✅ |
| MORAL_HAZARD | name_of_life_assured | H | `Ashok` | `Asbok` | 0.79 | yes | ❌ |
| MORAL_HAZARD | nominee_relationship | H | `Nephew` | `of nominee Klepheu` | 0.38 | yes | ❌ |
| MORAL_HAZARD | date | H | `26/04/2026` | `Dommryry Places .` | 0.22 | yes | ❌ |
| MORAL_HAZARD | place | H | `West Bihar` | `West Rams` | 0.65 | yes | ❌ |
| MULTIPLE_POLICIES_CONSENT | proposer_name | H | `Ashok` | `Ashok` | 0.91 | no | ✅ |
| MULTIPLE_POLICIES_CONSENT | reason_for_multiple_policies | H | `Financial Planning` | `Financial Planning` | 0.83 | no | ✅ |
| MULTIPLE_POLICIES_CONSENT | date | H | `26/04/2026` | `26/04/2026` | 0.77 | yes | ✅ |
| MULTIPLE_POLICIES_CONSENT | place | H | `West Bihar` | `West Bihar` | 0.76 | yes | ✅ |
| SUITABILITY_PROFILER | application_number | H | `1500137601025` | `150013161025` | 0.77 | yes | ❌ |
| SUITABILITY_PROFILER | name_of_life_assured | H | `Ashok` | `Ashok` | 0.81 | no | ✅ |
| SUITABILITY_PROFILER | name_of_agent_sp | H | `Ramesh Kumar` | `Ramesh Kumar` | 0.90 | no | ✅ |
| SUITABILITY_PROFILER | date | H | `26/04/2026` | `9/424` | 0.19 | yes | ❌ |
| SUITABILITY_PROFILER | place | H | `West Bihar` | `most extra` | 0.62 | yes | ❌ |

**Mismatches (17)**: NACH_MANDATE.bank_account_number, NACH_MANDATE.ifsc_code, NACH_MANDATE.amount_figures, FATCA_ANNEXURE.policy_number, FATCA_ANNEXURE.fathers_name, FATCA_ANNEXURE.place_of_birth, FATCA_ANNEXURE.nationality, BENEFIT_ILLUSTRATION.application_number, BENEFIT_ILLUSTRATION.date, BENEFIT_ILLUSTRATION.place, MORAL_HAZARD.name_of_life_assured, MORAL_HAZARD.nominee_relationship, MORAL_HAZARD.date, MORAL_HAZARD.place, SUITABILITY_PROFILER.application_number, SUITABILITY_PROFILER.date, SUITABILITY_PROFILER.place
