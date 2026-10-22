"""Read uploaded files or files on the local Streamlit server without resizing them."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import pymupdf
from PIL import Image, ImageOps


SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}


class InputFile(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


@dataclass(frozen=True)
class LocalFile:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def load_local_paths(lines: str) -> list[LocalFile]:
    """One PDF path or three page-image paths, one per line, in page order."""
    files = []
    for raw in lines.splitlines():
        value = raw.strip().strip('"')
        if not value:
            continue
        path = Path(value).expanduser()
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported file type: {path.name}")
        if not path.is_file():
            raise ValueError(f"File not found on this computer: {path}")
        files.append(LocalFile(path.name, path.read_bytes()))
    return files


def read_inputs(files: Sequence[InputFile]) -> tuple[list[Image.Image], int, str]:
    """Decode input at its original resolution; render PDFs at 2x PDF points."""
    if not files:
        return [], 0, "images"
    total_bytes = sum(len(file.getvalue()) for file in files)
    if len(files) == 1 and files[0].name.lower().endswith(".pdf"):
        try:
            with pymupdf.open(stream=files[0].getvalue(), filetype="pdf") as pdf:
                if len(pdf) < 3:
                    raise ValueError("The PDF must include pages 1–3")
                page_text = [pdf[index].get_text().lower() for index in range(3)]
                anchors = ("financial assistance scheme", "total gross household income", "tenancy declaration")
                if any(page_text) and not all(anchor in text for anchor, text in zip(anchors, page_text)):
                    raise ValueError("The PDF does not match the expected MOE FAS application form")
                images = []
                for index in range(3):
                    pix = pdf[index].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        except pymupdf.FileDataError as exc:
            raise ValueError(f"Cannot read PDF: {exc}") from exc
        return images, total_bytes, "pdf" if all(page_text) else "images"
    if any(file.name.lower().endswith(".pdf") for file in files):
        raise ValueError("Provide one PDF, or three page images in page order")
    if len(files) != 3:
        raise ValueError("Provide exactly three full-page images in page order")
    images = []
    for file in files:
        try:
            with Image.open(io.BytesIO(file.getvalue())) as opened:
                images.append(ImageOps.exif_transpose(opened).convert("RGB"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read image {file.name}: {exc}") from exc
    return images, total_bytes, "images"
