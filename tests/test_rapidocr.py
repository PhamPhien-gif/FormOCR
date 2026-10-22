from types import SimpleNamespace

from PIL import Image

from src.inference import RapidOCRAdapter
from src.template import Region


class FakeEngine:
    def __call__(self, image, **kwargs):
        assert kwargs == {"use_det": True, "use_cls": False, "use_rec": True}
        return SimpleNamespace(boxes=[[[12, 12], [42, 12], [42, 25], [12, 25]]], txts=["JANE DOE"], scores=[0.98])


def test_ocr_assigns_text_to_region_without_checkbox_contract():
    adapter = RapidOCRAdapter("unused-det", "unused-rec", engine=FakeEngine())
    regions = {"applicant_name": Region(label="Applicant name", page=1, box=(10, 10, 60, 40), required=True),
               "applicant_nric": Region(label="NRIC", page=1, box=(70, 10, 120, 40))}
    output, raw, elapsed = adapter.extract([Image.new("RGB", (150, 80))], regions, {"page_numbers": [1]})
    assert output.fields["applicant_name"].raw_value == "JANE DOE"
    assert output.fields["applicant_nric"].status == "EMPTY"
    assert "JANE DOE" in raw and elapsed >= 0


def test_unaligned_page_returns_raw_text_without_mislabeling_fields():
    adapter = RapidOCRAdapter("unused-det", "unused-rec", engine=FakeEngine())
    regions = {"applicant_name": Region(label="Applicant name", page=1, box=(10, 10, 60, 40))}
    output, raw, _ = adapter.extract([Image.new("RGB", (150, 80))], regions,
                                     {"page_numbers": [1], "unmapped_pages": [1]})
    assert output.fields["applicant_name"].status == "EMPTY"
    assert "JANE DOE" in raw
