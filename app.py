"""Streamlit interface for template setup, OCR, and human review."""
from __future__ import annotations

import io
import json
import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

from src.core import Decision, validate_review
from src.image_processing import assess_quality, overlay
from src.model_manager import LocalModelManager
from src.pipeline import Processor, load_config
from src.template import Template, build_template, load_template, preview, save_template


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
st.set_page_config(page_title="Form OCR", layout="wide")
config = load_config()
layout_path = Path(config["form"]["layout_path"])


@st.cache_resource(show_spinner=False)
def get_model_manager():
    return LocalModelManager()


def clear_attempt():
    for key in ("result", "debug", "completed", "comparison", "inference_device", "processing_log"):
        st.session_state.pop(key, None)


st.title("Template-based handwritten form OCR")
setup, process = st.tabs(["Template setup", "Process form"])
with setup:
    st.subheader("Reference template")
    pdf_path = Path(config["form"]["template_path"])
    if not pdf_path.exists():
        st.error(f"Reference PDF missing: {pdf_path}")
    elif st.button("Generate template from PDF"):
        try:
            build_template(pdf_path, layout_path, config["form"]["type"], config["form"]["version"])
            st.success("Template generated. Inspect every box before processing forms.")
        except Exception as exc:
            st.error(str(exc))
    if layout_path.exists():
        try:
            template = load_template(layout_path)
            st.image(preview(template), caption="Red: field regions; blue: checkbox regions", width="stretch")
            st.caption(f"{template.form_type} v{template.form_version}; {template.width} × {template.height} pixels")
            with st.form("edit_template"):
                edited = template.model_copy(deep=True)
                for field_id, region in edited.fields.items():
                    st.markdown(f"**{field_id}**")
                    values = st.columns(4)
                    region.box = tuple(int(values[i].number_input(label, value=region.box[i], step=1, key=f"{field_id}_{label}")) for i, label in enumerate(("x1", "y1", "x2", "y2")))
                    for option, box in region.options.items():
                        cols = st.columns(4)
                        region.options[option] = tuple(int(cols[i].number_input(f"{option} {label}", value=box[i], step=1, key=f"{field_id}_{option}_{label}")) for i, label in enumerate(("x1", "y1", "x2", "y2")))
                if st.form_submit_button("Save verified coordinates"):
                    try:
                        validated = Template.model_validate(edited.model_dump())
                        validated.verified = True
                        save_template(validated, layout_path)
                        st.success("Template saved")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        except Exception as exc:
            st.error(f"Template configuration error: {exc}")

