from ocr_service.paths import REFERENCE_PDF
from pathlib import Path

import pytest

from ocr_service.pipeline.core import Decision, FieldResult, FieldStatus, validate_review, validate_values
from ocr_service.pipeline.template import build_template, load_template


def test_moe_layout_has_string_fields_and_only_dob_is_date(tmp_path):
    template = build_template(REFERENCE_PDF, tmp_path / "layout.json")
    assert template.page_count == 5
    assert len(template.fields) == 79
    assert {key for key, region in template.fields.items() if region.data_type == "date"} == {"applicant_date_of_birth"}
    assert {region.page for region in template.fields.values()} == {1, 2, 3}
    assert not any(hasattr(region, "options") for region in template.fields.values())
    assert template.fields["declaration_name_nric_signature"].box == (102, 316, 794, 382)
    assert template.fields["declaration_date"].box == (800, 316, 1066, 382)
    assert load_template(tmp_path / "layout.json").fields == template.fields
    assert all(Path(path).is_file() for path in template.reference_image_paths)


@pytest.mark.parametrize("dob", ["31/02/2026", "1/02/2026", "2026-02-01"])
def test_only_dob_requires_real_dd_mm_yyyy(dob, tmp_path):
    definitions = build_template(REFERENCE_PDF, tmp_path / "layout.json").fields
    values = {key: "example" if region.required else "" for key, region in definitions.items()}
    values["applicant_date_of_birth"] = dob
    values["declaration_date"] = "October 2026"
    _, issues = validate_review(values, definitions, {"date_format": "%d/%m/%Y"})
    assert [(issue.code, issue.field) for issue in issues] == [("INVALID_DATE", "applicant_date_of_birth")]


def test_optional_empty_and_string_age_are_valid(tmp_path):
    definitions = build_template(REFERENCE_PDF, tmp_path / "layout.json").fields
    values = {key: "ABC" if region.required else "" for key, region in definitions.items()}
    values["applicant_date_of_birth"] = "29/02/2024"
    values["household_1_age"] = "about 40"
    values["declaration_date"] = "22 Oct 2026"
    checked, issues = validate_review(values, definitions, {"date_format": "%d/%m/%Y"})
    assert not issues
    assert checked["household_1_age"] == "about 40"
    assert checked["declaration_date"] == "22 Oct 2026"
    assert isinstance(checked["household_1_age"], str)


def test_required_empty_is_reviewable(tmp_path):
    definitions = build_template(REFERENCE_PDF, tmp_path / "layout.json").fields
    fields = {key: FieldResult(status=FieldStatus.EMPTY) for key in definitions}
    issues, decision = validate_values(fields, definitions, {"date_format": "%d/%m/%Y"})
    assert decision == Decision.REVIEW_REQUIRED
    assert any(issue.code == "REQUIRED_EMPTY" and issue.field == "applicant_name" for issue in issues)
