"""Offline field extraction.

Strategy per field (chosen by FieldSpec.method in config.py):
  anchor   find the printed label in the full-page EasyOCR boxes, build a search
           window to its right/below, then read the value:
             printed     -> text of full-page OCR boxes inside the window
             handwritten -> crop the window (tightened to detected ink) and read
                            it with TrOCR AND EasyOCR on both image versions
  regex    printed ID numbers matched by format anywhere on the page
  mrz      bottom MRZ line re-read with a restricted alphabet, then parsed
  checkbox the option whose box has the most ink is the selected one

Every reading is kept in `raw_readings`; the value is chosen by voting over
normalised readings, preferring those that pass the validator.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

import cv2
import numpy as np

import config
from config import FieldSpec
from src import ocr
from src.preprocess import Page
from src.validate import normalize, similarity, validate

log = logging.getLogger(__name__)

# Character allowlists for EasyOCR on handwritten crops of code-like fields.
DIGITS = "0123456789"
UPPER_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
ALLOWLIST = {"account": DIGITS, "appno": DIGITS, "amount": DIGITS + ",",
             "date": DIGITS + "/-.", "ifsc": UPPER_ALNUM, "pan": UPPER_ALNUM}

# Regexes for printed ID numbers (method="regex"); applied to row text.
ID_PATTERNS = {
    "aadhaar": r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)",
    "pan": r"(?<![A-Z])[A-Z]{5}\s?\d{4}\s?[A-Z](?![A-Z])",
    "dl": r"(?<![A-Z])[A-Z]{2}\s?\d{2}\s?\d{4}\s?\d{7}(?!\d)",
    "passport": r"(?<![A-Z0-9])[A-Z]\d{7}(?![0-9])",
}


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9&/ ]", "", text.lower()).strip()


MAX_LABEL_START = 4  # a label may follow a short prefix like "a) " or "2) "


def find_labels(boxes: list[dict], phrase: str, threshold: float = 0.8,
                anywhere: bool = False) -> list[dict]:
    """Find printed label occurrences, fuzzily, inside OCR boxes.

    A label must START its box (after a short "a) " style prefix), otherwise
    "Policy No" would match inside "Proposer/Policyholder" sentences; pass
    anywhere=True for stop labels, which may sit at the end of a value box.

    Returns dicts {box, start_x, end_x, trailing, score}: `start_x`/`end_x`
    are where the label text starts/ends inside the box (the box may also
    contain the value), `trailing` is any text after the label in the box.
    """
    target = _norm(phrase)
    n = len(target)
    hits = []
    for b in boxes:
        text = b["text"]
        low = _norm(text)
        if len(low) < max(2, n - 3):
            continue
        if n <= 4 and len(low) > n + 10 and not anywhere:
            continue  # a short label ("IFSC") lives in a short box, not a sentence
        best, best_start, best_end = 0.0, 0, 0
        last_start = len(low) - n + 1 if anywhere else min(MAX_LABEL_START + 1, len(low) - n + 2)
        for start in range(0, max(1, last_start)):
            for size in (n - 1, n, n + 1):
                window = low[start:start + size]
                if not window:
                    continue
                r = similarity(window, target)
                if r > best:
                    best, best_start, best_end = r, start, start + size
        # Short labels ("IFSC", "Date") tolerate one wrong char (75%) but no less.
        if best >= (min(threshold, 0.75) if n <= 4 else threshold):
            x0, y0, x1, y1 = b["box"]
            scale = (x1 - x0) / max(1, len(low))
            hits.append({"box": b["box"], "start_x": int(x0 + best_start * scale),
                         "end_x": int(x0 + best_end * scale),
                         "trailing": text[int(best_end / max(1, len(low)) * len(text)):].strip(" :.-_"),
                         "score": best, "text": text})
    # The same box can match several phrasings of one label: keep it once.
    unique: dict[tuple, dict] = {}
    for h in hits:
        key = tuple(h["box"])
        if key not in unique or h["score"] > unique[key]["score"]:
            unique[key] = h
    return list(unique.values())


def search_window(label: dict, spec: FieldSpec, direction: str, page_w: int,
                  page_h: int, stops: list[dict]) -> tuple[int, int, int, int]:
    """Region where the value of `label` should be."""
    x0, y0, x1, y1 = label["box"]
    h = max(12, label.get("line_h", y1 - y0))  # window size in single-line heights
    if direction == "left":  # value sits left of this label (FieldSpec.left_of)
        wx1 = label["start_x"] - 2
        wx0 = max(0, wx1 - int(spec.width * page_w))
        cy = (y0 + y1) / 2
        wy0, wy1 = int(cy - 0.6 * spec.height * h), int(cy + 0.4 * spec.height * h)
    elif direction in ("right", "right_down"):
        wx0 = int(spec.x_from * page_w) if spec.x_from else label["end_x"] + 2
        wx1 = min(page_w, wx0 + int(spec.width * page_w))
        cy = (y0 + y1) / 2
        if direction == "right_down":  # multi-line value starting on the label row
            wy0, wy1 = int(y0 - 0.3 * h), int(y0 + spec.height * h)
        else:
            # Handwriting tends to sit on/above the printed line: bias upwards.
            wy0 = int(cy - 0.6 * spec.height * h)
            wy1 = int(cy + 0.4 * spec.height * h)
        for s in stops:  # clip at the first stop label on the same row
            sx = s["start_x"]
            sy0, sy1 = s["box"][1], s["box"][3]
            if sx > wx0 + 5 and sy0 < wy1 and sy1 > wy0:
                wx1 = min(wx1, sx - 2)
    else:  # below
        # Printed values are often left-aligned under a bilingual label whose
        # English part starts mid-line ("पिता का नाम / Father's Name"): extend left.
        wx0 = max(0, x0 - (0 if spec.handwritten else int(0.15 * page_w)))
        wx1 = min(page_w, x0 + int(spec.width * page_w))
        wy0 = y1 - int(0.2 * h)
        wy1 = y1 + int(spec.height * h)
    return (max(0, wx0), max(0, wy0), min(page_w, wx1), min(page_h, wy1))


def extend_label_block(label: dict, boxes: list[dict]) -> dict:
    """Grow a label downwards over its continuation lines (multi-line table
    headers such as "Tax Identification Number (TIN)/ Functional equivalent"),
    so a 'below' window starts under the whole header, not inside it."""
    x0, y0, x1, y1 = label["box"]
    h = y1 - y0
    grown = True
    while grown:
        grown = False
        for b in boxes:
            bx0, by0, bx1, by1 = b["box"]
            overlaps = bx0 < x1 and bx1 > x0
            if overlaps and y1 - 0.3 * h <= by0 <= y1 + 0.5 * h and by1 > y1:
                y1, grown = by1, True
    return dict(label, box=[x0, y0, x1, y1], line_h=h)  # keep one-line height


def boxes_in(boxes: list[dict], window: tuple[int, int, int, int],
             exclude: list[int] | None = None) -> list[dict]:
    """OCR boxes whose centre lies inside the window."""
    wx0, wy0, wx1, wy1 = window
    out = []
    for b in boxes:
        if exclude and b["box"] == exclude:
            continue
        x0, y0, x1, y1 = b["box"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if wx0 <= cx <= wx1 and wy0 <= cy <= wy1:
            out.append(b)
    return sorted(out, key=lambda b: (b["box"][1] // 20, b["box"][0]))


INK_MAX_GRAY = 150  # pen/print is darker than this; grey table shading is not


def ink_mask(gray: np.ndarray) -> np.ndarray:
    """Binary mask of ink: dark by Otsu AND darker than INK_MAX_GRAY."""
    t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ((gray < min(t, INK_MAX_GRAY)) * 255).astype(np.uint8)


def horizontal_lines(binary: np.ndarray) -> np.ndarray:
    """Horizontal strokes longer than a third of the crop (ruled lines)."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, binary.shape[1] // 3), 1))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)


