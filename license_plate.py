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
        # Padda boxen: skylten sitter ofta precis vid nedre kanten av YOLO-boxen
        # och blir annars bortklippt (vanligt i sub-strömmar).
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        pad_x = int(round(bw * 0.04))
        pad_top = int(round(bh * 0.05))
        pad_bot = int(round(bh * 0.20))  # extra neråt = skyltzon
        x1 = max(0, x1 - pad_x)
        x2 = min(width, x2 + pad_x)
        y1 = max(0, y1 - pad_top)
        y2 = min(height, y2 + pad_bot)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        ch, cw = crop.shape[:2]
        # Snävare skyltzon (nedre centrala delen) ger skylten fler pixlar och
        # bättre igenkänning än hela fordonsrutan. Testas först, hela rutan som
        # fallback om skylten sitter annorlunda.
        tight = crop[int(ch * 0.50):, int(cw * 0.06):int(cw * 0.94)]
        best = None
        for cand in (tight, crop):
            if cand is None or cand.size == 0:
                continue
            best = self._ocr_crops(cand, best)
            if best and best["confidence"] >= 0.5:
                break
        return best

    def _ocr_crops(self, crop, current=None):
        """OCR på flera uppskalningar + kontrastvariant, behåll bästa träff."""
        import cv2

        if crop is None or crop.size == 0:
            return current
        # Kontrastförstärkt gråskalevariant (CLAHE) hjälper på skyltar.
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
            variants = [crop, cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)]
        except Exception:  # noqa: BLE001
            variants = [crop]
        scales = [2.0, 3.0, 4.0] if max(crop.shape[:2]) < 900 else [1.0, 2.0]
        best = current
        for src in variants:
            for scale in scales:
                scaled = src if scale == 1.0 else cv2.resize(
                    src, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
                )
                results = self._read_text(scaled)
                for raw_text, confidence in results or []:
                    text = self.normalize(raw_text)
                    score = float(confidence or 0.0)
                    if text and score >= self.min_conf and (best is None or score > best["confidence"]):
                        best = {"text": text, "confidence": round(score, 4)}
                if best and best["confidence"] >= 0.72:
                    return best
        return best

    @staticmethod
    def normalize(value: str) -> str:
        """Normalize OCR noise while keeping only plate-like alphanumerics."""
        text = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
        return text if _ALLOWED.fullmatch(text) else ""
