"""Typed contracts and business rules shared by the UI and extraction pipeline."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    EMPTY = "EMPTY"
    UNREADABLE = "UNREADABLE"
    NOT_VISIBLE = "NOT_VISIBLE"
    AMBIGUOUS = "AMBIGUOUS"


class Decision(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RECAPTURE_REQUIRED = "RECAPTURE_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Issue(BaseModel):
    code: str
    message: str
    severity: str = "WARNING"
    field: str | None = None


class Evidence(BaseModel):
    bounding_box: tuple[int, int, int, int] | None = None
    coordinate_system: str | None = None

    @model_validator(mode="after")
    def valid_box(self):
        if self.bounding_box is not None:
            x1, y1, x2, y2 = self.bounding_box
            if min(x1, y1) < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("Invalid evidence bounding box")
            if self.coordinate_system not in {"reference_pixels", "uploaded_pixels"}:
                raise ValueError("Unknown evidence coordinate system")
        return self


class ModelField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: FieldStatus
    raw_value: str | None = None


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, ModelField]
    form_matches_template: bool | None = None


class FieldResult(BaseModel):
    status: FieldStatus
    raw_value: str | None = None
    normalized_value: str | None = None
    evidence: Evidence | None = None
    issues: list[Issue] = Field(default_factory=list)


class QualityResult(BaseModel):
    status: str
    metrics: dict[str, float] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)


class ProcessingResult(BaseModel):
    schema_version: str = "2.0"
    document: dict[str, Any]
    image_quality: QualityResult
    form_validation: dict[str, Any]
    extraction: dict[str, dict[str, FieldResult]]
    validation: dict[str, Any]
    processing: dict[str, Any]
    review: dict[str, Any] = Field(default_factory=lambda: {"status": "PENDING", "reviewed_values": None})
    debug: dict[str, Any] = Field(default_factory=dict, exclude=True)


def validate_values(fields: dict[str, FieldResult], definitions: dict, rules: dict) -> tuple[list[Issue], Decision]:
    issues: list[Issue] = []
    decision = Decision.REVIEW_REQUIRED
    for key, field in fields.items():
        definition = definitions[key]
        if field.status in {FieldStatus.UNREADABLE, FieldStatus.NOT_VISIBLE, FieldStatus.AMBIGUOUS}:
            if definition.required:
                decision = Decision.RECAPTURE_REQUIRED
            issues.append(Issue(code=field.status.value, message=f"{definition.label} needs manual review", field=key))
            continue
        raw = (field.raw_value or "").strip()
        field.raw_value = raw or None
        if not raw:
            field.status = FieldStatus.EMPTY
            if definition.required:
                issues.append(Issue(code="REQUIRED_EMPTY", message=f"{definition.label} is empty; complete it during review", field=key))
            continue
        if definition.data_type == "date":
            try:
                parsed = datetime.strptime(raw, rules.get("date_format", "%d/%m/%Y"))
                if parsed.strftime("%d/%m/%Y") != raw:
                    raise ValueError("Noncanonical date")
                field.normalized_value = parsed.strftime("%d/%m/%Y")
            except ValueError:
                issues.append(Issue(code="INVALID_DATE", message="Date of birth must be a real DD/MM/YYYY date", field=key))
        else:
            field.normalized_value = raw
    return issues, decision


def validate_review(values: dict[str, Any], definitions: dict, rules: dict) -> tuple[dict | None, list[Issue]]:
    checked = {key: FieldResult(status=FieldStatus.EXTRACTED, raw_value=str(values.get(key) or "")) for key in definitions}
    issues, _ = validate_values(checked, definitions, rules)
    if issues:
        return None, issues
    return {key: field.normalized_value or "" for key, field in checked.items()}, []
