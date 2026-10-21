import pytest

from src.core import Decision, FieldResult, FieldStatus, validate_review, validate_values
from src.inference import InferenceError, parse_output


RULES = {"date_format": "%d/%m/%Y", "minimum_age": 0, "maximum_age": 120}


def fields(name="John Smith", age="21", date="15/10/2026", options=None):
    return {
        "date": FieldResult(status=FieldStatus.EXTRACTED, raw_value=date),
        "name": FieldResult(status=FieldStatus.EXTRACTED if name else FieldStatus.EMPTY, raw_value=name or None),
        "age": FieldResult(status=FieldStatus.EXTRACTED if age else FieldStatus.EMPTY, raw_value=age or None),
        "gender": FieldResult(status=FieldStatus.EXTRACTED, options=options or {"Male": True, "Female": False}),
    }


def test_valid_and_review_change():
    result = fields()
    issues, decision = validate_values(result, RULES)
    assert not issues and decision == Decision.REVIEW_REQUIRED
    final, errors = validate_review({"date": "15/10/2026", "name": "Jane Smith", "age": "21", "gender": "Female"}, RULES)
    assert not errors and final == {"date": "15/10/2026", "name": "Jane Smith", "age": 21, "gender": "Female"}


@pytest.mark.parametrize("key", ["name", "age"])
def test_empty_can_be_reviewed(key):
    result = fields(**{key: ""})
    issues, decision = validate_values(result, RULES)
    assert decision == Decision.REVIEW_REQUIRED
    assert any(issue.code == "REQUIRED_EMPTY" and issue.field == key for issue in issues)


@pytest.mark.parametrize("date,age", [("31/02/2026", "21"), ("15/10/2026", "21.5"), ("15/10/2026", "-1"), ("15/10/2026", "121")])
def test_invalid_date_or_age(date, age):
    issues, _ = validate_values(fields(date=date, age=age), RULES)
    assert issues


def test_double_selected_requires_new_form():
    issues, decision = validate_values(fields(options={"Male": True, "Female": True}), RULES)
    assert decision == Decision.NEW_FORM_REQUIRED and issues[0].code == "BOTH_GENDERS"


def test_neither_selected_is_empty():
    result = fields(options={"Male": False, "Female": False})
    _, decision = validate_values(result, RULES)
    assert decision == Decision.REVIEW_REQUIRED and result["gender"].status == FieldStatus.EMPTY


@pytest.mark.parametrize("status", [FieldStatus.UNREADABLE, FieldStatus.NOT_VISIBLE, FieldStatus.AMBIGUOUS])
def test_bad_region_requires_recapture(status):
    result = fields()
    result["name"].status = status
    _, decision = validate_values(result, RULES)
    assert decision == Decision.RECAPTURE_REQUIRED


def test_malformed_model_output_fails():
    with pytest.raises(InferenceError):
        parse_output("not JSON", {"date"})
    with pytest.raises(InferenceError):
        parse_output('{"fields":{"date":{"status":"UNSUPPORTED"}}}', {"date"})
