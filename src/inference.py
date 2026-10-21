"""Local llama.cpp inference for Qwen3-VL GGUF, independent of Streamlit."""
from __future__ import annotations

import atexit
import base64
import io
import json
import logging
import re
import socket
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

import requests
from PIL import Image

from src.core import ModelOutput


LOG = logging.getLogger(__name__)


class InferenceError(RuntimeError):
    pass


class VisionLanguageModel(ABC):
    @abstractmethod
    def extract(self, images: Sequence[Image.Image], field_definitions: dict, template_context: dict) -> tuple[ModelOutput, str, float]:
        raise NotImplementedError


def parse_output(text: str, expected_fields: set[str]) -> ModelOutput:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            for field in data["fields"].values():
                if isinstance(field, dict):
                    for key in ("label", "type", "required"):
                        field.pop(key, None)
        output = ModelOutput.model_validate(data)
    except Exception as exc:
        raise InferenceError(f"Model returned invalid structured JSON: {exc}") from exc
    if set(output.fields) != expected_fields:
        raise InferenceError(f"Model fields differ from template: expected {sorted(expected_fields)}")
    if output.fields.get("gender") and output.fields["gender"].options is not None and set(output.fields["gender"].options) != {"Male", "Female"}:
        raise InferenceError("Gender options must be Male and Female")
    return output


def build_prompt(field_definitions: dict, template_context: dict) -> str:
    fields = {key: {"label": value.label, "type": value.data_type, "required": value.required} for key, value in field_definitions.items()}
    return (
        "Read ONLY the completed form images. Never copy answer values from a blank reference. "
        "The reference metadata is for layout only. Extract English handwriting exactly as visible; "
        "do not guess, correct spelling, or invent missing values. Recognize intentional checkbox ticks, X marks, "
        "or filled boxes; printing artifacts are not selections. Identify crossed-out or overwritten answers. "
        "For full-page images, check that the printed Form Application title and all four printed labels are present. "
        "For field crops, the title may be absent; return null for form_matches_template if uncertain. "
        "Return ONLY a JSON object with keys fields, crossed_out_handwriting_detected, and form_matches_template (true, false, or null if uncertain). "
        "Each field must have status (EXTRACTED, EMPTY, UNREADABLE, NOT_VISIBLE, AMBIGUOUS). "
        "Use EMPTY when a visible answer region has no handwriting; use UNREADABLE only when handwriting is present but cannot be read. "
        "raw_value (string or null), options (null except gender, where exactly Male and Female map to true, false, or null), "
        "and crossed_out (boolean). Do not repeat input metadata keys label, type, or required in the output. "
        "For unselected gender boxes return false; ambiguous marks return null. "
        "Never output evidence coordinates unless visually verified. "
        f"Mode: {template_context.get('mode', 'full_page')}. Images in order: {template_context.get('image_labels', [])}. "
        f"Expected fields: {json.dumps(fields)}."
    )


