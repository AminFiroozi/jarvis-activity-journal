"""Optional OCR adapter for screenshot evidence.

OCR is deliberately best-effort. The analyzer can operate with no OCR package,
no OCR executable, or an unreadable image and will still send the screenshot to
the configured vision model.
"""

from __future__ import annotations

import pathlib
from typing import Any


_AUTO = object()


def extract_text(image: pathlib.Path, ocr_module: Any = _AUTO) -> dict:
    """Return OCR regions with text, confidence, and pixel bounding boxes.

    ``pytesseract`` is optional. Passing ``ocr_module=None`` explicitly disables
    OCR, which is useful for callers and tests that want deterministic fallback
    behavior.
    """
    if ocr_module is _AUTO:
        try:
            import pytesseract  # type: ignore
        except ImportError:
            return {"available": False, "regions": [], "reason": "OCR dependency unavailable"}
        ocr_module = pytesseract
    if ocr_module is None:
        return {"available": False, "regions": [], "reason": "OCR unavailable"}

    try:
        data = ocr_module.image_to_data(str(image), output_type=ocr_module.Output.DICT)
        regions = []
        for index, text in enumerate(data.get("text", [])):
            text = str(text).strip()
            if not text:
                continue
            try:
                confidence = float(data.get("conf", ["-1"])[index])
            except (IndexError, TypeError, ValueError):
                confidence = -1.0
            regions.append({
                "text": text,
                "confidence": max(0.0, min(1.0, confidence / 100.0)) if confidence >= 0 else 0.0,
                "box": [
                    int(data.get("left", [0])[index]),
                    int(data.get("top", [0])[index]),
                    int(data.get("width", [0])[index]),
                    int(data.get("height", [0])[index]),
                ],
            })
        return {"available": True, "regions": regions}
    except Exception as error:  # OCR must never prevent vision analysis.
        return {"available": False, "regions": [], "reason": f"OCR failed: {error}"}
