"""Screen capture, OCR, and pixel-based analysis for JKLM BombParty."""

from __future__ import annotations

import warnings
from typing import Final

import easyocr
import mss
import numpy as np
import torch
from PIL import Image

__all__ = [
    "capture_input_roi",
    "click_input_field",
    "detect_round_restart",
    "detect_turn_active_from_array",
    "read_syllable_from_region",
    "warmup_ocr",
]

_GPU_AVAILABLE: Final[bool] = torch.cuda.is_available()

if not _GPU_AVAILABLE:
    warnings.filterwarnings("ignore", message=".*pin_memory.*", category=UserWarning)

_ocr_reader: easyocr.Reader | None = None

# Persistent mss instance — avoids creating a new screen-capture handle
# on every poll cycle.
_sct: mss.mss | None = None


def _get_ocr_reader() -> easyocr.Reader:
    """Lazy-initialized EasyOCR singleton.  Uses GPU when available."""
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(["en"], gpu=_GPU_AVAILABLE, verbose=False)
    return _ocr_reader


def _get_sct() -> mss.mss:
    """Lazy-initialized persistent mss instance."""
    global _sct
    if _sct is None:
        _sct = mss.mss()
    return _sct


def warmup_ocr() -> None:
    """Pre-load the EasyOCR model so the first real call is fast."""
    _get_ocr_reader()


# Proportional ROIs: (x, y, w, h) relative to game window dimensions.
SYLLABLE_ROI: Final = (0.375, 0.455, 0.080, 0.145)
INPUT_ROI: Final = (0.255, 0.925, 0.320, 0.070)

# OCR tuning constants.
_OCR_CONFIDENCE_MIN: Final = 0.35
_SYLLABLE_MAX_LEN: Final = 5
_OCR_ALLOWLIST: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Turn detection: the active input bar is #161312 (RGB 22, 19, 18).
# Enough pixels within tolerance → turn is active.
_INPUT_BAR_COLOR: Final = np.array([22, 19, 18], dtype=np.float32)
_INPUT_COLOR_TOLERANCE: Final = 25
_INPUT_MATCH_FRACTION: Final = 0.55

# Round restart: the green button #26AA36 (RGB 38, 170, 54) appears in
# the input bar area between rounds.
_RESTART_COLOR: Final = np.array([38, 170, 54], dtype=np.float32)
_RESTART_COLOR_TOLERANCE: Final = 50
_RESTART_MATCH_FRACTION: Final = 0.02


def _capture_game_region(region: tuple[int, int, int, int]) -> Image.Image:
    """Capture a screen region as a PIL Image.

    Args:
        region: (x, y, width, height) in screen pixels.

    Raises:
        ValueError: If the region has non-positive dimensions.
    """
    x, y, w, h = region
    if w <= 0 or h <= 0:
        raise ValueError(f"Region must have positive dimensions, got {w}x{h}")
    screenshot = _get_sct().grab({"left": x, "top": y, "width": w, "height": h})
    return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def capture_input_roi(region: tuple[int, int, int, int]) -> np.ndarray:
    """Capture only the input-field ROI as a numpy RGB array.

    Returns the raw numpy array so callers can skip PIL overhead for
    pixel-level checks.
    """
    win_x, win_y, win_w, win_h = region
    rx, ry, rw, rh = INPUT_ROI
    roi_x = int(win_x + rx * win_w)
    roi_y = int(win_y + ry * win_h)
    roi_w = max(int(rw * win_w), 1)
    roi_h = max(int(rh * win_h), 1)

    screenshot = _get_sct().grab(
        {"left": roi_x, "top": roi_y, "width": roi_w, "height": roi_h},
    )
    # Convert BGRA → RGB via numpy slicing (faster than PIL conversion).
    bgra = np.frombuffer(screenshot.bgra, dtype=np.uint8).reshape(
        screenshot.height, screenshot.width, 4,
    )
    return np.ascontiguousarray(bgra[:, :, 2::-1])


def _extract_roi(image: Image.Image, roi: tuple[float, float, float, float]) -> Image.Image:
    """Crop a proportional sub-region from an image.

    Coordinates are clamped to image bounds to prevent zero-dimension crops.
    """
    img_w, img_h = image.size
    rx, ry, rw, rh = roi
    x0 = max(0, int(rx * img_w))
    y0 = max(0, int(ry * img_h))
    x1 = min(img_w, max(x0 + 1, int((rx + rw) * img_w)))
    y1 = min(img_h, max(y0 + 1, int((ry + rh) * img_h)))
    return image.crop((x0, y0, x1, y1))


