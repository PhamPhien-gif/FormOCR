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
    NEW_FORM_REQUIRED = "NEW_FORM_REQUIRED"
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
    options: dict[str, bool | None] | None = None
    crossed_out: bool = False


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, ModelField]
    crossed_out_handwriting_detected: bool = False
    form_matches_template: bool | None = None


class FieldResult(BaseModel):
    status: FieldStatus
    raw_value: str | None = None
    normalized_value: str | int | None = None
    options: dict[str, bool | None] | None = None
    evidence: Evidence | None = None
    issues: list[Issue] = Field(default_factory=list)


class QualityResult(BaseModel):
    status: str
    metrics: dict[str, float] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)


class ProcessingResult(BaseModel):
    schema_version: str = "1.0"
    document: dict[str, Any]
    image_quality: QualityResult
    form_validation: dict[str, Any]
    extraction: dict[str, dict[str, FieldResult]]
    validation: dict[str, Any]
    processing: dict[str, Any]
    review: dict[str, Any] = Field(default_factory=lambda: {"status": "PENDING", "reviewed_values": None})
    debug: dict[str, Any] = Field(default_factory=dict, exclude=True)


def validate_values(fields: dict[str, FieldResult], rules: dict) -> tuple[list[Issue], Decision]:
    issues: list[Issue] = []
    decision = Decision.REVIEW_REQUIRED
    for key, field in fields.items():
        if field.status in {FieldStatus.UNREADABLE, FieldStatus.NOT_VISIBLE, FieldStatus.AMBIGUOUS}:
            decision = Decision.RECAPTURE_REQUIRED
            issues.append(Issue(code=field.status.value, message=f"{key} requires a new photo", field=key))
            continue
        if field.status == FieldStatus.EMPTY:
            issues.append(Issue(code="REQUIRED_EMPTY", message=f"{key} is empty; complete it during review", field=key))
            continue
        raw = (field.raw_value or "").strip()
        field.raw_value = raw
        if key == "date":
            try:
                parsed = datetime.strptime(raw, rules.get("date_format", "%d/%m/%Y"))
                if parsed.strftime("%d/%m/%Y") != raw:
                    raise ValueError("Noncanonical date")
                field.normalized_value = parsed.strftime("%d/%m/%Y")
            except ValueError:
                issues.append(Issue(code="INVALID_DATE", message="Date must be a real DD/MM/YYYY date", field=key))
        elif key == "name":
            if raw:
                field.normalized_value = raw
            else:
                issues.append(Issue(code="INVALID_NAME", message="Name is required", field=key))
        elif key == "age":
            if raw.isascii() and raw.isdecimal() and int(raw) in range(rules.get("minimum_age", 0), rules.get("maximum_age", 120) + 1):
                field.normalized_value = int(raw)
            else:
                issues.append(Issue(code="INVALID_AGE", message="Age must be an integer in the allowed range", field=key))
        elif key == "gender":
            options = field.options or {}
            if set(options) != {"Male", "Female"}:
                issues.append(Issue(code="INVALID_OPTIONS", message="Gender options must be Male and Female", field=key))
                decision = Decision.RECAPTURE_REQUIRED
            elif all(options.values()):
                issues.append(Issue(code="BOTH_GENDERS", message="Both gender options are selected. Please complete a new paper form and upload a new photo.", field=key))
                decision = Decision.NEW_FORM_REQUIRED
            elif any(value is None for value in options.values()):
                issues.append(Issue(code="AMBIGUOUS_GENDER", message="Gender mark is ambiguous", field=key))
                if decision != Decision.NEW_FORM_REQUIRED:
                    decision = Decision.RECAPTURE_REQUIRED
            elif any(options.values()):
                field.normalized_value = next(k for k, v in options.items() if v)
            else:
                field.status = FieldStatus.EMPTY
                issues.append(Issue(code="REQUIRED_EMPTY", message="Gender is empty; complete it during review", field=key))
    return issues, decision


def validate_review(values: dict[str, Any], rules: dict) -> tuple[dict | None, list[Issue]]:
    checked = {
        "date": FieldResult(status=FieldStatus.EXTRACTED, raw_value=str(values.get("date") or "")),
        "name": FieldResult(status=FieldStatus.EXTRACTED, raw_value=str(values.get("name") or "")),
        "age": FieldResult(status=FieldStatus.EXTRACTED, raw_value=str(values.get("age") or "")),
        "gender": FieldResult(status=FieldStatus.EXTRACTED, options={"Male": values.get("gender") == "Male", "Female": values.get("gender") == "Female"}),
    }
    issues, _ = validate_values(checked, rules)
    if not values.get("gender"):
        issues.append(Issue(code="REQUIRED_EMPTY", message="Gender is required", field="gender"))
    if issues:
        return None, issues
    return {key: field.normalized_value for key, field in checked.items()}, []
