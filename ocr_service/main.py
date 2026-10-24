"""FastAPI HTTP layer for the existing three-page FormOCR processor."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ocr_service.contracts import ApiError, FormDefinitionResponse, OcrResponse
from ocr_service.service import OcrService
from ocr_service.pipeline.input_files import LocalFile

LOG = logging.getLogger(__name__)
SIGNATURES = {
    ".pdf": (b"%PDF-", "application/pdf"),
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}


class HttpError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code, self.code, self.message = status_code, code, message


def create_app(service_factory: Callable[[], OcrService] = OcrService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.ocr_service = await run_in_threadpool(service_factory)
            app.state.ocr_error = None
        except Exception as exc:
            LOG.exception("OCR service initialization failed")
            app.state.ocr_service = None
            app.state.ocr_error = str(exc)
        yield

    app = FastAPI(title="FAS OCR Service", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(HttpError)
    async def handle_http_error(_request: Request, exc: HttpError):
        return JSONResponse(status_code=exc.status_code, content=ApiError(code=exc.code, message=exc.message).model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse(status_code=422, content=ApiError(code="INVALID_REQUEST", message="Provide a multipart file field and valid form parameters.").model_dump())

    def service(request: Request) -> OcrService:
        current = getattr(request.app.state, "ocr_service", None)
        if current is None:
            raise HttpError(503, "OCR_UNAVAILABLE", "OCR engine is not ready. Check the local model and template files.")
        return current

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "fas-ocr-service"}

    @app.get("/ready")
    async def ready(request: Request):
        service(request)
        return {"status": "ready", "service": "fas-ocr-service"}

    @app.get("/api/v1/forms/current", response_model=FormDefinitionResponse)
    async def current_form(request: Request):
        return service(request).form_definition()

    @app.post("/api/v1/ocr/extract", response_model=OcrResponse)
    async def extract(request: Request, file: list[UploadFile] = File(...),
                      form_type: str | None = Form(default=None),
                      form_version: str | None = Form(default=None)):
        current = service(request)
        if form_type and form_type != current.template.form_type:
            raise HttpError(422, "UNSUPPORTED_FORM", "The requested form type is not supported.")
        if form_version and form_version != current.template.form_version:
            raise HttpError(422, "UNSUPPORTED_VERSION", "The requested form version is not supported.")
        if len(file) not in (1, 3):
            raise HttpError(422, "INVALID_PAGE_COUNT", "Provide one PDF or three page images in order.")
        prepared: list[LocalFile] = []
        total = 0
        for upload in file:
            filename = Path(upload.filename or "").name
            suffix = Path(filename).suffix.lower()
            if suffix not in SIGNATURES:
                raise HttpError(415, "UNSUPPORTED_FORMAT", "Only PDF, PNG and JPEG files are supported.")
            chunks = []
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > current.max_upload_bytes:
                    raise HttpError(413, "FILE_TOO_LARGE", "Uploaded files exceed the configured size limit.")
                chunks.append(chunk)
            data = b"".join(chunks)
            if not data:
                raise HttpError(400, "EMPTY_FILE", "The uploaded file is empty.")
            if not data.startswith(SIGNATURES[suffix][0]):
                raise HttpError(415, "UNSUPPORTED_FORMAT", f"{filename} does not match its file extension.")
            prepared.append(LocalFile(filename, data))
            await upload.close()
        if len(prepared) == 1 and not prepared[0].name.lower().endswith(".pdf"):
            raise HttpError(422, "INVALID_PAGE_COUNT", "This form needs one PDF or three page images.")
        if len(prepared) == 3 and any(item.name.lower().endswith(".pdf") for item in prepared):
            raise HttpError(422, "INVALID_PAGE_COUNT", "Provide one PDF or three page images in order.")
        timeout = float(os.getenv("OCR_REQUEST_TIMEOUT_SECONDS", "180"))
        try:
            return await asyncio.wait_for(run_in_threadpool(current.process, prepared), timeout=timeout)
        except TimeoutError as exc:
            raise HttpError(504, "OCR_TIMEOUT", "OCR processing timed out.") from exc
        except (ValueError, OSError) as exc:
            raise HttpError(422, "INVALID_DOCUMENT", str(exc)) from exc
        except (RuntimeError, ValidationError) as exc:
            LOG.exception("OCR processing failed")
            raise HttpError(500, "OCR_PROCESSING_FAILED", "OCR processing failed. Please retry or check the service logs.") from exc

    return app


app = create_app()