def line_mask(binary: np.ndarray, v_frac: float = 0.5) -> np.ndarray:
    """Long horizontal / vertical strokes = ruled lines, box and cell borders."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(binary.shape[0] * v_frac))))
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)
    return cv2.bitwise_or(horizontal_lines(binary), vert)


def clean_crop(gray: np.ndarray, pad: int = 10, boxed: bool = False) -> np.ndarray:
    """Whiten ruled lines and add a white margin - what the OCR engines see.

    Vertical lines must span 90% of the crop height. Inside a boxed field
    they are cell borders and are removed everywhere; otherwise only near the
    crop edges (box ends), because tall strokes like 'd', 'l', '1' would
    otherwise be erased too."""
    if gray.size == 0:
        return gray
    ink = ink_mask(gray)
    lines = line_mask(ink, v_frac=0.9)
    if not boxed:  # keep only horizontal lines away from the crop edges
        w = gray.shape[1]
        edge = max(4, int(0.06 * w))
        lines[:, edge:w - edge] = horizontal_lines(ink)[:, edge:w - edge]
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
    out = gray.copy()
    out[lines > 0] = 255
    return cv2.copyMakeBorder(out, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def ink_bbox(gray: np.ndarray, window: tuple[int, int, int, int],
             pad: int = 6) -> tuple[int, int, int, int] | None:
    """Tighten a window to the dark (ink) pixels inside it, ignoring long
    ruled lines (form underlines / table borders). None if the window is blank."""
    wx0, wy0, wx1, wy1 = window
    crop = gray[wy0:wy1, wx0:wx1]
    if crop.size == 0:
        return None
    binary = ink_mask(crop)
    binary = cv2.subtract(binary, line_mask(binary))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if np.count_nonzero(binary) < 30:
        return None
    y_lo, y_hi = heaviest_band(binary)
    ys, xs = np.nonzero(binary[y_lo:y_hi])
    if len(xs) < 30:
        return None
    x0, x1 = np.percentile(xs, [1, 99]).astype(int)
    # Re-include the band's own thin ascenders/descenders (a few rows each side).
    grow = max(3, (y_hi - y_lo) // 4)
    y0, y1 = max(0, y_lo - grow), min(binary.shape[0], y_hi + grow)
    return (max(0, wx0 + x0 - pad), max(0, wy0 + y0 - pad),
            min(gray.shape[1], wx0 + x1 + pad), min(gray.shape[0], wy0 + y1 + pad))


def heaviest_band(binary: np.ndarray) -> tuple[int, int]:
    """Rows [lo, hi) of the horizontal text band holding the most ink.

    A window can contain a printed header line plus the handwritten value;
    pen strokes are larger and denser than small print, so the band with the
    most ink is (almost always) the handwriting. Small gaps are bridged so
    descenders / dots stay attached.
    """
    profile = (binary > 0).sum(axis=1)
    # Rows with only a few ink pixels (ascenders/descenders reaching into
    # the next line) do not join two lines into one band.
    on = profile >= max(2, 0.08 * profile.max())
    bands, start = [], None
    for y, flag in enumerate(on):
        if flag and start is None:
            start = y
        elif not flag and start is not None:
            bands.append([start, y])
            start = None
    if start is not None:
        bands.append([start, len(on)])
    if not bands:
        return 0, binary.shape[0]
    gap = 2
    merged = [bands[0]]
    for b in bands[1:]:
        if b[0] - merged[-1][1] <= gap:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    # Bands cut by the window edge belong to neighbouring lines (e.g. the
    # rest of a header above); prefer bands fully inside the window.
    inside = [b for b in merged if b[0] > 1 and b[1] < binary.shape[0] - 1
              and profile[b[0]:b[1]].sum() >= 60]
    lo, hi = max(inside or merged, key=lambda b: profile[b[0]:b[1]].sum())
    return lo, hi


def crop(gray: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = box
    return gray[y0:y1, x0:x1]


# --------------------------------------------------------------------------- #
# Choosing a value from several readings
# --------------------------------------------------------------------------- #
SHAPE_CHARS = {"date": DIGITS + "/", "appno": DIGITS, "account": DIGITS, "amount": DIGITS,
               "ifsc": UPPER_ALNUM, "pan": UPPER_ALNUM}


def shape_score(kind: str, value: str) -> float:
    """Share of characters allowed for the kind (1.0 for free-text kinds).
    When nothing validates, '2610 4/2026' beats TrOCR's 'colourful'."""
    allowed = SHAPE_CHARS.get(kind)
    if not allowed or not value:
        return 1.0 if value else 0.0
    return sum(ch in allowed for ch in value) / len(value)


