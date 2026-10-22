# FormOCR — MOE FAS application form

Local Streamlit demo for extracting handwritten text from the supplied five-page `MOE_FAS_Application_Form.pdf`. It uses [RapidOCR](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/usage/) with PP-OCRv5 mobile detection and English recognition ONNX models on CPU. The models are downloaded once; processing needs no network connection.

## Windows setup

Use 64-bit Python 3.11 or newer. In PowerShell, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\download_rapidocr_models.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The download script verifies SHA-256 checksums and saves the ONNX files under `models/rapidocr-ppocrv5-en/`. That directory and `.venv/` are ignored by Git. On this workspace the models are already downloaded. To place the models elsewhere, set `FORM_OCR_DETECTOR_PATH` and `FORM_OCR_RECOGNIZER_PATH` in the shell or edit [config/app.yaml](config/app.yaml). [.env.example](.env.example) documents the variables; it is not loaded automatically.

## Form layout and fields

In **Template setup**, generate the layout from the supplied PDF, inspect the red boxes on pages 1–3, and save verification for each page. The generated layout is `templates/generated/form_layout.json` and contains 79 fields:

| Page | Data |
| --- | --- |
| 1 | Submission school, applicant particulars, and five child/school rows |
| 2 | Eight household member rows and total gross household income |
| 3 | Declaration name/NRIC/signature and declaration date |

Pages 4–5 are annex instructions and contain no answer regions. Section II household rows can remain empty when the printed instructions say they do not apply. Only `applicant_date_of_birth` has the `date` type and must be a real date in `dd/mm/yyyy` format. Every other value, including ages, income, contact numbers and declaration date, is a string. There are no checkbox fields.

The reference layout is specific to this version of the PDF. If its printed cell positions change, update [src/template.py](src/template.py), regenerate the layout, and inspect it again. Regenerating clears verification. The layout is ignored by Git because it is a generated file.

## Process and review

In **Process form**, choose **Upload files** or **Local file paths**. Provide either one completed PDF with pages 1–3 or three full-page images for pages 1, 2 and 3 in that order. For local paths, enter one path per line; relative paths start at the repository root, and absolute paths point to files on the machine running Streamlit. Both methods read the same original image bytes. Pages 4–5 in a PDF are ignored. The app checks quality, aligns image uploads with the blank reference, runs the local OCR engine on pages 1–3, and assigns OCR text to cell regions. A PDF rendered at the reference size uses its page geometry directly. The status panel shows each stage and elapsed time; after one run it shows the previous run duration as a rough reference.

The preview displays the original image at its native size. PNG uploads stay lossless in the preview; use **Download original image** to compare it with the source file. The former 700×900 px check was an application heuristic, not a RapidOCR or PP-OCRv5 model limit. It has been removed. The app first aligns images with ORB, then tries SIFT for photographed or small page exports. Aligned OCR text is assigned to form fields. If alignment still fails, the app shows the raw transcript for manual review without assigning text to uncertain fields. OCR can miss or misread details. Reading by local path and enlarging a small crop do not increase its resolution. For the most reliable input, export the filled Word document as a complete PDF. For photos, capture each entire page including its corners in even light, hold the camera square to the page, use the camera's original resolution, and upload the original JPEG/PNG.

Review every extracted value, especially handwritten text and the signature. OCR is a transcription aid and does not verify a handwritten signature. Empty optional cells remain empty strings in the final JSON. Required applicant fields and the first child row must be completed in review. Use **Confirm and generate JSON** to download the reviewed values.

The `src/` modules can be used without Streamlit. `src/core.py` defines the result contracts and validation. The image quality thresholds in [config/app.yaml](config/app.yaml) are screening heuristics; photographs with poor alignment may need recapture.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests cover layout generation, field types, date validation, and OCR text assignment. The local models were also run on the blank supplied PDF. Recognition accuracy on completed handwriting still requires representative filled forms and human review.