with process:
    if not layout_path.exists():
        st.info("Generate and verify the template in the Template setup tab first.")
        st.stop()
    template = load_template(layout_path)
    if not template.verified:
        st.warning("Inspect the template boxes and click Save verified coordinates before processing.")
        st.stop()
    st.caption(f"Form: {template.form_type} • Template version: {template.form_version}")
    selected_model = st.selectbox("OCR model", ["Qwen3-VL-2B Q4_K_M", "PaddleOCR-VL-1.6"], on_change=clear_attempt)
    provider = "paddle" if selected_model == "PaddleOCR-VL-1.6" else "qwen"
    st.caption(f"Model: {config['paddle_model' if provider == 'paddle' else 'model']['model_id']} | local GGUF | CPU | offline inference")
    if provider == "paddle":
        st.caption("PaddleOCR-VL transcribes text; checkbox marks and crossed-out handwriting still need careful human review.")
    mode = st.selectbox("Extraction mode", ["auto", "template_aligned", "full_page", "compare"], help="Auto uses aligned crops for Qwen and a full page for PaddleOCR-VL. Compare runs both modes.")
    upload = st.file_uploader("Upload a completed form photo", type=["jpg", "jpeg", "png"], on_change=clear_attempt)
    if upload:
        image_bytes = upload.getvalue()
        try:
            opened = Image.open(io.BytesIO(image_bytes))
            if opened.format not in {"JPEG", "PNG"}:
                raise UnidentifiedImageError("Only JPEG and PNG are supported")
            image = ImageOps.exif_transpose(opened).convert("RGB")
        except UnidentifiedImageError:
            st.error("Unsupported or corrupt image")
            st.stop()
        st.image(image, caption="Original uploaded image", width=500)
        if st.button("Process image", type="primary"):
            clear_attempt()
            settings = config["paddle_model" if provider == "paddle" else "model"]
            started = time.perf_counter()
            timeline = []
            with st.status("Checking image quality...", expanded=True) as progress:
                clock = st.empty()
                try:
                    initial_quality = assess_quality(image, len(image_bytes), config["quality"])
                    timeline.append(f"Image quality: {initial_quality.status} ({time.perf_counter() - started:.1f}s)")
                    progress.write(timeline[-1])
                    if initial_quality.status != "RECAPTURE_REQUIRED":
                        progress.update(label="Loading local OCR model...")
                    manager = get_model_manager()
                    events = queue.Queue()

                    def run_processing():
                        with manager.lock:
                            def report(stage):
                                events.put((stage, time.perf_counter()))

                            if initial_quality.status == "RECAPTURE_REQUIRED":
                                model = None
                            else:
                                report("Loading local OCR model")
                                model = manager.get(provider, settings)
                                report(f"{selected_model} ready")
                            processor = Processor(template, config, model)
                            if mode == "compare" and model is not None:
                                first, first_debug = processor.process(image, len(image_bytes), "template_aligned", lambda stage: report(f"Aligned: {stage}"))
                                second, second_debug = processor.process(image, len(image_bytes), "full_page", lambda stage: report(f"Full page: {stage}"))
                                comparison = {"template_aligned": first.model_dump(mode="json"), "full_page": second.model_dump(mode="json")}
                                total_inference = first_debug.get("inference_seconds", 0) + second_debug.get("inference_seconds", 0)
                                return first, first_debug, comparison, total_inference, model.device
                            result, debug = processor.process(image, len(image_bytes), mode, report)
                            return result, debug, None, debug.get("inference_seconds", 0), model.device if model is not None else None

                    process_started = time.perf_counter()
                    estimate_key = (provider, mode)
                    previous_seconds = st.session_state.get("processing_seconds_by_mode", {}).get(estimate_key)
                    current_stage = "Preparing OCR"
                    stage_started = process_started
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(run_processing)
                        while not future.done() or not events.empty():
                            while not events.empty():
                                next_stage, event_time = events.get_nowait()
                                timeline.append(f"{current_stage}: {event_time - stage_started:.1f}s")
                                progress.write(timeline[-1])
                                current_stage, stage_started = next_stage, event_time
                                progress.update(label=f"{current_stage}...")
                            elapsed = time.perf_counter() - process_started
                            if previous_seconds is None:
                                estimate = f"No reliable ETA on the first run; OCR request timeout is {settings['inference_timeout_seconds']}s"
                            elif elapsed < previous_seconds:
                                estimate = f"Estimated remaining: ~{previous_seconds - elapsed:.0f}s (previous run in this session)"
                            else:
                                estimate = f"Past previous run by {elapsed - previous_seconds:.0f}s; still processing"
                            clock.caption(f"Current stage: {current_stage} ({time.perf_counter() - stage_started:.0f}s) | Processing elapsed: {elapsed:.0f}s | {estimate}")
                            if not future.done():
                                time.sleep(1)
                        result, debug, comparison, total_inference, device = future.result()
                    processing_seconds = time.perf_counter() - process_started
                    timeline.append(f"{current_stage}: {time.perf_counter() - stage_started:.1f}s")
                    progress.write(timeline[-1])
                    timeline.append(f"Completed in {time.perf_counter() - started:.1f}s total; processing: {processing_seconds:.1f}s; model inference: {total_inference:.1f}s")
                    clock.caption(timeline[-1])
                    if device is not None:
                        st.session_state["inference_device"] = device
                    if total_inference > 0:
                        st.session_state.setdefault("processing_seconds_by_mode", {})[estimate_key] = processing_seconds
                    st.session_state["result"] = result
                    st.session_state["debug"] = debug
                    st.session_state["processing_log"] = timeline
                    if comparison is not None:
                        st.session_state["comparison"] = comparison
                    progress.update(label=f"Processing complete in {time.perf_counter() - started:.1f}s", state="complete", expanded=True)
                except Exception as exc:
                    progress.update(label="Processing failed", state="error", expanded=True)
                    st.error(f"Model or processing error: {exc}")
        result = st.session_state.get("result")
        if result:
            st.subheader("Image quality and form validation")
            st.write(result.image_quality.status, result.image_quality.metrics)
            st.write("Template match:", result.document["template_match"])
            st.write("OCR model:", result.document.get("ocr_model") or selected_model)
            st.write("Decision:", result.processing["status"])
            if st.session_state.get("inference_device") == "cpu":
                st.caption("Selected GGUF model ran locally on CPU.")
            for issue in result.image_quality.issues:
                st.warning(issue.message)
            for issue in result.validation["issues"]:
                st.error(issue["message"])
            debug = st.session_state.get("debug", {})
            if debug.get("aligned_image") is not None:
                st.image(overlay(debug["aligned_image"], template), caption="Aligned image and field boxes", width=600)
            if result.processing["status"] in {Decision.RECAPTURE_REQUIRED, Decision.NEW_FORM_REQUIRED}:
                st.info("Upload a new photo." if result.processing["status"] == Decision.RECAPTURE_REQUIRED else "Complete a new paper form, then upload its photo.")
            if result.processing["status"] == Decision.REVIEW_REQUIRED:
                fields = result.extraction["fields"]
                st.subheader("OCR results and human review")
                for key, field in fields.items():
                    st.write(f"{key}: {field.status} | raw: {field.raw_value!r} | normalized: {field.normalized_value!r}")
                with st.form("review"):
                    date = st.text_input("Date (DD/MM/YYYY)", value=str(fields["date"].normalized_value or ""))
                    name = st.text_input("Name", value=str(fields["name"].normalized_value or ""))
                    age = st.text_input("Age", value=str(fields["age"].normalized_value if fields["age"].normalized_value is not None else ""))
                    choices = ["", "Male", "Female"]
                    gender = st.radio("Gender", choices, index=choices.index(fields["gender"].normalized_value or ""), format_func=lambda value: "Select…" if value == "" else value)
                    if st.form_submit_button("Confirm & Auto-fill", type="primary"):
                        values, issues = validate_review({"date": date, "name": name, "age": age, "gender": gender}, config["validation"])
                        if issues:
                            for issue in issues:
                                st.error(issue.message)
                        else:
                            result.review = {"status": "CONFIRMED", "reviewed_values": values}
                            result.processing["status"] = Decision.COMPLETED
                            result.debug.setdefault("stage_history", []).append("COMPLETED")
                            st.session_state["completed"] = values
                if st.session_state.get("completed"):
                    st.subheader("Auto-fill result")
                    st.json(st.session_state["completed"])
                    st.download_button("Download final JSON", json.dumps(st.session_state["completed"], indent=2), "form_data.json", "application/json")
            with st.expander("Extraction JSON"):
                st.json(result.model_dump(mode="json"))
            with st.expander("Developer diagnostics"):
                for entry in st.session_state.get("processing_log", []):
                    st.write(entry)
                if st.session_state.get("comparison"):
                    st.json(st.session_state["comparison"])
                st.write("Mode:", debug.get("mode"))
                st.write("Alignment:", debug.get("alignment"))
                st.write("Inference seconds:", debug.get("inference_seconds"))
                st.code(debug.get("model_raw_output", ""), language="json")
                for key, crop in debug.get("crops", {}).items():
                    st.image(crop, caption=key)