def choose_value(spec: FieldSpec, readings: list[dict], context: dict) -> dict:
    """Vote over normalised readings.

    Ranking key: passes validator > number of readings that agree >
    summed OCR confidence. Returns the field result (without final confidence).
    """
    candidates: dict[str, dict] = {}
    for r in readings:
        value, corrections = normalize(spec.kind, r["text"])
        r["normalized"] = value
        if not value:
            continue
        c = candidates.setdefault(value, {"value": value, "raw": r["text"], "votes": 0,
                                          "conf_sum": 0.0, "best_conf": 0.0,
                                          "corrections": corrections})
        c["votes"] += 1
        c["conf_sum"] += r["conf"]
        if r["conf"] > c["best_conf"]:
            c["best_conf"], c["raw"], c["corrections"] = r["conf"], r["text"], corrections
    result = {"value": "", "raw": "", "handwritten": spec.handwritten, "raw_readings": readings,
              "corrections": [], "read_conf": 0.0, "two_pass": 0.0,
              "validator": {"passed": False, "messages": ["no reading"]}}
    if not candidates:
        return result
    for c in candidates.values():
        c["passed"], c["messages"] = validate(spec.kind, c["value"], context)
    best = max(candidates.values(),
               key=lambda c: (c["passed"] is not False, shape_score(spec.kind, c["value"]) >= 0.8,
                              c["votes"], c["conf_sum"]))
    others = [r for r in readings if r.get("normalized") is not None]
    agreement = [similarity(r.get("normalized", ""), best["value"]) for r in others]
    # Agreement = how much the *other* readings support the chosen value.
    if len(agreement) > 1:
        two_pass = (sum(agreement) - 1.0) / (len(agreement) - 1)
    else:
        two_pass = 0.0
    result.update(value=best["value"], raw=best["raw"], corrections=best["corrections"],
                  read_conf=round(best["best_conf"], 3), two_pass=round(max(0.0, two_pass), 3),
                  validator={"passed": best["passed"], "messages": best["messages"]})
    return result


