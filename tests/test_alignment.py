from PIL import Image

from src.image_processing import align
from src.template import build_template


def test_small_cropped_page_can_align_to_template(tmp_path):
    template = build_template("MOE_FAS_Application_Form.pdf", tmp_path / "layout.json")
    reference = Image.open(template.reference_image_paths[1]).convert("RGB")
    small_crop = reference.crop((70, 120, 1100, 1660)).resize((422, 652))
    result = align(small_crop, template, 2)
    assert result.reliable
    assert result.image.size == (template.width, template.height)
    assert result.diagnostics["inliers"] >= 10