def _is_valid_syllable(text: str, confidence: float) -> bool:
    """Validate OCR output as a plausible syllable."""
    return (
        bool(text)
        and text.isalpha()
        and len(text) <= _SYLLABLE_MAX_LEN
        and confidence >= _OCR_CONFIDENCE_MIN
    )


def _read_syllable(
    image: Image.Image,
    roi: tuple[float, float, float, float] = SYLLABLE_ROI,
) -> str | None:
    """Read the current syllable from the bomb circle via OCR.

    3× upscale gives EasyOCR enough pixels to work with on the small
    crop.  LANCZOS produces smooth edges which improves recognition.
    We pass the raw RGB image — EasyOCR's internal contrast/threshold
    handling is more reliable than a fixed binary cutoff on an animated
    background.
    """
    crop = _extract_roi(image, roi)
    if crop.width <= 0 or crop.height <= 0:
        return None

    upscaled = crop.resize(
        (crop.width * 3, crop.height * 3), Image.LANCZOS,
    )

    results = _get_ocr_reader().readtext(
        np.array(upscaled), allowlist=_OCR_ALLOWLIST, detail=1,
    )
    if not results:
        return None

    best = max(results, key=lambda r: r[2])
    text = best[1].strip().upper()
    confidence: float = best[2]

    return text if _is_valid_syllable(text, confidence) else None


def _validate_pixel_array(arr: np.ndarray) -> bool:
    """Check that an array has the expected (H, W, 3) RGB shape."""
    return bool(arr.ndim == 3 and arr.shape[2] >= 3)


def detect_turn_active_from_array(arr: np.ndarray) -> bool:
    """Detect the player's turn by color-matching the input-field ROI.

    The active input bar is #161312 (RGB 22, 19, 18).  Returns True if
    a sufficient fraction of pixels are within tolerance.
    """
    if not _validate_pixel_array(arr):
        return False
    rgb = arr[:, :, :3]
    diff = np.abs(rgb.astype(np.float32) - _INPUT_BAR_COLOR)
    close = diff.max(axis=2) < _INPUT_COLOR_TOLERANCE
    return float(close.mean()) >= _INPUT_MATCH_FRACTION


def detect_round_restart(arr: np.ndarray) -> bool:
    """Detect the green restart button (#26AA36) in the input bar area."""
    if not _validate_pixel_array(arr):
        return False
    rgb = arr[:, :, :3]
    diff = np.abs(rgb.astype(np.float32) - _RESTART_COLOR)
    close = diff.max(axis=2) < _RESTART_COLOR_TOLERANCE
    return float(close.mean()) >= _RESTART_MATCH_FRACTION


def _detect_turn_active(
    image: Image.Image,
    roi: tuple[float, float, float, float] = INPUT_ROI,
) -> bool:
    """Detect the player's turn from a full game screenshot."""
    arr = np.array(_extract_roi(image, roi).convert("RGB"))
    return detect_turn_active_from_array(arr)


def click_input_field(region: tuple[int, int, int, int]) -> None:
    """Click the centre of the input field to guarantee it has focus.

    Args:
        region: Game window (x, y, width, height) in screen pixels.
    """
    # Deferred import: pyautogui pulls in several heavy sub-modules.
    # Loading it lazily keeps the bot's startup time fast.
    import pyautogui

    rx, ry, rw, rh = INPUT_ROI
    win_x, win_y, win_w, win_h = region

    abs_x = int(win_x + (rx + rw / 2) * win_w)
    abs_y = int(win_y + (ry + rh / 2) * win_h)

    pyautogui.click(abs_x, abs_y)


def read_syllable_from_region(region: tuple[int, int, int, int]) -> str | None:
    """Capture the game window once and read the syllable.

    Returns None if the turn is not active or OCR fails.
    """
    try:
        image = _capture_game_region(region)
    except (ValueError, mss.exception.ScreenShotError):
        return None
    if not _detect_turn_active(image):
        return None
    return _read_syllable(image)