# --------------------------------------------------------------------------- #
# Reading strategies
# --------------------------------------------------------------------------- #
BOXED_KINDS = {"account", "ifsc"}  # written one character per printed cell


def cell_spans(gray: np.ndarray) -> list[tuple[int, int]]:
    """x-ranges of the cells of a boxed field, from its vertical borders.
    Returns [] unless at least 4 roughly evenly spaced borders are found."""
    binary = ink_mask(gray)
    h = gray.shape[0]
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(0.6 * h)))))
    cols = np.nonzero(vert.max(axis=0))[0]
    if len(cols) == 0:
        return []
    xs, group = [], [cols[0]]
    for c in cols[1:]:  # cluster adjacent columns into one border
        if c - group[-1] <= 2:
            group.append(c)
        else:
            xs.append(int(np.mean(group)))
            group = [c]
    xs.append(int(np.mean(group)))
    if len(xs) < 4:
        return []
    gaps = np.diff(xs)
    med = float(np.median(gaps))
    # Keep spans that look like a cell (similar width to the median cell).
    return [(a, b) for a, b in zip(xs, xs[1:]) if 0.6 * med <= b - a <= 1.6 * med]


def read_cells(gray: np.ndarray, kind: str) -> tuple[str, float] | None:
    """Read a boxed field cell by cell: one character per cell, EasyOCR
    recognition (no detection) with the field's alphabet. Stops at the
    first empty cell after the value."""
    # Only look at the main row of cells (the crop may clip a neighbour row).
    ink = cv2.subtract(ink_mask(gray), horizontal_lines(ink_mask(gray)))
    lo, hi = heaviest_band(ink)
    gray = gray[max(0, lo - 3):hi + 3]
    spans = cell_spans(gray)
    if len(spans) < 4:
        return None
    reader = ocr.easyocr_reader()
    chars, confs = [], []
    for a, b in spans:
        cell = gray[:, a + 2:b - 1]
        mask = cv2.subtract(ink_mask(cell), line_mask(ink_mask(cell), v_frac=0.6))
        if mask.mean() / 255 < 0.03:  # blank cell
            if chars:
                break
            continue
        res = reader.recognize(clean_crop(cell, pad=6, boxed=True), allowlist=ALLOWLIST.get(kind),
                               detail=1)
        text = "".join(r[1] for r in res).strip()
        chars.append(text[:1] if text else "?")
        confs.append(float(res[0][2]) if res and text else 0.0)
    if not chars:
        return None
    return "".join(chars), float(np.mean(confs))


