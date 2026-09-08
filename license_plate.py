"""Optional license-plate OCR for live vehicle detections.

The regular COCO YOLO model only finds vehicles. This reader uses EasyOCR or
PaddleOCR on vehicle crops, so it is intentionally disabled by default.
"""
from __future__ import annotations

import re
import threading

_ALLOWED = re.compile(r"^[A-Z0-9]{4,10}$")


class PlateReader:
    """Lazy selectable OCR reader with conservative plate normalization."""

    def __init__(self, engine: str = "easyocr", language: str = "en", min_conf: float = 0.45):
        self.engine = (engine or "easyocr").strip().lower()
        if self.engine not in ("easyocr", "paddleocr"):
            raise ValueError("OCR-motorn måste vara easyocr eller paddleocr")
        self.language = language or "en"
        self.min_conf = float(min_conf)
        self._reader = None
        self._lock = threading.Lock()

    def _get_reader(self):
        with self._lock:
            if self._reader is None:
                if self.engine == "paddleocr":
                    from paddleocr import PaddleOCR

                    try:
                        self._reader = PaddleOCR(
                            lang=self.language,
                            use_doc_orientation_classify=False,
                            use_doc_unwarping=False,
                            use_textline_orientation=False,
                        )
                    except TypeError:  # PaddleOCR 2.x
                        self._reader = PaddleOCR(
                            lang=self.language, use_angle_cls=False, show_log=False
                        )
                else:
                    import easyocr

                    self._reader = easyocr.Reader([self.language], gpu=False, verbose=False)
            return self._reader

    def _read_text(self, crop):
        reader = self._get_reader()
        if self.engine == "easyocr":
            return [(text, score) for _coords, text, score in reader.readtext(crop, detail=1, paragraph=False)]
        if hasattr(reader, "predict"):
            results = []
            for output in reader.predict(crop):
                data = output.json if hasattr(output, "json") else output
                if callable(data):
                    data = data()
                if isinstance(data, str):
                    import json

                    data = json.loads(data)
                data = data.get("res", data) if isinstance(data, dict) else {}
                texts = data.get("rec_texts", [])
                scores = data.get("rec_scores", [])
                results.extend(zip(texts, scores))
            return results
        raw = reader.ocr(crop, cls=False) or []
        rows = raw[0] if raw and isinstance(raw[0], list) else raw
        return [(item[1][0], item[1][1]) for item in rows if len(item) > 1]

    def read_vehicle(self, frame, box: list | tuple) -> dict | None:
        """Return the strongest normalized plate from a vehicle crop."""
        import cv2

        if frame is None or not box or len(box) < 4:
            return None
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = (int(round(float(v))) for v in box[:4])
        x1, x2 = max(0, min(x1, width - 1)), max(0, min(x2, width))
        y1, y2 = max(0, min(y1, height - 1)), max(0, min(y2, height))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        scale = 2 if max(crop.shape[:2]) < 900 else 1
        if scale > 1:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        results = self._read_text(crop)
        best = None
        for raw_text, confidence in results or []:
            text = self.normalize(raw_text)
            score = float(confidence or 0.0)
            if text and score >= self.min_conf and (best is None or score > best["confidence"]):
                best = {"text": text, "confidence": round(score, 4)}
        return best

    @staticmethod
    def normalize(value: str) -> str:
        """Normalize OCR noise while keeping only plate-like alphanumerics."""
        text = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
        return text if _ALLOWED.fullmatch(text) else ""
