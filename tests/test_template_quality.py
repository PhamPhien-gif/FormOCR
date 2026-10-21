from PIL import Image, ImageFilter

from src.image_processing import assess_quality
from src.template import build_template, load_template


def test_build_reference(tmp_path):
    template = build_template("Form.pdf", tmp_path / "layout.json")
    assert template.page_count == 1
    assert set(template.fields) == {"date", "name", "age", "gender"}
    assert set(template.fields["gender"].options) == {"Male", "Female"}
    assert load_template(tmp_path / "layout.json") == template


def test_severely_blurred_image_recapture():
    image = Image.new("RGB", (900, 1200), "white").filter(ImageFilter.GaussianBlur(20))
    report = assess_quality(image, 1000, {"min_blur": 35})
    assert report.status == "RECAPTURE_REQUIRED"
