from ocr_service.paths import REFERENCE_PDF
from PIL import Image

from ocr_service.pipeline.image_processing import align
from ocr_service.pipeline.template import build_template


def test_small_cropped_page_can_align_to_template(tmp_path):
    template = build_template(REFERENCE_PDF, tmp_path / "layout.json")
    reference = Image.open(template.reference_image_paths[1]).convert("RGB")
    small_crop = reference.crop((70, 120, 1100, 1660)).resize((422, 652))
    result = align(small_crop, template, 2)
    assert result.reliable
    assert result.image.size == (template.width, template.height)
    assert result.diagnostics["inliers"] >= 10
