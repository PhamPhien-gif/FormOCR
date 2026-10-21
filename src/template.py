"""PDF template setup, persistence, and visible region previews."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, model_validator


class Region(BaseModel):
    label: str
    data_type: str
    required: bool = True
    section: str = "main"
    box: tuple[int, int, int, int]
    options: dict[str, tuple[int, int, int, int]] = Field(default_factory=dict)


class Template(BaseModel):
    form_type: str
    form_version: str
    page_count: int
    reference_image_path: str
    width: int
    height: int
    fields: dict[str, Region]
    verified: bool = False

    @model_validator(mode="after")
    def valid_regions(self):
        for region in self.fields.values():
            for box in [region.box, *region.options.values()]:
                x1, y1, x2, y2 = box
                if not (0 <= x1 < x2 <= self.width and 0 <= y1 < y2 <= self.height):
                    raise ValueError(f"Region outside template: {box}")
        return self


def build_template(pdf_path: str | Path, output_path: str | Path, form_type="DEMO_APPLICATION", version="1.0") -> Template:
    """Locate printed labels; reserve space to their right for handwriting."""
    pdf_path, output_path = Path(pdf_path), Path(output_path)
    with pymupdf.open(pdf_path) as pdf:
        if len(pdf) != 1:
            raise ValueError("This demo currently requires a one-page form")
        page = pdf[0]
        words = page.get_text("words")
        anchors = {}
        for key in ("Name", "Age", "Date", "Gender"):
            matches = [w for w in words if w[4].rstrip(":") == key]
            if len(matches) != 1:
                raise ValueError(f"Could not uniquely locate printed label {key}")
            anchors[key.lower()] = matches[0]
        scale = 2.0
        width, height = round(page.rect.width * scale), round(page.rect.height * scale)
        image_path = output_path.parent / "reference_page_1.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image_path)
        fields = {}
        for key, kind in (("name", "string"), ("age", "integer"), ("date", "date"), ("gender", "single_select")):
            word = anchors[key]
            y1 = max(0, round((word[1] - 7) * scale))
            y2 = min(height, round((word[3] + 10) * scale))
            x1 = max(0, round((word[0] - 5) * scale))
            x2 = min(width, round(450 * scale)) if key != "gender" else min(width, round(250 * scale))
            options = {}
            if key == "gender":
                # Boxes are anchored to actual checkbox glyphs in the reference PDF.
                glyphs = [w for w in words if "☐" in w[4]]
                for option, glyph in zip(("Male", "Female"), glyphs, strict=False):
                    gx = glyph[0] if glyph[4].startswith("☐") else glyph[2] - 14
                    options[option] = (round(gx * scale), round((glyph[1] - 2) * scale), round((gx + 14) * scale), round((glyph[3] + 2) * scale))
            fields[key] = Region(label=key.title(), data_type=kind, box=(x1, y1, x2, y2), options=options)
    template = Template(form_type=form_type, form_version=version, page_count=1, reference_image_path=str(image_path), width=width, height=height, fields=fields)
    save_template(template, output_path)
    return template


def save_template(template: Template, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.model_dump_json(indent=2), encoding="utf-8")


def load_template(path: str | Path) -> Template:
    return Template.model_validate_json(Path(path).read_text(encoding="utf-8"))


def preview(template: Template) -> Image.Image:
    image = Image.open(template.reference_image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for key, region in template.fields.items():
        draw.rectangle(region.box, outline="red", width=3)
        draw.text((region.box[0], max(0, region.box[1] - 18)), key, fill="red")
        for box in region.options.values():
            draw.rectangle(box, outline="blue", width=2)
    return image
