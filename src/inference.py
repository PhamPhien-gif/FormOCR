"""Offline RapidOCR adapter using PP-OCRv5 detection and English recognition."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image

from src.core import FieldStatus, ModelField, ModelOutput


class InferenceError(RuntimeError):
    pass


class RapidOCRAdapter:
    model_id = "RapidOCR / PP-OCRv5 English"
    device = "cpu"

    def __init__(self, detector_path: str, recognizer_path: str, engine=None):
        self.detector_path = Path(detector_path).resolve()
        self.recognizer_path = Path(recognizer_path).resolve()
        if engine is None:
            for path in (self.detector_path, self.recognizer_path):
                if not path.is_file():
                    raise InferenceError(f"Local OCR model missing: {path}. Run scripts/download_rapidocr_models.py first.")
            from rapidocr import OCRVersion, RapidOCR

            engine = RapidOCR(params={
                "Global.use_cls": False,
                "Det.model_path": str(self.detector_path),
                "Rec.model_path": str(self.recognizer_path),
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.lang_type": "en",
                "EngineConfig.onnxruntime.use_cuda": False,
            })
        self.engine = engine

    def extract(self, images: Sequence[Image.Image], field_definitions: dict, template_context: dict,
                progress_callback: Callable[[str], None] | None = None) -> tuple[ModelOutput, str, float]:
        started = time.perf_counter()
        page_numbers = template_context.get("page_numbers", list(range(1, len(images) + 1)))
        unmapped_pages = set(template_context.get("unmapped_pages", []))
        assigned = {key: [] for key in field_definitions}
        all_lines = []
        for page_number, image in zip(page_numbers, images, strict=True):
            if progress_callback:
                progress_callback(f"Running OCR on page {page_number}")
            try:
                result = self.engine(image, use_det=True, use_cls=False, use_rec=True)
            except Exception as exc:
                raise InferenceError(f"RapidOCR failed on page {page_number}: {exc}") from exc
            for box, value, confidence in zip(result.boxes if result.boxes is not None else [],
                                              result.txts if result.txts is not None else [],
                                              result.scores if result.scores is not None else [], strict=True):
                points = [tuple(map(float, point)) for point in box]
                center_x = sum(point[0] for point in points) / len(points)
                center_y = sum(point[1] for point in points) / len(points)
                line = {"page": page_number, "text": str(value), "confidence": float(confidence), "box": points}
                all_lines.append(line)
                candidates = [(key, region) for key, region in field_definitions.items()
                              if page_number not in unmapped_pages and region.page == page_number
                              and region.box[0] <= center_x <= region.box[2]
                              and region.box[1] <= center_y <= region.box[3]]
                if candidates:
                    key, _ = min(candidates, key=lambda item: (item[1].box[2] - item[1].box[0]) * (item[1].box[3] - item[1].box[1]))
                    assigned[key].append(line)
        fields = {}
        for key, lines in assigned.items():
            lines.sort(key=lambda item: (round(sum(p[1] for p in item["box"]) / 4 / 12), min(p[0] for p in item["box"])))
            value = " ".join(line["text"].strip() for line in lines).strip()
            if key == "total_gross_household_income":
                value = re.sub(r"\s*/\s*month\s*$", "", value, flags=re.IGNORECASE)
                value = re.sub(r"^\s*\$\s*", "", value).strip()
            fields[key] = ModelField(status=FieldStatus.EXTRACTED if value else FieldStatus.EMPTY, raw_value=value or None)
        output = ModelOutput(fields=fields, form_matches_template=not unmapped_pages)
        raw = json.dumps({"lines": all_lines, "field_lines": assigned}, ensure_ascii=False)
        return output, raw, time.perf_counter() - started