def image_data_url(image: Image.Image) -> str:
    data = io.BytesIO()
    image.convert("RGB").save(data, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(data.getvalue()).decode("ascii")


class LlamaCppAdapter(VisionLanguageModel):
    def __init__(
        self,
        model_path: str,
        projector_path: str,
        server_path: str,
        max_new_tokens: int = 1024,
        context_size: int = 8192,
        inference_timeout_seconds: int = 300,
        model_id: str = "Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M",
        image_min_tokens: int | None = 1024,
    ):
        self.model_path = Path(model_path).expanduser().resolve()
        self.projector_path = Path(projector_path).expanduser().resolve()
        self.server_path = Path(server_path).expanduser().resolve()
        for path in (self.model_path, self.projector_path, self.server_path):
            if not path.is_file():
                raise InferenceError(f"Required local model or runtime file is missing: {path}")
        for path in (self.model_path, self.projector_path):
            with path.open("rb") as handle:
                if handle.read(4) != b"GGUF":
                    raise InferenceError(f"Invalid GGUF file: {path}")
        self.max_new_tokens = max_new_tokens
        self.inference_timeout_seconds = inference_timeout_seconds
        self.model_id = model_id
        self.device = "cpu"
        self.session = requests.Session()
        self.session.trust_env = False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        command = [
            str(self.server_path), "-m", str(self.model_path), "--mmproj", str(self.projector_path),
            "-ngl", "0", "-c", str(context_size), "-np", "1",
            "--host", "127.0.0.1", "--port", str(port),
        ]
        if image_min_tokens is not None:
            command.extend(["--image-min-tokens", str(image_min_tokens)])
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.process = subprocess.Popen(command, cwd=self.server_path.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            self._wait_until_ready()
        except Exception as exc:
            self.close()
            raise InferenceError(f"Could not start local llama.cpp server: {exc}") from exc
        atexit.register(self.close)
        LOG.info("Local GGUF model ready", extra={"model_id": model_id, "device": "cpu"})

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise InferenceError(f"llama-server exited during startup (code {self.process.returncode})")
            try:
                if self.session.get(f"{self.base_url}/health", timeout=1).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.25)
        raise InferenceError("Timed out waiting for local llama-server to load the model")

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def extract(self, images: Sequence[Image.Image], field_definitions: dict, template_context: dict) -> tuple[ModelOutput, str, float]:
        if not images:
            raise InferenceError("No images supplied")
        if self.process.poll() is not None:
            raise InferenceError("Local llama-server stopped; restart Streamlit")
        content = [{"type": "image_url", "image_url": {"url": image_data_url(image)}} for image in images]
        content.append({"type": "text", "text": build_prompt(field_definitions, template_context)})
        payload = {
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "seed": 0,
            "max_tokens": self.max_new_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        start = time.perf_counter()
        try:
            response = self.session.post(f"{self.base_url}/v1/chat/completions", json=payload, timeout=(5, self.inference_timeout_seconds))
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            if not isinstance(raw, str):
                raise ValueError("Model response content is not text")
            parsed = parse_output(raw, set(field_definitions))
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise InferenceError(f"Local GGUF inference failed: {exc}") from exc
        elapsed = time.perf_counter() - start
        LOG.info("Local GGUF inference completed", extra={"model_id": self.model_id, "mode": template_context.get("mode"), "elapsed_seconds": elapsed})
        return parsed, raw, elapsed


def _paddle_field_text(text: str, field_id: str) -> str:
    """Remove the printed label without manufacturing an answer."""
    return re.sub(rf"^\s*{re.escape(field_id)}\s*[:：]?\s*", "", text.strip(), count=1, flags=re.IGNORECASE).strip()


def _paddle_full_page_fields(text: str, field_ids: set[str]) -> dict[str, str]:
    labels = "|".join(re.escape(key) for key in sorted(field_ids, key=len, reverse=True))
    matches = list(re.finditer(rf"(?im)^\s*({labels})\s*[:：]\s*", text))
    fields = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields[match.group(1).lower()] = text[match.end():end].strip()
    return fields


def _paddle_gender_field(text: str) -> dict:
    options = {}
    for label in ("Male", "Female"):
        match = re.search(rf"\b{label}\b\s*(\[[xX✓✔ ]\]|[☐□☑☒✓✔✗✘])", text, flags=re.IGNORECASE)
        if match is None:
            options[label] = None
        else:
            marker = match.group(1)
            options[label] = marker not in {"☐", "□", "[ ]"}
    status = "AMBIGUOUS" if any(value is None for value in options.values()) else "EXTRACTED" if any(options.values()) else "EMPTY"
    return {"status": status, "raw_value": text or None, "options": options}


class PaddleOCRVLAdapter(LlamaCppAdapter):
    """Use PaddleOCR-VL's OCR task and map transcribed labels to form fields."""

    preferred_mode = "full_page"

    def __init__(self, model_path: str, projector_path: str, server_path: str, max_new_tokens: int = 1024, context_size: int = 8192, inference_timeout_seconds: int = 300, model_id: str = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"):
        super().__init__(model_path, projector_path, server_path, max_new_tokens, context_size, inference_timeout_seconds, model_id, image_min_tokens=None)

    def _recognize(self, image: Image.Image) -> str:
        if self.process.poll() is not None:
            raise InferenceError("Local PaddleOCR-VL server stopped; restart Streamlit")
        payload = {
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_data_url(image)}},
                {"type": "text", "text": "OCR:"},
            ]}],
            "temperature": 0,
            "max_tokens": self.max_new_tokens,
            "stream": False,
        }
        try:
            response = self.session.post(f"{self.base_url}/v1/chat/completions", json=payload, timeout=(5, self.inference_timeout_seconds))
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("OCR response is not text")
            return content.strip()
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise InferenceError(f"Local PaddleOCR-VL inference failed: {exc}") from exc

    def extract(self, images: Sequence[Image.Image], field_definitions: dict, template_context: dict) -> tuple[ModelOutput, str, float]:
        if not images:
            raise InferenceError("No images supplied")
        started = time.perf_counter()
        field_ids = set(field_definitions)
        labels = template_context.get("image_labels", [])
        report = template_context.get("progress_callback")
        if len(images) == len(field_ids) and set(labels) == field_ids:
            transcripts = {}
            for label, image in zip(labels, images, strict=True):
                if report is not None:
                    report(f"PaddleOCR-VL reading {label}")
                transcripts[label] = self._recognize(image)
            values = {key: _paddle_field_text(transcripts[key], key) for key in field_ids}
            form_matches_template = None
        else:
            if report is not None:
                report("PaddleOCR-VL reading full page")
            text = self._recognize(images[0])
            transcripts = {"full_page": text}
            values = _paddle_full_page_fields(text, field_ids)
            form_matches_template = all(key in values for key in field_ids) and re.search(r"\bForm\s+Application\b", text, flags=re.IGNORECASE) is not None
        fields = {}
        for key in field_ids:
            if key not in values:
                fields[key] = {"status": "NOT_VISIBLE"}
            elif key == "gender":
                fields[key] = _paddle_gender_field(values[key])
            else:
                value = values[key].strip()
                fields[key] = {"status": "EXTRACTED" if value else "EMPTY", "raw_value": value or None}
        output = ModelOutput.model_validate({"fields": fields, "form_matches_template": form_matches_template})
        elapsed = time.perf_counter() - started
        raw = json.dumps({"ocr_text": transcripts}, ensure_ascii=False)
        LOG.info("Local PaddleOCR-VL inference completed", extra={"model_id": self.model_id, "mode": template_context.get("mode"), "elapsed_seconds": elapsed})
        return output, raw, elapsed
