from types import SimpleNamespace

from PIL import Image

from src.inference import PaddleOCRVLAdapter, _paddle_field_text, _paddle_full_page_fields, _paddle_gender_field


def test_paddle_text_maps_to_fields_without_guessing():
    text = "Form Application\n\nName: Alex Kim\nAge: 31\nDate: 15/10/2026\nGender: Male ☑ Female ☐"
    values = _paddle_full_page_fields(text, {"name", "age", "date", "gender"})
    assert values["name"] == "Alex Kim"
    assert values["age"] == "31"
    assert _paddle_gender_field(values["gender"])["options"] == {"Male": True, "Female": False}
    assert _paddle_field_text("Name:", "name") == ""
    assert _paddle_gender_field("Male Female")["status"] == "AMBIGUOUS"


def test_paddle_adapter_uses_one_ocr_call_per_field_crop():
    adapter = object.__new__(PaddleOCRVLAdapter)
    adapter.model_id = "paddle-test"
    outputs = iter(["Name: Alex", "Age: 31", "Date: 15/10/2026", "Gender: Male ☑ Female ☐"])
    adapter._recognize = lambda image: next(outputs)
    definitions = {key: SimpleNamespace(label=key.title()) for key in ("name", "age", "date", "gender")}
    labels = list(definitions)
    stages = []
    result, raw, elapsed = adapter.extract([Image.new("RGB", (2, 2)) for _ in labels], definitions, {"mode": "template_aligned", "image_labels": labels, "progress_callback": stages.append})
    assert result.fields["name"].raw_value == "Alex"
    assert result.fields["gender"].options == {"Male": True, "Female": False}
    assert result.form_matches_template is None
    assert len(stages) == 4
    assert "ocr_text" in raw
    assert elapsed >= 0


def test_paddle_full_page_requires_form_title_and_labels():
    adapter = object.__new__(PaddleOCRVLAdapter)
    adapter.model_id = "paddle-test"
    adapter._recognize = lambda image: "Name: Alex\nAge: 31\nDate: 15/10/2026\nGender: Male ☑ Female ☐"
    definitions = {key: SimpleNamespace(label=key.title()) for key in ("name", "age", "date", "gender")}
    result, _, _ = adapter.extract([Image.new("RGB", (2, 2))], definitions, {"mode": "full_page"})
    assert result.form_matches_template is False
