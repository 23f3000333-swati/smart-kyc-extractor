"""Field normalisation, format-aware OCR corrections and validators.

Two public entry points:
  normalize(kind, raw)            -> (value, corrections)
  validate(kind, value, context)  -> (passed, messages)

`passed` is True / False, or None when the kind has no rule.
Corrections are only applied where the *format* demands a digit or a letter at
that position (e.g. 'O' in a digit slot becomes '0'). Every correction is
recorded so it can be shown to the reviewer and cost confidence.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from difflib import SequenceMatcher

# Characters OCR commonly confuses, keyed by what the slot requires.
TO_DIGIT = {"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1",
            "i": "1", "S": "5", "s": "5", "Z": "2", "z": "2", "B": "8"}
TO_LETTER = {"0": "O", "1": "I", "5": "S", "2": "Z", "8": "B"}

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
AADHAAR_RE = re.compile(r"^[0-9]{12}$")
ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")
PASSPORT_RE = re.compile(r"^[A-Z][0-9]{7}$")
DL_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[0-9]{4}[0-9]{7}$")
APPNO_RE = re.compile(r"^[0-9]{8,16}$")

# IFSC bank prefix -> canonical bank name (subset of RBI list, enough for the
# common banks; unknown prefixes simply skip the cross-check).
IFSC_BANKS = {
    "SBIN": "State Bank of India", "HDFC": "HDFC Bank", "ICIC": "ICICI Bank",
    "UTIB": "Axis Bank", "PUNB": "Punjab National Bank", "BARB": "Bank of Baroda",
    "CNRB": "Canara Bank", "UBIN": "Union Bank of India", "KKBK": "Kotak Mahindra Bank",
    "IDIB": "Indian Bank", "BKID": "Bank of India", "CBIN": "Central Bank of India",
    "IOBA": "Indian Overseas Bank", "YESB": "Yes Bank", "INDB": "IndusInd Bank",
    "MAHB": "Bank of Maharashtra", "UCBA": "UCO Bank", "PSIB": "Punjab & Sind Bank",
    "IDFB": "IDFC First Bank", "FDRL": "Federal Bank",
}
KNOWN_BANKS = sorted(set(IFSC_BANKS.values()))

RELATIONS = {"father", "mother", "spouse", "wife", "husband", "son", "daughter",
             "brother", "sister", "nephew", "niece", "uncle", "aunt", "grandson",
             "granddaughter", "grandfather", "grandmother", "cousin", "friend",
             "son-in-law", "daughter-in-law"}
NATIONALITIES = {"INDIAN", "NRI", "AMERICAN", "BRITISH", "NEPALESE", "CANADIAN"}

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
         "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000,
          "crore": 10_000_000, "crores": 10_000_000}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def similarity(a: str, b: str) -> float:
    """Case/space-insensitive string similarity in [0, 1]."""
    a = re.sub(r"[^a-z0-9<]", "", (a or "").lower())
    b = re.sub(r"[^a-z0-9<]", "", (b or "").lower())
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_substring(needle: str, hay: str) -> float:
    """Best similarity of `needle` against any same-length window of `hay`."""
    n = re.sub(r"[^a-z0-9]", "", needle.lower())
    h = re.sub(r"[^a-z0-9]", "", hay.lower())
    if not n or not h:
        return 0.0
    if len(h) <= len(n):
        return SequenceMatcher(None, n, h).ratio()
    return max(SequenceMatcher(None, n, h[i:i + len(n)]).ratio()
               for i in range(len(h) - len(n) + 1))


def _fix_slots(text: str, pattern: str) -> tuple[str, list[str]]:
    """Force each char of `text` into its slot type.

    pattern: one char per position, 'D' = digit slot, 'L' = letter slot,
    'X' = anything. Returns (fixed_text, corrections).
    """
    out, corrections = [], []
    for i, (ch, slot) in enumerate(zip(text, pattern)):
        new = ch
        if slot == "D" and not ch.isdigit():
            new = TO_DIGIT.get(ch, ch)
        elif slot == "L" and not ch.isalpha():
            new = TO_LETTER.get(ch, ch)
        if new != ch:
            corrections.append(f"pos {i}: '{ch}'->'{new}'")
        out.append(new)
    return "".join(out) + text[len(pattern):], corrections


def _digits_only(raw: str) -> tuple[str, list[str]]:
    """Keep only digits, converting look-alike letters (format = all digits)."""
    compact = re.sub(r"[\s,./\-]", "", raw)
    fixed, corr = _fix_slots(compact, "D" * len(compact))
    return re.sub(r"\D", "", fixed), corr


def strip_relation_prefix(raw: str) -> str:
    """'S/O KUMAR' -> 'KUMAR' (also D/O, W/O, C/O, 'Son of')."""
    return re.sub(r"^\s*(?:[SDWC]\s*[/\\|.]?\s*[O0]|son of|daughter of|wife of)\b[\s:.,]*",
                  "", raw, flags=re.I).strip(" ,.:")


def words_to_number(text: str) -> int | None:
    """'Fifty thousand Only' -> 50000 (Indian scale words supported)."""
    total, current, seen = 0, 0, False
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in UNITS:
            current += UNITS[w]
            seen = True
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w in SCALES:
            total += max(current, 1) * SCALES[w]
            current, seen = 0, True
    return total + current if seen else None


# --------------------------------------------------------------------------- #
# Checksums
# --------------------------------------------------------------------------- #
_VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
               [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
               [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
               [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
               [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
               [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
               [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
               [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(number: str) -> bool:
    """True if the digit string carries a valid Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def mrz_check_digit(field: str) -> int:
    """ICAO 9303 check digit: weights 7,3,1; A=10..Z=35; '<'=0."""
    total = 0
    for i, ch in enumerate(field):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch.upper()) - 55
        else:
            v = 0
        total += v * (7, 3, 1)[i % 3]
    return total % 10


