"""Loading pages and gentle image preprocessing (OpenCV).

Each page is kept in two versions with the SAME geometry, so a box found on
one can be cropped from the other:
  original  - deskewed grayscale, otherwise untouched
  enhanced  - original + CLAHE contrast + light denoise
Reading both gives the "two-pass" agreement signal used in confidence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np

import config

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class Page:
    """One page image ready for OCR."""
    source: Path
    index: int              # page number inside the file (0 for images)
    original: np.ndarray    # deskewed grayscale
    enhanced: np.ndarray    # CLAHE + denoise
    skew_deg: float

    @property
    def page_id(self) -> str:
        return f"{self.source.name}#p{self.index + 1}"


def load_images(path: Path) -> list[np.ndarray]:
    """Return BGR images for a file: one per PDF page, or a single image."""
    if path.suffix.lower() == ".pdf":
        images = []
        with fitz.open(path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=config.PDF_DPI)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                images.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR))
        return images
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image {path}")
    return [img]


def estimate_skew(gray: np.ndarray) -> float:
    """Estimate page skew (degrees) from long near-horizontal lines.

    Uses Hough lines on edges; returns the median angle of lines within
    +/-10 degrees. Forms have many ruled lines, so this is robust enough.
    """
    edges = cv2.Canny(gray, 50, 150)
    min_len = gray.shape[1] // 4
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=150,
                            minLineLength=min_len, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) <= 10:
            angles.append(ang)
    return float(np.median(angles)) if angles else 0.0


def rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    """Rotate around the centre, filling with white."""
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def enhance(gray: np.ndarray) -> np.ndarray:
    """CLAHE + light non-local-means denoise. Gentle so pen strokes survive."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    out = clahe.apply(gray)
    return cv2.fastNlMeansDenoising(out, None, h=7, templateWindowSize=7, searchWindowSize=21)


def prepare_page(path: Path, index: int, bgr: np.ndarray) -> Page:
    """Grayscale -> downscale (max side) -> deskew (small angles) -> enhanced copy."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    scale = config.MAX_SIDE / max(gray.shape)
    if scale < 1:  # keeps EasyOCR time bounded on large scans / PDF renders
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    skew = estimate_skew(gray)
    if 0.2 <= abs(skew) <= 5:
        gray = rotate(gray, skew)
    else:
        skew = 0.0
    log.debug("%s p%d skew %.2f", path.name, index + 1, skew)
    return Page(path, index, gray, enhance(gray), skew)


def load_pages(path: Path) -> list[Page]:
    """All pages of a file, preprocessed."""
    return [prepare_page(path, i, img) for i, img in enumerate(load_images(path))]


def list_inputs(folder: Path = config.INPUT_DIR) -> list[Path]:
    """Supported files in the input folder, sorted by name."""
    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in IMAGE_EXTS | {".pdf"})
