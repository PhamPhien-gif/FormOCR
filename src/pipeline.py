"""Reusable document processor independent of Streamlit."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable
from uuid import uuid4

import yaml
from PIL import Image, ImageOps

from src.core import Decision, Evidence, FieldResult, FieldStatus, Issue, ProcessingResult, QualityResult, validate_values
from src.image_processing import align, assess_quality, crops
from src.inference import InferenceError, VisionLanguageModel
from src.template import Template
from src.state_machine import AttemptState


LOG = logging.getLogger(__name__)


def load_config(path: str | Path = "config/app.yaml") -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if os.getenv("FORM_OCR_MODEL_ID"):
        config["model"]["model_id"] = os.environ["FORM_OCR_MODEL_ID"]
    if os.getenv("FORM_OCR_MODEL_PATH"):
        config["model"]["model_path"] = os.environ["FORM_OCR_MODEL_PATH"]
    if os.getenv("FORM_OCR_PROJECTOR_PATH"):
        config["model"]["projector_path"] = os.environ["FORM_OCR_PROJECTOR_PATH"]
    if os.getenv("FORM_OCR_SERVER_PATH"):
        config["model"]["server_path"] = os.environ["FORM_OCR_SERVER_PATH"]
    for variable, key in (
        ("FORM_OCR_PADDLE_MODEL_PATH", "model_path"),
        ("FORM_OCR_PADDLE_PROJECTOR_PATH", "projector_path"),
        ("FORM_OCR_PADDLE_SERVER_PATH", "server_path"),
    ):
        if os.getenv(variable):
            config["paddle_model"][key] = os.environ[variable]
    return config


class Processor:
    def __init__(self, template: Template, config: dict, model: VisionLanguageModel):
        self.template, self.config, self.model = template, config, model

    def process(self, image: Image.Image, byte_count: int, mode: str = "auto", progress_callback: Callable[[str], None] | None = None) -> tuple[ProcessingResult, dict]:
        def report(stage: str) -> None:
            if progress_callback is not None:
                progress_callback(stage)

        request_id = str(uuid4())
        state = AttemptState()
        state.transition("QUALITY_CHECKING")
        report("Checking image quality")
        image = ImageOps.exif_transpose(image).convert("RGB")
        quality = assess_quality(image, byte_count, self.config["quality"])
        document = {"document_id": request_id, "form_type": self.template.form_type, "form_version": self.template.form_version, "template_match": False, "page_count": 1, "ocr_model": getattr(self.model, "model_id", None)}
        def response(decision: Decision, issues: list[Issue], form_status="UNKNOWN", fields=None, debug=None):
            state.transition(decision.value)
            result = ProcessingResult(document=document, image_quality=quality, form_validation={"status": form_status, "issues": []}, extraction={"fields": fields or {}}, validation={"schema_valid": fields is not None, "business_valid": not issues, "issues": [issue.model_dump() for issue in issues]}, processing={"status": decision.value, "can_auto_fill": decision == Decision.REVIEW_REQUIRED and not issues, "requires_new_form": decision == Decision.NEW_FORM_REQUIRED}, debug=debug or {})
            result.debug["stage_history"] = state.history
            LOG.info("processing decision", extra={"request_id": request_id, "form_type": self.template.form_type, "decision": decision.value, "issue_codes": [i.code for i in issues]})
            return result, result.debug
        if quality.status == "RECAPTURE_REQUIRED":
            return response(Decision.RECAPTURE_REQUIRED, quality.issues)
        state.transition("FORM_VALIDATING")
        report("Aligning image with template")
        alignment = align(image, self.template)
        debug = {"alignment": alignment.diagnostics, "aligned_image": alignment.image}
        preferred = getattr(self.model, "preferred_mode", self.config["ocr"].get("preferred_mode", "template_aligned"))
        chosen = preferred if mode == "auto" else mode
        if chosen == "template_aligned" and not alignment.reliable:
            if self.config["ocr"].get("enable_full_page_fallback", True):
                chosen = "full_page"
            else:
                return response(Decision.RECAPTURE_REQUIRED, [Issue(code="ALIGNMENT_FAILED", message="Cannot reliably locate required fields")], debug=debug)
        if chosen == "template_aligned":
            field_crops = crops(alignment.image, self.template, self.config["ocr"].get("crop_padding_ratio", 0.12))
            images = list(field_crops.values())
            debug["crops"] = field_crops
            labels = list(field_crops)
        else:
            images, labels = [image], ["completed full page"]
            if self.config["ocr"].get("enable_template_reference_image", False):
                images.append(Image.open(self.template.reference_image_path).convert("RGB"))
                labels.append("blank reference layout only; never copy answer values")
        debug["mode"] = chosen
        # A successful alignment gives structural evidence. In fallback mode the VLM must assess visibility.
        document["template_match"] = alignment.reliable
        if not alignment.reliable and chosen == "full_page":
            quality.issues.append(Issue(code="TEMPLATE_MATCH_UNVERIFIED", message="Geometric template match could not be confirmed"))
            quality.status = "NEEDS_REVIEW"
        try:
            state.transition("EXTRACTING")
            report(f"Running local OCR ({chosen})")
            extracted, raw, elapsed = self.model.extract(images, self.template.fields, {"mode": chosen, "image_labels": labels, "form_type": self.template.form_type, "progress_callback": report})
        except InferenceError as exc:
            return response(Decision.FAILED, [Issue(code="INFERENCE_FAILED", message=str(exc), severity="ERROR")], debug=debug)
        debug.update({"model_raw_output": raw, "inference_seconds": elapsed, "parsed_extraction": extracted.model_dump(mode="json")})
        state.transition("VALIDATING")
        report("Validating extracted fields")
        if extracted.form_matches_template is False or (chosen == "full_page" and extracted.form_matches_template is not True):
            return response(Decision.RECAPTURE_REQUIRED, [Issue(code="FORM_MISMATCH", message="The expected printed form structure could not be verified")], "INVALID", debug=debug)
        document["template_match"] = alignment.reliable or extracted.form_matches_template is True
        fields = {}
        for key, item in extracted.fields.items():
            evidence = Evidence(bounding_box=self.template.fields[key].box, coordinate_system="reference_pixels") if alignment.reliable else None
            fields[key] = FieldResult(status=item.status, raw_value=item.raw_value, options=item.options, evidence=evidence)
        issues, decision = validate_values(fields, self.config["validation"])
        crossed = extracted.crossed_out_handwriting_detected or any(item.crossed_out for item in extracted.fields.values())
        if crossed:
            issues.append(Issue(code="CROSSED_OUT", message="Crossed-out or corrected handwriting was detected. Please complete a new paper form and upload a new photo."))
            decision = Decision.NEW_FORM_REQUIRED
        if not alignment.reliable and any(field.status == FieldStatus.NOT_VISIBLE for field in fields.values()):
            decision = Decision.RECAPTURE_REQUIRED
        result, dbg = response(decision, issues, "INVALID" if crossed or decision == Decision.NEW_FORM_REQUIRED else "VALID" if alignment.reliable else "UNVERIFIED", fields, debug)
        result.form_validation["crossed_out_handwriting_detected"] = crossed
        return result, dbg
