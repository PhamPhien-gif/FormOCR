"""Coordinates for writable cells of the supplied five-page MOE FAS form."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, model_validator

SCALE = 2.0


class Region(BaseModel):
    label: str
    page: int
    box: tuple[int, int, int, int]
    data_type: str = "string"
    required: bool = False
    section: str = ""


class Template(BaseModel):
    form_type: str
    form_version: str
    page_count: int
    reference_image_paths: list[str]
    width: int
    height: int
    fields: dict[str, Region]
    verified: bool = False
    verified_pages: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_regions(self):
        if len(self.reference_image_paths) != self.page_count:
            raise ValueError("A reference image is required for every page")
        for key, region in self.fields.items():
            x1, y1, x2, y2 = region.box
            if region.page < 1 or region.page > self.page_count or not (0 <= x1 < x2 <= self.width and 0 <= y1 < y2 <= self.height):
                raise ValueError(f"Invalid region {key}: page {region.page}, {region.box}")
            if region.data_type not in {"string", "date"}:
                raise ValueError(f"Unsupported data type for {key}")
        return self


def _box(x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int, int]:
    return tuple(round(value * SCALE) for value in (x1, y1, x2, y2))


def _cell(x1: float, y1: float, x2: float, y2: float, inset: float = 3.5):
    return _box(x1 + inset, y1 + inset, x2 - inset, y2 - inset)


def _fields() -> dict[str, Region]:
    fields: dict[str, Region] = {}

    def add(key, label, page, box, section, required=False, data_type="string"):
        fields[key] = Region(label=label, page=page, box=box, section=section, required=required, data_type=data_type)

    add("form_submitted_to", "Form submitted to", 1, _box(140, 166, 379, 187), "Submission")
    applicant = [
        ("applicant_nric", "Applicant NRIC", 143.7, 209.6, 291.8, 249.2),
        ("applicant_name", "Applicant name", 384, 209.6, 533.5, 249.2),
        ("applicant_citizenship", "Applicant citizenship", 143.7, 249.2, 291.8, 288.7),
        ("applicant_date_of_birth", "Applicant date of birth", 384, 249.2, 533.5, 288.7),
        ("applicant_contact_no", "Applicant contact number", 143.7, 288.7, 291.8, 328.2),
        ("applicant_email_address", "Applicant email address", 384, 288.7, 533.5, 328.2),
        ("applicant_home_address", "Applicant home address", 143.7, 328.2, 533.5, 367.9),
    ]
    for key, label, x1, y1, x2, y2 in applicant:
        add(key, label, 1, _cell(x1, y1, x2, y2), "Applicant", required=True, data_type="date" if key == "applicant_date_of_birth" else "string")

    child_columns = [
        ("bc_nric_no", "BC / NRIC No.", 50.8, 143.7),
        ("name", "Child name", 143.7, 281.2),
        ("current_school", "Current school", 281.2, 428.7),
        ("current_level", "Current level", 428.7, 533.5),
    ]
    child_rows = [415.5, 455.0, 494.5, 534.0, 573.5, 613.2]
    for row in range(5):
        for suffix, label, x1, x2 in child_columns:
            add(f"child_{row+1}_{suffix}", f"Child {row+1}: {label}", 1, _cell(x1, child_rows[row], x2, child_rows[row+1]), "Children", required=row == 0)

    household_columns = [
        ("name_bc_nric", "Name and BC / NRIC No.", 85.2, 164.2),
        ("relationship_marital_status", "Relationship and marital status", 164.2, 239.2),
        ("age", "Age", 239.2, 269.2),
        ("occupation_status", "Occupation status", 269.2, 364.2),
        ("gross_monthly_income", "12-month average gross monthly income", 364.2, 449.2),
        ("other_administrative_income", "Other administrative income", 449.2, 533.1),
    ]
    household_rows = [150.9, 185.4, 219.9, 254.4, 288.9, 323.4, 357.9, 392.4, 426.9]
    for row in range(8):
        for suffix, label, x1, x2 in household_columns:
            add(f"household_{row+1}_{suffix}", f"Household {row+1}: {label}", 2, _cell(x1, household_rows[row], x2, household_rows[row+1], 2.5), "Household")
    add("total_gross_household_income", "Total gross household income", 2, _box(467, 429, 490, 445), "Household")

    add("declaration_name_nric_signature", "Declaration name, NRIC and signature", 3, _box(51, 158, 397, 191), "Declaration")
    add("declaration_date", "Declaration date", 3, _box(400, 158, 533, 191), "Declaration")
    return fields


def build_template(pdf_path: str | Path, output_path: str | Path, form_type="MOE_FAS", version="2026-10") -> Template:
    pdf_path, output_path = Path(pdf_path), Path(output_path)
    with pymupdf.open(pdf_path) as pdf:
        if len(pdf) != 5 or not all(abs(page.rect.width - 595.3) < 2 and abs(page.rect.height - 841.9) < 2 for page in pdf):
            raise ValueError("Expected the five-page A4 MOE FAS application form")
        if "FAS" not in pdf[0].get_text() or "SECTION II" not in pdf[1].get_text().upper():
            raise ValueError("PDF content does not match the expected MOE FAS form")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        paths = []
        for page_number, page in enumerate(pdf, 1):
            image_path = output_path.parent / f"reference_page_{page_number}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), alpha=False).save(image_path)
            paths.append(str(image_path))
        template = Template(form_type=form_type, form_version=version, page_count=5, reference_image_paths=paths,
                            width=round(pdf[0].rect.width * SCALE), height=round(pdf[0].rect.height * SCALE), fields=_fields())
    save_template(template, output_path)
    return template


def save_template(template: Template, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.model_dump_json(indent=2), encoding="utf-8")


def load_template(path: str | Path) -> Template:
    return Template.model_validate_json(Path(path).read_text(encoding="utf-8"))


def preview(template: Template, page_number: int = 1) -> Image.Image:
    image = Image.open(template.reference_image_paths[page_number - 1]).convert("RGB")
    draw = ImageDraw.Draw(image)
    for key, region in template.fields.items():
        if region.page == page_number:
            draw.rectangle(region.box, outline="red", width=2)
            draw.text((region.box[0], max(0, region.box[1] - 18)), key, fill="red")
    return image