def read_handwritten(page: Page, window: tuple[int, int, int, int],
                     page_boxes: list[dict], spec: FieldSpec) -> list[dict]:
    """TrOCR + EasyOCR on the cleaned window crop, for both image versions
    (+ cell-by-cell reading for boxed fields)."""
    readings = []
    tight = ink_bbox(page.enhanced, window)
    if tight is None:
        return readings
    allow = ALLOWLIST.get(spec.kind)
    for version in ("original", "enhanced"):
        raw = crop(getattr(page, version), tight)
        img = clean_crop(raw, boxed=spec.kind in BOXED_KINDS)
        base = {"version": version, "crop": list(tight)}
        text, conf = ocr.trocr_crop(img)
        readings.append(dict(base, engine="trocr", text=text, conf=round(conf, 3)))
        text, conf = ocr.easyocr_crop(img, allowlist=allow)
        readings.append(dict(base, engine="easyocr_crop", text=text, conf=round(conf, 3)))
        if spec.kind in BOXED_KINDS:
            cells = read_cells(raw, spec.kind)
            if cells:
                readings.append(dict(base, engine="easyocr_cells", text=cells[0],
                                     conf=round(cells[1], 3)))
    return readings


def first_row(boxes: list[dict]) -> list[dict]:
    """Boxes on the top-most text row (value directly under / beside a label)."""
    top = min(boxes, key=lambda b: b["box"][1])
    h = top["box"][3] - top["box"][1]
    cy = (top["box"][1] + top["box"][3]) / 2
    return [b for b in boxes if abs((b["box"][1] + b["box"][3]) / 2 - cy) < 0.6 * h]


def read_printed(window: tuple[int, int, int, int], ocr_pages: dict[str, list[dict]],
                 label_box: list[int], multiline: bool = False) -> list[dict]:
    """Join the full-page OCR boxes inside the window, per image version."""
    readings = []
    for version, boxes in ocr_pages.items():
        inside = boxes_in(boxes, window, exclude=label_box)
        if inside and not multiline:
            inside = sorted(first_row(inside), key=lambda b: b["box"][0])
        if inside:
            text = " ".join(b["text"] for b in inside)
            conf = sum(b["conf"] for b in inside) / len(inside)
            readings.append({"engine": "easyocr_page", "version": version, "text": text,
                             "conf": round(conf, 3)})
    return readings