def mrz_line2_checks(line: str) -> list[str]:
    """Return a list of failed checks for a TD3 (passport) MRZ line 2."""
    problems = []
    if len(line) < 28:
        return [f"too short ({len(line)} chars)"]
    if len(line) != 44:
        problems.append(f"length {len(line)} != 44 (non-standard TD3 line)")
    parts = {"document number": (line[0:9], line[9]),
             "date of birth": (line[13:19], line[19]),
             "date of expiry": (line[21:27], line[27])}
    for name, (data, check) in parts.items():
        expected = mrz_check_digit(data)
        if not check.isdigit() or int(check) != expected:
            problems.append(f"{name} check digit '{check}' != computed {expected}")
    if len(line) != 44:
        return problems  # composite position is undefined on a non-standard line
    composite = line[0:10] + line[13:20] + line[21:43]
    if line[43].isdigit() and int(line[43]) != mrz_check_digit(composite):
        problems.append(f"composite check digit '{line[43]}' != computed "
                        f"{mrz_check_digit(composite)}")
    return problems


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def normalize_date(raw: str) -> tuple[str, list[str]]:
    """Parse a hand/printed date into DD/MM/YYYY.

    Accepts '/', '-', '.', or spaces as separators, or an 8/6-digit run.
    Two-digit years: <= current yy -> 20yy, else 19yy (26 -> 2026, 79 -> 1979).
    """
    corrections: list[str] = []
    text = raw.strip()
    # Look-alike letters only inside the date (digit slots).
    fixed = "".join(TO_DIGIT.get(c, c) if c.isalpha() else c for c in text)
    if fixed != text:
        corrections.append(f"letters->digits '{text}'->'{fixed}'")
    m = re.search(r"(\d{1,2})\s*[/\-.\s]\s*(\d{1,2})\s*[/\-.\s]\s*(\d{4}|\d{2})(?!\d)", fixed)
    run = re.sub(r"\D", "", fixed)
    if m:
        d, mth, y = m.groups()
    elif len(run) == 10 and run[2] in "17" and run[5] in "17":
        # Handwritten '/' read as '1' or '7': DD?MM?YYYY with slash slots.
        d, mth, y = run[:2], run[3:5], run[6:]
        corrections.append(f"pos 2,5: '{run[2]}','{run[5]}' -> '/' (slash slots)")
    else:
        if len(run) == 8:
            d, mth, y = run[:2], run[2:4], run[4:]
        elif len(run) == 6:
            d, mth, y = run[:2], run[2:4], run[4:]
        else:
            return raw.strip(), corrections
        corrections.append(f"split digit run '{run}'")
    if len(y) == 2:
        yy = int(y)
        y = str(2000 + yy if yy <= date.today().year % 100 else 1900 + yy)
        corrections.append(f"2-digit year -> {y}")
    return f"{int(d):02d}/{int(mth):02d}/{y}", corrections


