"""OCR engines: EasyOCR (printed text, boxes, handwriting fallback) and
TrOCR (handwritten single-line crops). Models are loaded lazily, once.

All boxes are dicts: {"text": str, "conf": float, "box": [x0, y0, x1, y1]}.
Full-page results are cached as JSON in output/.cache (keyed by file hash),
so re-runs while tuning anchors take seconds instead of minutes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

import config

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def easyocr_reader():
    """Shared EasyOCR reader (CPU)."""
    import easyocr
    log.info("loading EasyOCR %s", config.EASYOCR_LANGS)
    return easyocr.Reader(config.EASYOCR_LANGS, gpu=False, verbose=False)


@lru_cache(maxsize=1)
def trocr_model():
    """Shared TrOCR processor + model (CPU, eval mode)."""
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    log.info("loading %s", config.TROCR_MODEL)
    try:  # use the local cache without any network call when possible
        processor = TrOCRProcessor.from_pretrained(config.TROCR_MODEL, local_files_only=True)
        model = VisionEncoderDecoderModel.from_pretrained(config.TROCR_MODEL, local_files_only=True)
    except OSError:  # first run: download once
        processor = TrOCRProcessor.from_pretrained(config.TROCR_MODEL)
        model = VisionEncoderDecoderModel.from_pretrained(config.TROCR_MODEL)
    model.eval()
    torch.set_num_threads(4)
    return processor, model


def _to_boxes(results) -> list[dict]:
    """Convert EasyOCR output [(poly, text, conf)] to our box dicts."""
    boxes = []
    for poly, text, conf in results:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        boxes.append({"text": text, "conf": float(conf),
                      "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]})
    return boxes


def _cache_path(source: Path, page_index: int, version: str, shape: tuple) -> Path:
    """Cache key = file content hash + page + image variant + image size."""
    digest = hashlib.sha1(source.read_bytes()).hexdigest()[:12]
    size = f"{shape[1]}x{shape[0]}"
    return config.CACHE_DIR / f"{source.stem[:30]}_{digest}_p{page_index}_{version}_{size}.json"


def full_page_ocr(image: np.ndarray, source: Path, page_index: int, version: str) -> list[dict]:
    """EasyOCR over a whole page (cached on disk)."""
    path = _cache_path(source, page_index, version, image.shape)
    if path.exists():
        return json.loads(path.read_text())
    log.info("EasyOCR full page: %s p%d (%s)", source.name, page_index + 1, version)
    boxes = _to_boxes(easyocr_reader().readtext(image, paragraph=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(boxes))
    return boxes


def easyocr_crop(crop: np.ndarray, allowlist: str | None = None) -> tuple[str, float]:
    """Read a crop with EasyOCR; join boxes left-to-right. Returns (text, conf)."""
    if crop.size == 0 or min(crop.shape[:2]) < 8:
        return "", 0.0
    res = easyocr_reader().readtext(crop, paragraph=False, allowlist=allowlist)
    if not res:
        return "", 0.0
    boxes = sorted(_to_boxes(res), key=lambda b: (b["box"][1] // 40, b["box"][0]))
    text = " ".join(b["text"] for b in boxes)
    # Confidence weighted by text length so a long good box dominates noise.
    total = sum(len(b["text"]) for b in boxes) or 1
    conf = sum(b["conf"] * len(b["text"]) for b in boxes) / total
    return text.strip(), float(conf)


def trocr_crop(crop: np.ndarray) -> tuple[str, float]:
    """Read a single handwritten line with TrOCR. Returns (text, conf).

    conf = exp(length-normalised beam log-probability), i.e. the geometric
    mean of token probabilities - a reasonable per-reading confidence.
    """
    if crop.size == 0 or min(crop.shape[:2]) < 8:
        return "", 0.0
    import torch
    from PIL import Image
    processor, model = trocr_model()
    rgb = Image.fromarray(crop).convert("RGB")
    pixel_values = processor(images=rgb, return_tensors="pt").pixel_values
    with torch.no_grad():
        # no_repeat_ngram_size stops the "000 000 000 ..." loops TrOCR falls
        # into on digit strings it cannot read.
        out = model.generate(pixel_values, max_new_tokens=24, num_beams=4,
                             no_repeat_ngram_size=3,
                             output_scores=True, return_dict_in_generate=True)
    text = processor.batch_decode(out.sequences, skip_special_tokens=True)[0]
    conf = float(torch.exp(out.sequences_scores[0])) if out.sequences_scores is not None else 0.5
    return text.strip(), conf