def extract_anchor(page: Page, ocr_pages: dict[str, list[dict]], spec: FieldSpec,
                   context: dict) -> dict:
    """Label-anchored extraction; tries every label occurrence, keeps the best."""
    boxes = ocr_pages["enhanced"]
    h, w = page.enhanced.shape[:2]
    stops = [s for p in spec.stop for s in find_labels(boxes, p, anywhere=True)]
    labels = [lab for p in spec.labels for lab in find_labels(boxes, p)]
    labels += [dict(lab, left=True) for p in spec.left_of for lab in find_labels(boxes, p)]
    if not labels:
        res = choose_value(spec, [], context)
        res["validator"]["messages"] = [f"label {spec.labels + spec.left_of} not found"]
        return res
    best = None
    for label in labels:
        if label.get("left"):
            directions = ["left"]
        elif spec.direction == "right_or_below":
            directions = ["right", "below"]
        else:
            directions = [spec.direction]
        for direction in directions:
            # Multi-line headers only occur above handwritten table cells; for
            # printed fields the line below the label IS the value.
            grow = direction == "below" and spec.handwritten
            anchor = extend_label_block(label, boxes) if grow else label
            window = search_window(anchor, spec, direction, w, h, stops)
            if spec.handwritten:
                readings = read_handwritten(page, window, boxes, spec)
            else:
                readings = read_printed(window, ocr_pages, label["box"],
                                        multiline=spec.kind == "address")
            if label["trailing"] and len(label["trailing"]) > 1 and direction == "right":
                readings.append({"engine": "easyocr_label_box", "version": "enhanced",
                                 "text": label["trailing"], "conf": 0.5})
            if not readings:
                continue
            res = choose_value(spec, readings, context)
            res["window"] = list(window)
            score = (res["validator"]["passed"] is not False, label["score"] >= 0.9,
                     res["read_conf"] + res["two_pass"])
            if best is None or score > best[0]:
                best = (score, res)
    return best[1] if best else choose_value(spec, [], context)


def _rows(boxes: list[dict]) -> list[str]:
    """Group boxes into text rows (by vertical centre) for regex scanning."""
    rows: dict[int, list[dict]] = defaultdict(list)
    for b in boxes:
        cy = (b["box"][1] + b["box"][3]) // 2
        rows[cy // 25].append(b)
    out = []
    for _, row in sorted(rows.items()):
        out.append(" ".join(b["text"] for b in sorted(row, key=lambda b: b["box"][0])))
    return out + [b["text"] for b in boxes]


def extract_regex(ocr_pages: dict[str, list[dict]], spec: FieldSpec, context: dict) -> dict:
    """Printed ID number found by its format anywhere on the page."""
    pattern = re.compile(ID_PATTERNS[spec.kind])
    readings, seen = [], set()
    for version, boxes in ocr_pages.items():
        confs = {b["text"]: b["conf"] for b in boxes}
        for row in _rows(boxes):
            for m in pattern.finditer(row.upper()):
                key = (version, m.group(0), row)
                if key in seen:
                    continue
                seen.add(key)
                conf = max((c for t, c in confs.items() if m.group(0)[:4] in t.upper()), default=0.5)
                readings.append({"engine": "easyocr_page", "version": version,
                                 "text": m.group(0), "conf": round(conf, 3)})
    return choose_value(spec, readings, context)


MRZ_ALLOW = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"


def count_glyphs(gray_line: np.ndarray) -> int:
    """Count characters on an MRZ line via connected components.

    MRZ uses a monospace OCR-B font, so every character (including each '<')
    is one separate blob. OCR engines often merge or drop repeated '<'; the
    blob count tells us how many there really are.
    """
    _, binary = cv2.threshold(gray_line, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary)
    min_h = 0.3 * gray_line.shape[0]
    spans = sorted((s[0], s[0] + s[2]) for s in stats[1:] if s[3] >= min_h * 0.5 and s[4] > 15)
    merged: list[list[int]] = []
    for x0, x1 in spans:  # parts of one glyph overlap horizontally
        if merged and x0 < merged[-1][1] - 2:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return len(merged)


def align_mrz_fillers(line: str, glyphs: int) -> tuple[str, list[str]]:
    """Make the '<' filler run match the counted number of glyphs.

    Only the run of fillers after the 28 fixed-position data characters is
    adjusted; data characters are never invented.
    """
    m = re.match(r"^(.{28})(<+)(.*)$", line)
    if not m or glyphs <= 28 or len(line) == glyphs:
        return line, []
    head, run, tail = m.groups()
    new_run = glyphs - 28 - len(tail)
    if new_run <= 0:
        return line, []
    return head + "<" * new_run + tail, [f"filler run {len(run)} -> {new_run} '<' "
                                         f"(counted {glyphs} glyphs on the line)"]


def extract_mrz(page: Page, ocr_pages: dict[str, list[dict]], spec: FieldSpec,
                context: dict) -> dict:
    """MRZ line 2: the lowest long text line on the page, re-read with a
    restricted alphabet from both image versions."""
    h, w = page.enhanced.shape[:2]
    boxes = [b for b in ocr_pages["enhanced"] if b["box"][1] > 0.7 * h
             and (b["box"][2] - b["box"][0]) > 0.4 * w]
    readings = []
    if boxes:
        line_box = max(boxes, key=lambda b: b["box"][1])
        ly0, ly1 = line_box["box"][1], line_box["box"][3]
        # EasyOCR often splits the line (e.g. trailing check digits): use the
        # union of every box on the same text line.
        same_line = [b for b in ocr_pages["enhanced"]
                     if b["box"][1] < ly1 and b["box"][3] > ly0]
        x0 = min(b["box"][0] for b in same_line)
        x1 = max(b["box"][2] for b in same_line)
        y0 = min(b["box"][1] for b in same_line)
        y1 = max(b["box"][3] for b in same_line)
        line_box = {"text": "".join(b["text"] for b in sorted(same_line, key=lambda b: b["box"][0])),
                    "conf": min(b["conf"] for b in same_line), "box": [x0, y0, x1, y1]}
        pad = (y1 - y0) // 3
        region = (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))
        glyphs = count_glyphs(crop(page.original, region))
        for version in ("original", "enhanced"):
            text, conf = ocr.easyocr_crop(crop(getattr(page, version), region), allowlist=MRZ_ALLOW)
            text = text.replace(" ", "")
            fixed, corr = align_mrz_fillers(text, glyphs)
            readings.append({"engine": "easyocr_crop", "version": version, "text": fixed,
                             "conf": round(conf, 3), "pre_fix": text, "fix": corr,
                             "glyphs": glyphs})
        page_text = re.sub(r"[^A-Z0-9<]", "", line_box["text"].upper().replace("«", "<"))
        fixed, corr = align_mrz_fillers(page_text, glyphs)
        readings.append({"engine": "easyocr_page", "version": "enhanced", "text": fixed,
                         "conf": round(line_box["conf"], 3), "pre_fix": page_text, "fix": corr})
    res = choose_value(spec, readings, context)
    fixes = [f for r in readings if r["text"] == res["value"] for f in r.get("fix", [])]
    if fixes:
        res["corrections"] = sorted(set(res["corrections"] + fixes))
    return res


