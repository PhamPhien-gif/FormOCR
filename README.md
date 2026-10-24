# FormOCR — MOE FAS application form

Local, CPU based OCR demo for the current MOE FAS application form. React handles upload and human review; ASP.NET Core validates requests and forwards them to FastAPI; FastAPI calls the existing RapidOCR + PP-OCRv5 English pipeline. There is no database.

## Project layout

```text
FormOCR/
├── frontend/                  React, TypeScript, Vite, UI tests
├── backend/                   ASP.NET Core gateway and contract tests
├── ocr_service/               FastAPI and all Python OCR resources
│   ├── pipeline/              Existing decoding, alignment, OCR, field mapping
│   ├── assets/                Reference FAS PDF
│   ├── config/                Form and OCR configuration
│   ├── scripts/               Offline model downloader
│   ├── tests/                 Python pipeline and API tests
│   ├── samples/               Sample input images
│   ├── models/                Downloaded ONNX models (ignored by Git)
│   ├── wheelhouse/            Offline Python wheels, lock and checksums (ignored by Git)
│   ├── templates/generated/   Generated reference layout (ignored by Git)
│   ├── main.py                FastAPI endpoints
│   ├── service.py             Adapter around the existing pipeline
│   └── legacy_streamlit.py    Previous interface for comparison
└── README.md
```

The OCR virtual environment is `ocr_service/.venv/` and is ignored by Git. Model and generated layout paths are resolved from `ocr_service/`, regardless of the shell's working directory. No OCR algorithm, field mapping, or processing threshold was changed during the folder reorganization.

## Requirements and setup

Use 64-bit Python 3.11+, .NET SDK 10, and Node.js 22.12+. A GPU is not required. Run these commands in PowerShell from the repository root for an online setup:

```powershell
python -m venv ocr_service\.venv
.\ocr_service\.venv\Scripts\python.exe -m pip install -r ocr_service\requirements.txt
.\ocr_service\.venv\Scripts\python.exe ocr_service\scripts\download_rapidocr_models.py
dotnet build backend\FasOcr.Api\FasOcr.Api.csproj
cd frontend
npm.cmd install
cd ..
```

The model downloader checks SHA-256 hashes. The default ONNX files are under `ocr_service/models/rapidocr-ppocrv5-en/`. Use `ocr_service/.env.example` for optional model path overrides; the Python service does not load `.env` files automatically. The supplied reference form is `ocr_service/assets/MOE_FAS_Application_Form.pdf`.

## Prepare and install OCR offline

On a **connected Windows 64-bit machine with the same CPython major/minor version as the target**, download the models as above and build the wheelhouse:

```powershell
python ocr_service\scripts\build_wheelhouse.py
python ocr_service\scripts\install_offline.py --verify-only
python ocr_service\scripts\package_offline.py
```

This workspace's bundle was built for **CPython 3.12, Windows x64**. It contains 65 wheels (about 230 MiB), `requirements.lock`, a SHA-256 manifest, the reference PDF and two local ONNX model files in their normal folders. The builder downloads binary wheels for every direct and transitive Python requirement and checks that pip can resolve all packages using only those files. Rebuild for a different Python version or platform on a connected machine. `--refresh` replaces a previous wheelhouse after dependencies change.

Copy the generated `ocr_service-win-amd64-py312.zip` to the offline machine and extract it; the ZIP excludes `.venv/` and includes the wheelhouse, models, PDF, source and instructions. You can also copy the **entire `ocr_service/` folder**, omitting `.venv/`. Include the ignored `wheelhouse/` and `models/` folders; a Git clone alone will not contain them. The target must already have matching 64-bit Python installed. In PowerShell, from the parent folder of `ocr_service/`:

```powershell
python ocr_service\scripts\install_offline.py
.\ocr_service\.venv\Scripts\python.exe -m uvicorn ocr_service.main:app --host 127.0.0.1 --port 8000
```

