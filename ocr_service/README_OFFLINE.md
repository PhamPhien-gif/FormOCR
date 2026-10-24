# Offline OCR installation (Windows x64)

This directory contains local ONNX models and a Python wheelhouse. The wheelhouse was built for the exact Python major/minor and platform recorded in `wheelhouse/manifest.json`.

1. Install matching 64-bit CPython on the target machine. This bundle targets CPython 3.12 on Windows x64.
2. Extract the ZIP so this folder is named `ocr_service`.
3. In PowerShell, change to the parent folder of `ocr_service` and run:

```powershell
python ocr_service\scripts\install_offline.py
.\ocr_service\.venv\Scripts\python.exe -m uvicorn ocr_service.main:app --host 127.0.0.1 --port 8000
```

The installer checks all wheel, model, and reference PDF hashes before creating `.venv`. It installs with `--no-index`, then runs `pip check` and an OCR startup check. It requires no network connection. Open `http://127.0.0.1:8000/ready` to check service readiness.

The wheelhouse covers Python OCR service dependencies. The ASP.NET gateway and React frontend, if needed on the target machine, require their own .NET and Node dependencies.
