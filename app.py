"""Streamlit UI for the MOE FAS template and offline OCR."""
from __future__ import annotations

import json
import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

from src.core import Decision, validate_review
from src.image_processing import overlay
from src.input_files import load_local_paths, read_inputs
from src.inference import RapidOCRAdapter
from src.pipeline import Processor, load_config
from src.template import Template, build_template, load_template, preview, save_template

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
st.set_page_config(page_title="MOE FAS Form OCR", layout="wide")
config = load_config()
layout_path = Path(config["form"]["layout_path"])


@st.cache_resource(show_spinner=False)
def get_model(detector_path: str, recognizer_path: str):
    return RapidOCRAdapter(detector_path, recognizer_path)


def clear_attempt():
    for key in ("result", "debug", "completed", "processing_log"):
        st.session_state.pop(key, None)


if layout_path.exists():
    layout_revision = layout_path.stat().st_mtime_ns
    if st.session_state.get("layout_revision") != layout_revision:
        clear_attempt()
        st.session_state["layout_revision"] = layout_revision


st.title("MOE FAS handwritten form OCR")
setup, process = st.tabs(["Template setup", "Process form"])
with setup:
    pdf_path = Path(config["form"]["template_path"])
    if not pdf_path.exists():
        st.error(f"Reference PDF missing: {pdf_path}")
    elif st.button("Generate layout from MOE FAS PDF"):
        try:
            build_template(pdf_path, layout_path, config["form"]["type"], config["form"]["version"])
            clear_attempt()
            st.success("Layout generated. Check the red boxes on pages 1–3.")
        except Exception as exc:
            st.error(str(exc))
    if layout_path.exists():
        try:
            template = load_template(layout_path)
            st.caption(f"{len(template.fields)} string/date fields across pages 1–3. Pages 4–5 contain instructions only.")
            page_number = st.selectbox("Page to inspect", [1, 2, 3])
            st.image(preview(template, page_number), caption=f"Page {page_number}: red rectangles are OCR regions",
                     width="content", output_format="PNG")
            st.caption(f"Verified pages: {', '.join(map(str, template.verified_pages)) or 'none'}")
            with st.form(f"edit_template_{page_number}"):
                edited = template.model_copy(deep=True)
                for key, region in edited.fields.items():
                    if region.page != page_number:
                        continue
                    st.markdown(f"**{region.label}** (`{key}`)")
                    columns = st.columns(4)
                    region.box = tuple(int(columns[i].number_input(label, value=region.box[i], step=1,
                                                                      key=f"{page_number}_{key}_{label}"))
                                       for i, label in enumerate(("x1", "y1", "x2", "y2")))
                if st.form_submit_button(f"Save and verify page {page_number}"):
                    try:
                        edited.verified_pages = sorted(set(edited.verified_pages) | {page_number})
                        edited.verified = set(edited.verified_pages) >= {1, 2, 3}
                        validated = Template.model_validate(edited.model_dump())
                        save_template(validated, layout_path)
                        st.success(f"Page {page_number} saved")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        except Exception as exc:
            st.error(f"Layout error: {exc}")

