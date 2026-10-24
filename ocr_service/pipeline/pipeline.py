"""Multi-page MOE FAS processing independent of Streamlit."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

import yaml
from PIL import Image, ImageOps

from ocr_service.pipeline.core import Decision, Evidence, FieldResult, Issue, ProcessingResult, QualityResult, validate_values
from ocr_service.pipeline.image_processing import align, assess_quality
from ocr_service.pipeline.inference import InferenceError, RapidOCRAdapter
from ocr_service.pipeline.state_machine import AttemptState
from ocr_service.pipeline.template import Template

LOG = logging.getLogger(__name__)


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "config" / "app.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if os.getenv("FORM_OCR_DETECTOR_PATH"):
        config["ocr"]["detector_path"] = os.environ["FORM_OCR_DETECTOR_PATH"]
    if os.getenv("FORM_OCR_RECOGNIZER_PATH"):
        config["ocr"]["recognizer_path"] = os.environ["FORM_OCR_RECOGNIZER_PATH"]
    return config


class Processor:
    def __init__(self, template: Template, config: dict, model: RapidOCRAdapter):
        self.template, self.config, self.model = template, config, model

    def process(self, images: Sequence[Image.Image], byte_count: int, source_kind: str = "images",
                progress_callback: Callable[[str], None] | None = None) -> tuple[ProcessingResult, dict]:
        def report(stage):
            if progress_callback:
                progress_callback(stage)

        state = AttemptState()
        state.transition("QUALITY_CHECKING")
        needed_pages = sorted({field.page for field in self.template.fields.values()})
        document = {"document_id": str(uuid4()), "form_type": self.template.form_type,
                    "form_version": self.template.form_version, "template_match": False,
                    "page_count": self.template.page_count, "processed_pages": needed_pages,
                    "ocr_model": self.model.model_id}
        debug: dict = {"alignments": {}, "aligned_images": {}, "unaligned_pages": []}
        quality = QualityResult(status="ACCEPTED")

        def response(decision: Decision, issues: list[Issue], fields=None):
            state.transition(decision.value)
            result = ProcessingResult(document=document, image_quality=quality,
                                      form_validation={"status": "VALID" if document["template_match"] else "UNVERIFIED", "issues": []},
                                      extraction={"fields": fields or {}},
                                      validation={"schema_valid": fields is not None, "business_valid": not issues,
                                                  "issues": [issue.model_dump() for issue in issues]},
                                      processing={"status": decision.value, "can_auto_fill": decision == Decision.REVIEW_REQUIRED,
                                                  "requires_new_form": False}, debug=debug)
            result.debug["stage_history"] = state.history
            return result, result.debug

        if not images or max(needed_pages) > len(images):
            return response(Decision.RECAPTURE_REQUIRED, [Issue(code="MISSING_PAGE", message="Pages 1–3 are required")])
        aligned = []
        for page_number in needed_pages:
            report(f"Checking page {page_number} quality")
            image = ImageOps.exif_transpose(images[page_number - 1]).convert("RGB")
            page_quality = assess_quality(image, byte_count if len(images) == 1 else 0, self.config["quality"])
            quality.metrics[f"page_{page_number}_blur"] = page_quality.metrics["blur_score"]
            quality.issues.extend(page_quality.issues)
            if page_quality.status == "RECAPTURE_REQUIRED":
                quality.status = "RECAPTURE_REQUIRED"
        if byte_count > self.config["quality"].get("max_bytes", 15_000_000):
            quality.issues.append(Issue(code="FILE_TOO_LARGE", message="Upload exceeds configured size", severity="ERROR"))
            quality.status = "RECAPTURE_REQUIRED"
        elif quality.issues:
            quality.status = "NEEDS_REVIEW"
        if quality.status == "RECAPTURE_REQUIRED":
            return response(Decision.RECAPTURE_REQUIRED, quality.issues)

        state.transition("FORM_VALIDATING")
        for page_number in needed_pages:
            report(f"Aligning page {page_number}")
            image = ImageOps.exif_transpose(images[page_number - 1]).convert("RGB")
            if source_kind == "pdf" and image.size == (self.template.width, self.template.height):
                aligned_image, reliable, diagnostics = image, True, {"method": "PDF page geometry"}
            else:
                match = align(image, self.template, page_number)
                aligned_image, reliable, diagnostics = match.image, match.reliable, match.diagnostics
            if not reliable or aligned_image is None:
                if not self.config["ocr"].get("allow_unaligned_trial", False):
                    return response(Decision.RECAPTURE_REQUIRED, [Issue(code="ALIGNMENT_FAILED", message=f"Cannot align page {page_number} with the form")])
                debug["unaligned_pages"].append(page_number)
                diagnostics = {**diagnostics, "method": "raw OCR without field mapping"}
                aligned_image = image
                quality.issues.append(Issue(code="ALIGNMENT_UNVERIFIED", message=f"Page {page_number} could not be aligned. Raw OCR text will need manual review."))
                quality.status = "NEEDS_REVIEW"
            else:
                debug["aligned_images"][page_number] = aligned_image
            debug["alignments"][page_number] = diagnostics
            aligned.append(aligned_image)
        document["template_match"] = not debug["unaligned_pages"]
        state.transition("EXTRACTING")
        try:
            extracted, raw, elapsed = self.model.extract(aligned, self.template.fields,
                                                         {"page_numbers": needed_pages, "unmapped_pages": debug["unaligned_pages"]}, report)
        except InferenceError as exc:
            return response(Decision.FAILED, [Issue(code="INFERENCE_FAILED", message=str(exc), severity="ERROR")])
        debug.update({"model_raw_output": raw, "inference_seconds": elapsed})
        state.transition("VALIDATING")
        fields = {}
        for key, region in self.template.fields.items():
            item = extracted.fields[key]
            evidence = None if region.page in debug["unaligned_pages"] else Evidence(bounding_box=region.box, coordinate_system="reference_pixels")
            fields[key] = FieldResult(status=item.status, raw_value=item.raw_value, evidence=evidence)
        issues, decision = validate_values(fields, self.template.fields, self.config["validation"])
        LOG.info("Processed %s pages with %s: %s", len(needed_pages), self.model.model_id, decision.value)
        return response(decision, issues, fields)