The installer verifies Python compatibility, wheel/model/PDF checksums, installs with `--no-index`, runs `pip check`, and starts the OCR service class once as a smoke test. No package index or model download is used. This wheelhouse covers **Python OCR service dependencies only**; .NET SDK/NuGet and Node/npm must be provisioned separately if the gateway and React app also run on the offline machine.

## Run the three services

Open three PowerShell windows at the repository root, then run one command in each:

```powershell
.\ocr_service\.venv\Scripts\python.exe -m uvicorn ocr_service.main:app --host 127.0.0.1 --port 8000
```

```powershell
dotnet run --project backend\FasOcr.Api --urls http://127.0.0.1:5100
```

```powershell
cd frontend
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. React calls only the ASP.NET gateway. The gateway URL is set by `frontend/.env.example`; copy it to `frontend/.env.local` if needed. Upstream URL, timeout, upload limit, and browser origins are in `backend/FasOcr.Api/appsettings.json`.

Check `http://127.0.0.1:8000/ready` for OCR readiness and `http://127.0.0.1:5100/health` for gateway health. The OCR process loads the local models once. After models have been downloaded, processing needs no internet connection.

## Form input and review

Upload one completed PDF containing at least pages 1–3, or three complete PNG/JPEG page images selected in page order. The maximum is 25 MB total. The reference PDF has five pages; pages 4–5 are instructions and contain no answer regions. The current layout has 79 fields on pages 1–3. Only `applicant_date_of_birth` uses the date type and requires a real `DD/MM/YYYY` date. All other values are strings; there are no checkboxes.

The browser shows the original image or PDF preview, elapsed OCR time, field statuses, warnings, and any raw transcript from a page that could not be aligned. Only `EXTRACTED` values are filled automatically; every field can be corrected. Replacing the upload prevents an older OCR response from changing the new review. Confirmation checks required fields and date of birth, then downloads reviewed values as JSON. The demo does not persist OCR results or uploaded forms in a database.

Use a full page PDF export or original camera images for best results. Verify all handwritten values and signatures against the document. OCR transcribes text; it does not verify a signature.

The generated reference layout lives in `ocr_service/templates/generated/form_layout.json`. If the printed PDF changes, update `ocr_service/pipeline/template.py`, regenerate the layout, and inspect the answer regions. The legacy Streamlit interface can do the layout inspection:

```powershell
.\ocr_service\.venv\Scripts\python.exe -m streamlit run ocr_service\legacy_streamlit.py
```

## HTTP API

| Service | Method and path | Purpose |
| --- | --- | --- |
| FastAPI | `GET /health`, `GET /ready` | Health and model readiness |
| FastAPI | `GET /api/v1/forms/current` | Current form schema and field definitions |
| FastAPI | `POST /api/v1/ocr/extract` | OCR using repeated multipart `file` fields |
| ASP.NET | `GET /health` | Gateway health |
| ASP.NET | `GET /api/v1/fas/form` | Validated schema proxy |
| ASP.NET | `POST /api/v1/fas/ocr` | Validated multipart OCR proxy |

The ASP.NET gateway also serves **Swagger UI at `http://127.0.0.1:5100/swagger`** and its OpenAPI JSON at `/swagger/v1/swagger.json`. In Swagger's OCR operation, choose one PDF or three page images in the `file` control. Swagger UI is bundled with the .NET package and needs no browser CDN connection.

The OCR response includes the request ID, processing status, form version, page metadata, model and timing, field values/status/evidence/issues, validation results, and unaligned transcripts. Errors return `{ "code": "...", "message": "..." }` with an appropriate HTTP status. The browser never calls FastAPI directly.

## Tests

Run from the repository root:

```powershell
.\ocr_service\.venv\Scripts\python.exe -m pytest -q ocr_service\tests
dotnet run --project backend\FasOcr.Api.Tests
dotnet build backend\FasOcr.Api\FasOcr.Api.csproj
cd frontend
npm.cmd test
npm.cmd run build
```

The tests cover Python pipeline and FastAPI upload behavior, gateway validation and upstream failures, and React upload/review state. The supplied blank PDF has also been sent through both running APIs to verify that all 79 fields and their evidence survive the full route.