with process:
    if not layout_path.exists():
        st.info("Generate the layout in Template setup first.")
        st.stop()
    template = load_template(layout_path)
    if not template.verified:
        st.warning("Inspect and verify each of pages 1–3 in Template setup first.")
        st.stop()
    st.caption("RapidOCR + PP-OCRv5 English · local CPU · no model download during processing")
    input_method = st.radio("Image source", ["Upload files", "Local file paths"], horizontal=True, on_change=clear_attempt)
    if input_method == "Upload files":
        files = st.file_uploader("Upload one completed PDF or three full-page images in order", type=["pdf", "jpg", "jpeg", "png"],
                                 accept_multiple_files=True, on_change=clear_attempt)
    else:
        path_lines = st.text_area("Local paths: one PDF or three full-page images, one path per line",
                                  placeholder="D:\\Github\\FormOCR\\Image1.png\nD:\\Github\\FormOCR\\Image2.png\nD:\\Github\\FormOCR\\Image3.png",
                                  on_change=clear_attempt)
        try:
            files = load_local_paths(path_lines)
        except ValueError as exc:
            st.error(str(exc))
            files = []
        st.caption("Paths are read by the Streamlit process on this computer. They use the same pixels as upload.")
    if files:
        try:
            images, byte_count, source_kind = read_inputs(files)
        except Exception as exc:
            st.error(f"Input error: {exc}")
            st.stop()
        st.write(f"Loaded {len(images)} pages for OCR")
        st.caption("No minimum image size. If template alignment fails, OCR will still run and show raw text for manual review.")
        preview_page = st.selectbox("Preview page", range(1, len(images) + 1))
        preview_image = images[preview_page - 1]
        st.caption(f"Page {preview_page}: {preview_image.width} × {preview_image.height} pixels. Preview at original size; no display compression.")
        if source_kind == "images":
            original_file = files[preview_page - 1]
            original_bytes = original_file.getvalue()
            original_format = "PNG" if original_file.name.lower().endswith(".png") else "JPEG"
            st.image(original_bytes, caption=original_file.name, width="content", output_format=original_format)
            st.download_button("Download original image", original_bytes, file_name=original_file.name)
        else:
            st.image(preview_image, caption=f"PDF page {preview_page}", width="content", output_format="PNG")
        if st.button("Process form", type="primary"):
            clear_attempt()
            events = queue.Queue()
            started = time.perf_counter()
            with st.status("Preparing local OCR", expanded=True) as progress:
                clock = st.empty()

                def work():
                    events.put("Loading local OCR models")
                    model = get_model(config["ocr"]["detector_path"], config["ocr"]["recognizer_path"])
                    return Processor(template, config, model).process(images, byte_count, source_kind, events.put)

                try:
                    previous = st.session_state.get("previous_processing_seconds")
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(work)
                        stage = "Preparing"
                        stage_started = started
                        timeline = []
                        while not future.done() or not events.empty():
                            while not events.empty():
                                next_stage = events.get_nowait()
                                timeline.append(f"{stage}: {time.perf_counter() - stage_started:.1f}s")
                                progress.write(timeline[-1])
                                stage, stage_started = next_stage, time.perf_counter()
                                progress.update(label=stage)
                            elapsed = time.perf_counter() - started
                            estimate = "First run: no ETA" if previous is None else f"Previous run: {previous:.0f}s"
                            clock.caption(f"{stage} · stage {time.perf_counter() - stage_started:.0f}s · total {elapsed:.0f}s · {estimate}")
                            if not future.done():
                                time.sleep(0.5)
                        result, debug = future.result()
                    elapsed = time.perf_counter() - started
                    timeline.append(f"{stage}: {time.perf_counter() - stage_started:.1f}s")
                    timeline.append(f"Completed in {elapsed:.1f}s; OCR {debug.get('inference_seconds', 0):.1f}s")
                    st.session_state.update(result=result, debug=debug, processing_log=timeline,
                                            previous_processing_seconds=elapsed)
                    progress.update(label=f"Complete in {elapsed:.1f}s", state="complete")
                except Exception as exc:
                    progress.update(label="Processing failed", state="error")
                    st.error(str(exc))
        result = st.session_state.get("result")
        if result:
            st.subheader("Processing result")
            st.write("Decision:", result.processing["status"])
            st.write("Image quality:", result.image_quality.status)
            for issue in result.image_quality.issues:
                st.warning(issue.message)
            for issue in result.validation["issues"]:
                st.warning(issue["message"])
            debug = st.session_state.get("debug", {})
            if debug.get("unaligned_pages"):
                st.subheader("Raw OCR text from unaligned pages")
                st.caption("These pages were read directly. Text is not assigned to form fields; compare it with the image and enter confirmed values in the review form.")
                raw_lines = json.loads(debug.get("model_raw_output", "{}")).get("lines", [])
                for page_number in debug["unaligned_pages"]:
                    transcript = "\n".join(line["text"] for line in raw_lines if line["page"] == page_number)
                    st.text_area(f"Page {page_number} OCR transcript", value=transcript or "No text detected", height=220, disabled=True)
            for page_number, image in debug.get("aligned_images", {}).items():
                with st.expander(f"Aligned page {page_number} with OCR regions"):
                    st.image(overlay(image, template, page_number), width="content", output_format="PNG")
            if result.processing["status"] == Decision.RECAPTURE_REQUIRED:
                st.info("Check the page order and upload a clearer form if needed.")
            if result.processing["status"] == Decision.REVIEW_REQUIRED:
                st.subheader("Review extracted values")
                st.caption("Only applicant date of birth is validated as DD/MM/YYYY. Other values remain strings. Verify signatures visually.")
                with st.form("review_values"):
                    reviewed = {}
                    fields = result.extraction["fields"]
                    for section in dict.fromkeys(region.section for region in template.fields.values()):
                        with st.expander(section, expanded=section == "Applicant"):
                            for key, region in template.fields.items():
                                if region.section != section:
                                    continue
                                value = fields[key].normalized_value or fields[key].raw_value or ""
                                suffix = " (DD/MM/YYYY)" if region.data_type == "date" else ""
                                reviewed[key] = st.text_input(region.label + suffix, value=value, key=f"review_{key}")
                    if st.form_submit_button("Confirm and generate JSON", type="primary"):
                        values, issues = validate_review(reviewed, template.fields, config["validation"])
                        if issues:
                            for issue in issues:
                                st.error(issue.message)
                        else:
                            result.review = {"status": "CONFIRMED", "reviewed_values": values}
                            result.processing["status"] = Decision.COMPLETED
                            st.session_state["completed"] = values
                if st.session_state.get("completed"):
                    st.json(st.session_state["completed"])
                    st.download_button("Download final JSON", json.dumps(st.session_state["completed"], ensure_ascii=False, indent=2),
                                       "moe_fas_data.json", "application/json")
            with st.expander("Diagnostics"):
                for entry in st.session_state.get("processing_log", []):
                    st.write(entry)
                st.write("Alignment:", debug.get("alignments"))
                st.write("OCR seconds:", debug.get("inference_seconds"))
                st.code(debug.get("model_raw_output", ""), language="json")
