"""Document classification by fuzzy anchor-phrase matching on printed OCR text."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import config


def _norm(text: str) -> str:
    """Lowercase, keep letters/digits/'<', collapse spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9< ]", " ", text.lower())).strip()


def fuzzy_contains(text: str, phrase: str, threshold: float = 0.85) -> float:
    """Best similarity of `phrase` against any same-length window of `text`.

    Returns the similarity if >= threshold, else 0. Exact substring = 1.0.
    """
    phrase = _norm(phrase)
    if phrase in text:
        return 1.0
    n, best = len(phrase), 0.0
    # Slide over word starts only: fast and good enough for OCR'd headings.
    for m in re.finditer(r"(?:^| )(\S)", text):
        start = m.start(1)
        window = text[start:start + n]
        best = max(best, SequenceMatcher(None, window, phrase).ratio())
        if best >= 0.99:
            break
    return best if best >= threshold else 0.0


def page_text(boxes: list[dict]) -> str:
    """Normalised full text of a page from OCR boxes (reading order)."""
    ordered = sorted(boxes, key=lambda b: (b["box"][1] // 15, b["box"][0]))
    return _norm(" ".join(b["text"] for b in ordered))


def classify_text(text: str) -> tuple[str, float, dict[str, float]]:
    """Score every type; return (doc_type, confidence, all_scores).

    confidence combines how strong the winner is (score / max possible) and
    the margin over the runner-up, so two close types give low confidence.
    """
    scores: dict[str, float] = {}
    for doc_type, anchors in config.CLASS_ANCHORS.items():
        scores[doc_type] = sum(w * fuzzy_contains(text, p) for p, w in anchors)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < config.MIN_CLASS_SCORE:
        return "OTHER", 0.5, scores
    max_possible = sum(w for _, w in config.CLASS_ANCHORS[best])
    strength = min(1.0, best_score / max(3.0, 0.6 * max_possible))
    margin = (best_score - second) / best_score
    confidence = round(0.5 * strength + 0.5 * margin, 3)
    doc_type = "OTHER" if best.startswith("OTHER") else best
    return doc_type, confidence, scores


def classify_document(page_texts: list[str]) -> tuple[str, float, str]:
    """Classify a (possibly multi-page) file. Returns (type, conf, detail).

    Each page is classified; the most confident in-scope page wins, but if
    any page is a recognised out-of-scope form the whole file is OTHER.
    """
    results = [classify_text(t) for t in page_texts]
    for _, _, scores in results:
        top = max(scores, key=scores.get)
        if top.startswith("OTHER") and scores[top] >= config.MIN_CLASS_SCORE:
            return "OTHER", round(min(1.0, scores[top] / 4), 3), top
    doc_type, conf, scores = max(results, key=lambda r: r[1])
    return doc_type, conf, max(scores, key=scores.get)
