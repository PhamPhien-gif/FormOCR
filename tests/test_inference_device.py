import json
from types import SimpleNamespace

import pytest
from PIL import Image

from src.inference import InferenceError, LlamaCppAdapter, image_data_url, parse_output


def test_missing_local_files_fail_before_server_starts(tmp_path):
    with pytest.raises(InferenceError, match="Required local model or runtime file is missing"):
        LlamaCppAdapter(str(tmp_path / "model.gguf"), str(tmp_path / "mmproj.gguf"), str(tmp_path / "llama-server.exe"))


def test_image_is_embedded_as_data_url():
    assert image_data_url(Image.new("RGB", (2, 2))).startswith("data:image/jpeg;base64,")


def test_repeated_prompt_metadata_is_ignored():
    raw = json.dumps({"fields": {"name": {"label": "Name", "type": "string", "required": True, "status": "EMPTY"}}})
    assert parse_output(raw, {"name"}).fields["name"].status == "EMPTY"


def test_extract_sends_local_json_request():
    adapter = object.__new__(LlamaCppAdapter)
    adapter.process = SimpleNamespace(poll=lambda: None)
    adapter.base_url = "http://127.0.0.1:12345"
    adapter.max_new_tokens = 100
    adapter.inference_timeout_seconds = 30
    adapter.model_id = "test-model"
    sent = {}

    def post(url, json, timeout):
        sent.update(url=url, payload=json, timeout=timeout)
        raw = {"fields": {"name": {"status": "EXTRACTED", "raw_value": "Alex"}}, "crossed_out_handwriting_detected": False, "form_matches_template": None}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": __import__("json").dumps(raw)}}]})

    adapter.session = SimpleNamespace(post=post)
    definitions = {"name": SimpleNamespace(label="Name", data_type="string", required=True)}
    result, _, elapsed = adapter.extract([Image.new("RGB", (2, 2))], definitions, {"mode": "template_aligned"})
    assert result.fields["name"].raw_value == "Alex"
    assert elapsed >= 0
    assert sent["url"] == "http://127.0.0.1:12345/v1/chat/completions"
    assert sent["payload"]["response_format"] == {"type": "json_object"}
    assert sent["payload"]["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
