"""HTTP contract tests with the OCR engine replaced by an in-memory stub."""
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from ocr_service.contracts import FormDefinitionResponse, FormFieldDefinition, OcrResponse
from ocr_service.main import create_app
from ocr_service.service import OcrService


class StubTemplate:
    form_type = "MOE_FAS"
    form_version = "2026-10"


class StubService:
    template = StubTemplate()
    max_upload_bytes = 100

    def form_definition(self):
        return FormDefinitionResponse(form_type="MOE_FAS", form_version="2026-10", page_count=3,
                                      fields=[FormFieldDefinition(id="applicant_name", label="Name", page=1,
                                                                  section="Applicant", data_type="string", required=True)])

    def process(self, files):
        assert len(files) in (1, 3)
        return OcrResponse(request_id="test-1", schema_version="2.0", status="REVIEW_REQUIRED",
                           form_type="MOE_FAS", form_version="2026-10", page_count=3,
                           processed_pages=[1, 2, 3], template_match=True, ocr_model="stub",
                           processing_seconds=0.1, ocr_seconds=0.05, fields={}, issues=[],
                           image_quality={}, form_validation={}, validation={}, can_review=True,
                           requires_recapture=False, requires_new_form=False)


@contextmanager
def client():
    with TestClient(create_app(lambda: StubService())) as test_client:
        yield test_client


def test_schema_and_pdf_contract():
    with client() as api:
        form = api.get("/api/v1/forms/current")
        assert form.status_code == 200
        assert form.json()["fields"][0]["dataType"] == "string"
        response = api.post("/api/v1/ocr/extract", files=[("file", ("form.pdf", b"%PDF- demo", "application/pdf"))],
                            data={"form_type": "MOE_FAS", "form_version": "2026-10"})
        assert response.status_code == 200
        assert response.json()["requestId"] == "test-1"


def test_rejects_wrong_count_signature_and_version():
    with client() as api:
        image = ("page.png", b"\x89PNG\r\n\x1a\n" + b"x", "image/png")
        assert api.post("/api/v1/ocr/extract", files=[("file", image)]).json()["code"] == "INVALID_PAGE_COUNT"
        assert api.post("/api/v1/ocr/extract", files=[("file", ("page.pdf", b"bad", "application/pdf"))]).json()["code"] == "UNSUPPORTED_FORMAT"
        assert api.post("/api/v1/ocr/extract", files=[("file", ("page.pdf", b"%PDF- demo", "application/pdf"))],
                        data={"form_version": "wrong"}).json()["code"] == "UNSUPPORTED_VERSION"
        assert api.post("/api/v1/ocr/extract", files=[("file", image)] * 3).status_code == 200


def test_rejects_oversized_upload():
    with client() as api:
        response = api.post("/api/v1/ocr/extract", files=[("file", ("form.pdf", b"%PDF-" + b"x" * 100, "application/pdf"))])
        assert response.status_code == 413
        assert response.json()["code"] == "FILE_TOO_LARGE"


def test_current_layout_exposes_three_input_pages_and_all_fields(tmp_path, monkeypatch):
    class FakeModel:
        model_id = "fake"

    monkeypatch.chdir(tmp_path)
    service = OcrService(model=FakeModel())
    definition = service.form_definition()
    assert definition.page_count == 3
    assert len(definition.fields) == 79
    assert sum(field.data_type == "date" for field in definition.fields) == 1
    assert not any(field.data_type == "checkbox" for field in definition.fields)
    assert all(Path(path).is_file() for path in service.template.reference_image_paths)
