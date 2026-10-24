from ocr_service.paths import REFERENCE_PDF
from PIL import Image

from ocr_service.pipeline.core import FieldStatus, ModelField, ModelOutput
from ocr_service.pipeline.image_processing import Alignment
from ocr_service.pipeline.pipeline import Processor, load_config
from ocr_service.pipeline.template import build_template


class StubOCR:
    model_id = "stub OCR"

    def extract(self, images, fields, context, report):
        assert context["unmapped_pages"] == [1, 2, 3]
        return ModelOutput(fields={key: ModelField(status=FieldStatus.EMPTY) for key in fields},
                           form_matches_template=False), '{"lines":[{"page":1,"text":"JANE DOE"}]}', 0.01


def test_low_resolution_alignment_failure_still_runs_raw_ocr(tmp_path, monkeypatch):
    template = build_template(REFERENCE_PDF, tmp_path / "layout.json")
    monkeypatch.setattr("ocr_service.pipeline.pipeline.align", lambda image, template, page: Alignment(None, False, {"reason": "low resolution"}))
    images = [Image.new("RGB", (423, 632), "white") for _ in range(3)]
    result, debug = Processor(template, load_config(), StubOCR()).process(images, 1000)
    assert result.processing["status"] == "REVIEW_REQUIRED"
    assert result.document["template_match"] is False
    assert result.form_validation["status"] == "UNVERIFIED"
    assert debug["unaligned_pages"] == [1, 2, 3]
    assert "JANE DOE" in debug["model_raw_output"]
