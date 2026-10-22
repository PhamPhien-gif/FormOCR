import pytest
from PIL import Image, ImageDraw

from src.image_processing import assess_quality
from src.input_files import load_local_paths, read_inputs
from src.pipeline import load_config


def sample_paths(tmp_path):
    paths = [tmp_path / f"page{number}.png" for number in (1, 2, 3)]
    for path, size in zip(paths, [(423, 632), (422, 652), (465, 642)], strict=True):
        image = Image.new("RGB", size, "white")
        ImageDraw.Draw(image).text((20, 20), "Sample form", fill="black")
        image.save(path)
    return paths


def test_local_paths_preserve_original_image_bytes_and_dimensions(tmp_path):
    paths = sample_paths(tmp_path)
    files = load_local_paths("\n".join(str(path) for path in paths))
    images, byte_count, source_kind = read_inputs(files)
    assert [file.getvalue() for file in files] == [path.read_bytes() for path in paths]
    assert [image.size for image in images] == [(423, 632), (422, 652), (465, 642)]
    assert byte_count == sum(path.stat().st_size for path in paths)
    assert source_kind == "images"


def test_small_image_has_no_resolution_warning(tmp_path):
    images, _, _ = read_inputs(load_local_paths("\n".join(str(path) for path in sample_paths(tmp_path))))
    quality = assess_quality(images[0], 0, load_config()["quality"])
    assert "LOW_RESOLUTION" not in {issue.code for issue in quality.issues}


def test_local_path_error_is_actionable():
    with pytest.raises(ValueError, match="File not found"):
        load_local_paths("does-not-exist.png")
