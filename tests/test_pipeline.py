from PIL import Image

from src.core import Decision, ModelOutput
from src.pipeline import Processor, load_config
from src.template import build_template


class StubModel:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def extract(self, images, field_definitions, template_context):
        self.calls += 1
        return ModelOutput.model_validate(self.data), "{}", 0.1


def output(**changes):
    data = {
        "fields": {
            "date": {"status": "EXTRACTED", "raw_value": "15/10/2026"},
            "name": {"status": "EXTRACTED", "raw_value": "John Smith"},
            "age": {"status": "EXTRACTED", "raw_value": "21"},
            "gender": {"status": "EXTRACTED", "options": {"Male": True, "Female": False}},
        },
        "form_matches_template": True,
    }
    data.update(changes)
    return data


def test_pipeline_decisions(tmp_path):
    template = build_template("Form.pdf", tmp_path / "layout.json")
    image = Image.open(template.reference_image_path)
    config = load_config()
    model = StubModel(output())
    stages = []
    result, _ = Processor(template, config, model).process(image, 100000, progress_callback=stages.append)
    assert result.processing["status"] == Decision.REVIEW_REQUIRED
    assert model.calls == 1
    assert stages[0] == "Checking image quality"
    assert "Aligning image with template" in stages
    assert any(stage.startswith("Running local OCR") for stage in stages)
    assert stages[-1] == "Validating extracted fields"

    model = StubModel(output(crossed_out_handwriting_detected=True))
    result, _ = Processor(template, config, model).process(image, 100000)
    assert result.processing["status"] == Decision.NEW_FORM_REQUIRED

    model = StubModel(output())
    result, _ = Processor(template, config, model).process(Image.new("RGB", (1200, 1600), "white"), 10000)
    assert result.processing["status"] == Decision.RECAPTURE_REQUIRED
    assert model.calls == 0