def parse_date(value: str) -> date | None:
    """DD/MM/YYYY -> date, or None."""
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Normalisation per kind
# --------------------------------------------------------------------------- #
def normalize(kind: str, raw: str) -> tuple[str, list[str]]:
    """Clean an OCR reading for a field kind. Returns (value, corrections).

    Note: "raw" from OCR is never modified in place; the caller keeps it.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", []
    if kind in ("aadhaar", "account", "appno"):
        return _digits_only(raw)
    if kind == "amount":
        # Keep the figure part only (drop currency symbol, '/-', words).
        m = re.search(r"[0-9][0-9OoIlSZB,.\s]*", raw.replace("₹", " "))
        if not m:
            return "", []
        value, corr = _digits_only(m.group(0).split(".")[0])
        return value, corr
    if kind in ("pan", "ifsc", "passport", "dl"):
        compact = re.sub(r"[^A-Za-z0-9|]", "", raw).upper()
        pattern = {"pan": "LLLLLDDDDL", "ifsc": "LLLLD", "passport": "LDDDDDDD",
                   "dl": "LLDD" + "D" * 11}[kind]
        fixed, corr = _fix_slots(compact, pattern)
        return fixed, corr
    if kind == "mrz":
        return re.sub(r"[^A-Z0-9<]", "", raw.upper().replace("«", "<")), []
    if kind == "date":
        return normalize_date(raw)
    if kind == "father":
        return strip_relation_prefix(raw), []
    if kind == "bank":
        # The crop may hold extra text: match each known bank as a fuzzy substring.
        best = max(KNOWN_BANKS, key=lambda b: fuzzy_substring(b, raw))
        score = fuzzy_substring(best, raw)
        if score >= 0.75 and best != raw:
            return best, [f"bank name '{raw}'->'{best}' ({score:.2f})"]
        return raw, []
    if kind in ("name", "place", "relation", "nationality", "address", "choice"):
        value = re.sub(r"\s+", " ", raw).strip(" .,:;-_")
        if kind == "address":  # relation prefix "S/O" is often read "SIO" / "S1O"
            fixed = re.sub(r"^([SDWC])[I1l|\\]([O0])\b", r"\1/O", value)
            if fixed != value:
                return fixed, [f"'{value[:3]}'->'{fixed[:3]}' (relation prefix)"]
        if kind in ("place", "relation", "nationality"):
            value = re.sub(r"[^A-Za-z &]", "", value).strip()
        if kind == "nationality":
            value = value.upper()
        return value, []
    return raw, []


# --------------------------------------------------------------------------- #
# Validation per kind
# --------------------------------------------------------------------------- #
def validate(kind: str, value: str, context: dict | None = None) -> tuple[bool | None, list[str]]:
    """Check a normalised value. context may hold other fields of the document."""
    context = context or {}
    if not value:
        return False, ["empty"]
    v = value
    if kind == "aadhaar":
        if not AADHAAR_RE.match(v):
            return False, ["not 12 digits"]
        msgs = []
        if v[0] in "01":
            msgs.append("Aadhaar cannot start with 0/1 (sample card?)")
        if not verhoeff_ok(v):
            msgs.append("Verhoeff checksum fails (sample card?)")
        # Format is right; checksum failures are reported, not treated as misreads.
        return True, msgs
    if kind == "pan":
        ok = bool(PAN_RE.match(v))
        msgs = [] if ok else ["PAN format ^[A-Z]{5}[0-9]{4}[A-Z]$ fails"]
        if ok and v[3] not in "ABCFGHLJPTK":
            msgs.append(f"4th char '{v[3]}' is not a valid PAN holder type")
        return ok, msgs
    if kind == "ifsc":
        if not IFSC_RE.match(v):
            return False, ["IFSC format ^[A-Z]{4}0[A-Z0-9]{6}$ fails"]
        bank = context.get("bank_name")
        expected = IFSC_BANKS.get(v[:4])
        if bank and expected and similarity(bank, expected) < 0.75:
            return False, [f"IFSC prefix {v[:4]} = {expected}, but bank name is '{bank}'"]
        return True, []
    if kind == "account":
        ok = bool(ACCOUNT_RE.match(v))
        return ok, [] if ok else [f"account number must be 9-18 digits (got {len(v)})"]
    if kind == "passport":
        ok = bool(PASSPORT_RE.match(v))
        return ok, [] if ok else ["passport number format ^[A-Z][0-9]{7}$ fails"]
    if kind == "dl":
        ok = bool(DL_RE.match(v))
        return ok, [] if ok else ["DL format SS RR YYYY NNNNNNN fails"]
    if kind == "mrz":
        problems = mrz_line2_checks(v)
        # Structure must be right (doc no., IND, 6-digit dates, sex); check-digit
        # failures are real-world validity problems -> reported, flagged.
        structure = re.match(r"^[A-Z0-9<]{9}[0-9][A-Z<]{3}[0-9]{7}[MFX<][0-9]{7}", v)
        return bool(structure) and len(v) == 44, problems
    if kind == "appno":
        ok = bool(APPNO_RE.match(v))
        return ok, [] if ok else ["application/policy number must be 8-16 digits"]
    if kind == "amount":
        if not v.isdigit() or int(v) <= 0:
            return False, ["amount is not a positive number"]
        words = context.get("amount_words")
        if words:
            n = words_to_number(words)
            if n is not None and n != int(v):
                return False, [f"amount in words ({n}) != figures ({v})"]
            if n == int(v):
                return True, ["matches amount in words"]
        return True, []
    if kind == "date":
        d = parse_date(v)
        if not d:
            return False, ["not a valid DD/MM/YYYY date"]
        if not 1900 <= d.year <= 2100:
            return False, ["year out of range"]
        return True, []
    if kind in ("name", "father"):
        letters = re.sub(r"[^A-Za-z]", "", v)
        ok = len(letters) >= 2 and len(letters) >= 0.7 * len(v.replace(" ", "").replace(".", ""))
        return ok, [] if ok else ["name contains non-letters"]
    if kind == "place":
        ok = bool(re.fullmatch(r"[A-Za-z][A-Za-z ]{2,}", v))
        return ok, [] if ok else ["place must be letters only"]
    if kind == "nationality":
        ok = v in NATIONALITIES
        return ok, [] if ok else [f"unknown nationality '{v}'"]
    if kind == "relation":
        ok = v.lower() in RELATIONS
        return ok, [] if ok else [f"'{v}' is not a known relationship"]
    if kind == "bank":
        ok = v in KNOWN_BANKS
        return ok, [] if ok else ["bank name not in known-bank list"]
    if kind == "address":
        ok = bool(re.search(r"\b\d{6}\b", v))
        return ok, [] if ok else ["no 6-digit PIN code in address"]
    if kind == "choice":
        allowed = context.get("options") or []
        ok = not allowed or v in allowed
        return ok, [] if ok else ["not one of the printed options"]
    return None, []


def validate_document(fields: dict[str, str]) -> dict[str, list[str]]:
    """Document-level rules (e.g. expiry after issue). Returns {field: [problems]}."""
    problems: dict[str, list[str]] = {}
    pairs = [("date_of_issue", "valid_till"), ("date_of_birth", "date_of_expiry")]
    for start, end in pairs:
        a, b = parse_date(fields.get(start, "")), parse_date(fields.get(end, ""))
        if a and b and b <= a:
            problems.setdefault(end, []).append(f"{end} is not after {start}")
    return problems
