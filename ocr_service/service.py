"""Lifecycle and serialization adapter around the existing OCR modules."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Sequence

from ocr_service.pipeline.core import Decision, Issue
from ocr_service.pipeline.inference import RapidOCRAdapter
from ocr_service.pipeline.input_files import InputFile, read_inputs
from ocr_service.pipeline.pipeline import Processor, load_config
from ocr_service.pipeline.template import build_template, load_template

from ocr_service.contracts import FormDefinitionResponse, FormFieldDefinition, OcrField, OcrResponse
from ocr_service.paths import ROOT


class OcrService:
    def __init__(self, root: Path = ROOT, model=None):
        self.root = Path(root).resolve()
        self.config = load_config(self.root / "config" / "app.yaml")
        form = self.config["form"]
        layout_path = self.root / form["layout_path"]
        if layout_path.is_file():
            self.template = load_template(layout_path)
        else:
            pdf_path = self.root / form["template_path"]
            if not pdf_path.is_file():
                raise FileNotFoundError(f"Reference form missing: {pdf_path}")
            self.template = build_template(pdf_path, layout_path, form["type"], form["version"])
        if self.template.form_type != form["type"] or self.template.form_version != form["version"]:
            raise ValueError("Generated layout does not match the configured form type/version")
        ocr = self.config["ocr"]
        self.model = model or RapidOCRAdapter(str(self._model_path(ocr["detector_path"])),
                                               str(self._model_path(ocr["recognizer_path"])))
        self.processor = Processor(self.template, self.config, self.model)
        self._inference_lock = threading.Lock()

    def _model_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    @property
    def max_upload_bytes(self) -> int:
        return int(self.config["quality"]["max_bytes"])

    def form_definition(self) -> FormDefinitionResponse:
        return FormDefinitionResponse(
            form_type=self.template.form_type,
            form_version=self.template.form_version,
            page_count=max(region.page for region in self.template.fields.values()),
            fields=[FormFieldDefinition(id=key, label=region.label, page=region.page,
                                        section=region.section, data_type=region.data_type,
                                        required=region.required)
                    for key, region in self.template.fields.items()],
        )

    def process(self, files: Sequence[InputFile]) -> OcrResponse:
        started = time.perf_counter()
        images, byte_count, source_kind = read_inputs(files)
        with self._inference_lock:
            result, debug = self.processor.process(images, byte_count, source_kind)
        if result.processing["status"] == Decision.FAILED:
            raise RuntimeError("OCR inference failed")
        raw_lines = json.loads(debug.get("model_raw_output", "{}") or "{}").get("lines", [])
        transcripts = {str(page): [line["text"] for line in raw_lines if line["page"] == page]
                       for page in debug.get("unaligned_pages", [])}
        extracted = result.extraction["fields"]
        fields = {key: OcrField(value=field.normalized_value, raw_value=field.raw_value,
                                status=field.status, evidence=field.evidence, issues=field.issues)
                  for key, field in extracted.items()}
        issues = [*result.image_quality.issues,
                  *(Issue.model_validate(item) for item in result.form_validation.get("issues", [])),
                  *(Issue.model_validate(item) for item in result.validation.get("issues", []))]
        return OcrResponse(
            request_id=result.document["document_id"], schema_version=result.schema_version,
            status=result.processing["status"], form_type=result.document["form_type"],
            form_version=result.document["form_version"], page_count=result.document["page_count"],
            processed_pages=result.document["processed_pages"], template_match=result.document["template_match"],
            ocr_model=result.document["ocr_model"], processing_seconds=time.perf_counter() - started,
            ocr_seconds=float(debug.get("inference_seconds", 0)), fields=fields, issues=issues,
            image_quality=result.image_quality.model_dump(mode="json"), form_validation=result.form_validation,
            validation=result.validation, can_review=result.processing["status"] == Decision.REVIEW_REQUIRED,
            requires_recapture=result.processing["status"] == Decision.RECAPTURE_REQUIRED,
            requires_new_form=bool(result.processing.get("requires_new_form", False)), transcripts=transcripts,
        )