def box_ink(gray: np.ndarray, region: tuple[int, int, int, int]) -> float:
    """Fraction of dark pixels inside a region."""
    c = crop(gray, region)
    if c.size == 0:
        return 0.0
    return float(ink_mask(c).mean() / 255)


def is_struck(gray: np.ndarray, box: list[int]) -> bool:
    """True if a horizontal line runs through the middle of an option label
    (the option was crossed out). Text alone never fills ~80% of a row."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    c = gray[y0 + int(0.2 * h): y1 - int(0.2 * h), x0:x1]
    if c.size == 0:
        return False
    _, binary = cv2.threshold(c, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return float((binary > 0).mean(axis=1).max()) >= 0.8


def option_boxes(boxes: list[dict], spec: FieldSpec) -> list[tuple[str, list[int]]]:
    """Locate each option's OCR box: by fuzzy label match, or - when crossed-
    out labels are unreadable - by left-to-right order in the anchor row."""
    anchors = [a for p in spec.labels for a in find_labels(boxes, p)]
    anchor = anchors[0] if anchors else None
    found = []
    for option in spec.options:
        hits = find_labels(boxes, option, threshold=0.75)
        if anchor:  # options sit on/below the anchor row
            hits = [h_ for h_ in hits if -40 < h_["box"][1] - anchor["box"][1] < 400]
        if hits:
            found.append((option, hits[0]["box"], "label"))
    if len(found) == len(spec.options) or not anchor:
        return found
    ax0, ay0, ax1, ay1 = anchor["box"]
    stops = [s["start_x"] for p in spec.stop for s in find_labels(boxes, p, anywhere=True)
             if s["box"][1] < ay1 and s["box"][3] > ay0 and s["start_x"] > ax1]
    limit = min(stops) if stops else 10 ** 6
    row = sorted((b for b in boxes if b["box"][0] > ax1 and b["box"][2] <= limit
                  and b["box"][1] < ay1 and b["box"][3] > ay0), key=lambda b: b["box"][0])
    if len(row) == len(spec.options):
        return [(o, b["box"], "order") for o, b in zip(spec.options, row)]
    return found


def extract_checkbox(page: Page, ocr_pages: dict[str, list[dict]], spec: FieldSpec,
                     context: dict) -> dict:
    """Pick the ticked option: crossed-out options are excluded, then the
    option whose checkbox area holds the most ink wins."""
    found = option_boxes(ocr_pages["enhanced"], spec)
    readings = []
    # Same-size region for every option so densities are comparable; sized
    # from the median label height (a label box may wrap to two lines).
    s = int(np.median([b[3] - b[1] for _, b, _ in found])) if found else 0
    for version in ("original", "enhanced"):
        gray = getattr(page, version)
        dens, struck = {}, []
        for option, (x0, y0, x1, y1), how in found:
            # The box sits just left of a cleanly read label; when the label
            # was unreadable, EasyOCR's box starts with the checkbox itself.
            # Half a line of headroom catches ticks that rise above the box.
            left = x0 - int(1.6 * s) if how == "label" else x0 - int(0.3 * s)
            region = (max(0, left), max(0, y0 - s // 2), max(1, left + int(1.6 * s)), y0 + s)
            dens[option] = round(box_ink(gray, region), 3)
            if is_struck(gray, [x0, y0, x1, y1]):
                struck.append(option)
        candidates = {o: d for o, d in dens.items() if o not in struck} or dens
        if candidates:
            ranked = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)
            top, second = ranked[0][1], ranked[1][1] if len(ranked) > 1 else 0.0
            margin = (top - second) / top if top > 0 else 0.0
            # Every other option crossed out = an unambiguous choice.
            conf = 0.95 if len(candidates) == 1 and struck else min(1.0, 0.5 + margin)
            readings.append({"engine": "checkbox_density", "version": version,
                             "text": ranked[0][0], "conf": round(conf, 3),
                             "densities": dens, "struck_out": struck})
    ctx = dict(context, options=spec.options)
    res = choose_value(spec, readings, ctx)
    if len(found) < len(spec.options):
        missing = sorted(set(spec.options) - {o for o, _, _ in found})
        res["validator"]["messages"].append(f"option labels not found: {missing}")
        res["validator"]["passed"] = False if not found else res["validator"]["passed"]
    return res


# --------------------------------------------------------------------------- #
# Document entry point
# --------------------------------------------------------------------------- #
def extract_document(doc_type: str, page: Page, ocr_pages: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Extract all fields of one document page.

    Returns (fields, auxiliary). Auxiliary fields are extracted first and
    passed as validator context (e.g. amount in words for the figures).
    """
    specs = config.FIELDS.get(doc_type, [])
    context: dict = {}
    fields, aux = {}, {}
    # aux first, then the bank name before IFSC (IFSC prefix check needs it)
    order = sorted(specs, key=lambda s: (not s.aux, s.kind == "ifsc"))
    for spec in order:
        log.info("  %s.%s", doc_type, spec.name)
        if spec.method == "regex":
            res = extract_regex(ocr_pages, spec, context)
        elif spec.method == "mrz":
            res = extract_mrz(page, ocr_pages, spec, context)
        elif spec.method == "checkbox":
            res = extract_checkbox(page, ocr_pages, spec, context)
        else:
            res = extract_anchor(page, ocr_pages, spec, context)
        res["kind"] = spec.kind
        context[spec.name] = res["value"]
        (aux if spec.aux else fields)[spec.name] = res
    # keep the configured field order in the output
    fields = {s.name: fields[s.name] for s in specs if not s.aux}
    return fields, aux
