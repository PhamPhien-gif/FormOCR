"""Conservative image checks and geometric registration."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from ocr_service.pipeline.core import Issue, QualityResult
from ocr_service.pipeline.template import Template


def assess_quality(image: Image.Image, byte_count: int, config: dict) -> QualityResult:
    image = ImageOps.exif_transpose(image).convert("RGB")
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    metrics = {"blur_score": float(cv2.Laplacian(gray, cv2.CV_64F).var()), "brightness_score": float(gray.mean()),
               "dark_pixel_ratio": float((gray < 180).mean()), "width": float(image.width), "height": float(image.height)}
    issues = []
    if byte_count > config.get("max_bytes", 15_000_000):
        issues.append(Issue(code="FILE_TOO_LARGE", message="Image exceeds configured size", severity="ERROR"))
    min_width, min_height = config.get("min_width", 0), config.get("min_height", 0)
    if (min_width and min(image.size) < min_width) or (min_height and max(image.size) < min_height):
        issues.append(Issue(code="LOW_RESOLUTION", message=f"Image is {image.width}×{image.height} px; OCR can still be tried"))
    if metrics["blur_score"] < config.get("min_blur", 35):
        issues.append(Issue(code="POSSIBLE_BLUR", message="Image may be blurry"))
    if metrics["brightness_score"] < config.get("min_brightness", 45) or (metrics["brightness_score"] > config.get("max_brightness", 225) and metrics["dark_pixel_ratio"] < 0.003):
        issues.append(Issue(code="EXPOSURE", message="Image exposure may be unsuitable"))
    severe = any(issue.severity == "ERROR" for issue in issues)
    return QualityResult(status="RECAPTURE_REQUIRED" if severe else "NEEDS_REVIEW" if issues else "ACCEPTED", metrics=metrics, issues=issues)


@dataclass
class Alignment:
    image: Image.Image | None
    reliable: bool
    diagnostics: dict


def align(image: Image.Image, template: Template, page_number: int = 1) -> Alignment:
    reference = cv2.imread(template.reference_image_paths[page_number - 1])
    source = cv2.cvtColor(np.asarray(ImageOps.exif_transpose(image).convert("RGB")), cv2.COLOR_RGB2BGR)
    original_source = source
    if reference is None:
        return Alignment(None, False, {"reason": "Reference image unavailable"})
    # First isolate a photographed sheet where a four-corner contour is visible.
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(polygon) == 4 and cv2.contourArea(polygon) > 0.35 * source.shape[0] * source.shape[1]:
            pts = polygon[:, 0, :].astype(np.float32)
            sums, diffs = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
            ordered = np.array([pts[np.argmin(sums)], pts[np.argmin(diffs)], pts[np.argmax(sums)], pts[np.argmax(diffs)]], dtype=np.float32)
            dest = np.array([[0, 0], [template.width - 1, 0], [template.width - 1, template.height - 1], [0, template.height - 1]], dtype=np.float32)
            warped = cv2.warpPerspective(source, cv2.getPerspectiveTransform(ordered, dest), (template.width, template.height))
            source = warped
            break
    orb = cv2.ORB_create(nfeatures=3000)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    best = Alignment(None, False, {"reason": "Insufficient feature matches"})
    for rotation in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        candidate = source if rotation is None else cv2.rotate(source, rotation)
        kp1, d1 = orb.detectAndCompute(cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY), None)
        kp2, d2 = orb.detectAndCompute(reference_gray, None)
        if d1 is None or d2 is None or len(kp1) < 8 or len(kp2) < 8:
            continue
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
        good = [a for a, b in pairs if a.distance < 0.75 * b.distance]
        if len(good) < 8:
            continue
        src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5)
        if matrix is None or mask is None:
            continue
        inliers = int(mask.sum())
        corners = cv2.perspectiveTransform(np.float32([[[0, 0], [candidate.shape[1], 0], [candidate.shape[1], candidate.shape[0]], [0, candidate.shape[0]]]]), matrix)[0]
        projected_area = abs(cv2.contourArea(corners))
        plausible = inliers >= 8 and inliers / len(good) >= 0.45 and 0.35 * template.width * template.height < projected_area < 2.5 * template.width * template.height and cv2.isContourConvex(corners.astype(np.float32))
        if plausible and (not best.reliable or inliers > best.diagnostics.get("inliers", 0)):
            aligned = cv2.warpPerspective(candidate, matrix, (template.width, template.height))
            best = Alignment(Image.fromarray(cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)), True, {"matches": len(good), "inliers": inliers, "rotation": str(rotation), "projected_area": projected_area})
    if best.reliable:
        return best

    # SIFT is more tolerant of photographed screens and small document exports.
    # It can register a partial page when enough printed labels and table lines remain.
    sift = cv2.SIFT_create(nfeatures=4000)
    reference_points, reference_descriptors = sift.detectAndCompute(reference_gray, None)
    if reference_descriptors is None:
        return best
    for rotation in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        candidate = original_source if rotation is None else cv2.rotate(original_source, rotation)
        source_points, source_descriptors = sift.detectAndCompute(cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY), None)
        if source_descriptors is None:
            continue
        pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(source_descriptors, reference_descriptors, k=2)
        good = [a for a, b in pairs if a.distance < 0.72 * b.distance]
        if len(good) < 12:
            continue
        src = np.float32([source_points[m.queryIdx].pt for m in good])
        dst = np.float32([reference_points[m.trainIdx].pt for m in good])
        affine, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                    ransacReprojThreshold=5, maxIters=10000, confidence=0.999)
        if affine is None or mask is None:
            continue
        matrix = np.vstack((affine, [0, 0, 1]))
        inliers = int(mask.sum())
        corners = cv2.perspectiveTransform(np.float32([[[0, 0], [candidate.shape[1], 0],
                                                        [candidate.shape[1], candidate.shape[0]], [0, candidate.shape[0]]]]), matrix)[0]
        projected_area = abs(cv2.contourArea(corners))
        plausible = (inliers >= 10 and inliers / len(good) >= 0.3
                     and 0.3 * template.width * template.height < projected_area < 2.5 * template.width * template.height
                     and cv2.isContourConvex(corners.astype(np.float32)))
        if plausible and (not best.reliable or inliers > best.diagnostics.get("inliers", 0)):
            aligned = cv2.warpPerspective(candidate, matrix, (template.width, template.height))
            best = Alignment(Image.fromarray(cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)), True,
                             {"method": "SIFT affine", "matches": len(good), "inliers": inliers,
                              "rotation": str(rotation), "projected_area": projected_area})
    return best


def crops(image: Image.Image, template: Template, padding_ratio: float, page_number: int = 1) -> dict[str, Image.Image]:
    output = {}
    for key, region in template.fields.items():
        if region.page != page_number:
            continue
        x1, y1, x2, y2 = region.box
        pad_x, pad_y = round((x2 - x1) * padding_ratio), round((y2 - y1) * padding_ratio)
        output[key] = image.crop((max(0, x1 - pad_x), max(0, y1 - pad_y), min(image.width, x2 + pad_x), min(image.height, y2 + pad_y)))
    return output


def overlay(image: Image.Image, template: Template, page_number: int = 1) -> Image.Image:
    out = image.copy().convert("RGB")
    draw = ImageDraw.Draw(out)
    for field in template.fields.values():
        if field.page == page_number:
            draw.rectangle(field.box, outline="red", width=3)
    return out
