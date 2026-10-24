"""Public OCR transport contract; field IDs and statuses come from the existing pipeline."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ocr_service.pipeline.core import Evidence, FieldStatus, Issue


class TransportModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class FormFieldDefinition(TransportModel):
    id: str
    label: str
    page: int
    section: str
    data_type: str = Field(alias="dataType")
    required: bool


class FormDefinitionResponse(TransportModel):
    form_type: str = Field(alias="formType")
    form_version: str = Field(alias="formVersion")
    page_count: int = Field(alias="pageCount")
    fields: list[FormFieldDefinition]


class OcrField(TransportModel):
    value: str | None
    raw_value: str | None = Field(alias="rawValue")
    status: FieldStatus
    evidence: Evidence | None = None
    issues: list[Issue] = Field(default_factory=list)


class OcrResponse(TransportModel):
    request_id: str = Field(alias="requestId")
    schema_version: str = Field(alias="schemaVersion")
    status: str
    form_type: str = Field(alias="formType")
    form_version: str = Field(alias="formVersion")
    page_count: int = Field(alias="pageCount")
    processed_pages: list[int] = Field(alias="processedPages")
    template_match: bool = Field(alias="templateMatch")
    ocr_model: str = Field(alias="ocrModel")
    processing_seconds: float = Field(alias="processingSeconds")
    ocr_seconds: float = Field(alias="ocrSeconds")
    fields: dict[str, OcrField]
    issues: list[Issue]
    image_quality: dict[str, Any] = Field(alias="imageQuality")
    form_validation: dict[str, Any] = Field(alias="formValidation")
    validation: dict[str, Any]
    can_review: bool = Field(alias="canReview")
    requires_recapture: bool = Field(alias="requiresRecapture")
    requires_new_form: bool = Field(alias="requiresNewForm")
    transcripts: dict[str, list[str]] = Field(default_factory=dict)


class ApiError(TransportModel):
    code: str
    message: str
