"""Lazy RapidOCR adapter with explicit bundled-model provenance."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import math
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from numbers import Real
from pathlib import Path
from typing import Protocol

from PIL import Image

from pagetrace.documents import MediaType
from pagetrace.ocr.errors import OcrDependencyError, OcrProcessingError
from pagetrace.ocr.models import (
    OCR_ENGINE_NAME,
    OCR_INFERENCE_BACKEND_NAME,
    OCR_INFERENCE_PROFILE,
    OCR_PROCESSOR_NAME,
    OCR_PROCESSOR_VERSION,
    PDF_RENDERER_NAME,
    RAPIDOCR_MODEL_PROFILE,
    OcrConfig,
    OcrProcessorDescriptor,
)

_MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)
_BACKEND_FAILURES = (ImportError, OSError, RuntimeError, TypeError, ValueError)

OcrPoint = tuple[float, float]
OcrQuadrilateral = tuple[OcrPoint, OcrPoint, OcrPoint, OcrPoint]


@dataclass(frozen=True, slots=True)
class OcrEngineResult:
    """Validated line text, confidence, and rendered-pixel geometry from OCR."""

    lines: tuple[str, ...]
    confidences: tuple[float, ...]
    boxes: tuple[OcrQuadrilateral, ...] = ()


class OcrEngine(Protocol):
    """Small interface used by OCR orchestration and focused tests."""

    def recognize(self, image: Image.Image) -> OcrEngineResult:
        """Recognize one already-bounded page image."""


class RapidOcrEngine:
    """CPU-only, single-threaded adapter around the bundled RapidOCR model profile."""

    def __init__(self, configuration: OcrConfig) -> None:
        model_paths = _bundled_model_paths()
        try:
            module = importlib.import_module(OCR_ENGINE_NAME)
            engine_type = module.EngineType
            rapid_ocr = module.RapidOCR
            params = {
                "Global.log_level": "error",
                "Global.max_side_len": configuration.engine_max_side_length,
                "Global.text_score": float(configuration.minimum_confidence),
                "Global.return_word_box": False,
                "EngineConfig.onnxruntime.intra_op_num_threads": 1,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                "EngineConfig.onnxruntime.use_cuda": False,
                "EngineConfig.onnxruntime.use_dml": False,
                "EngineConfig.onnxruntime.use_cann": False,
                "EngineConfig.onnxruntime.use_coreml": False,
                "Det.engine_type": engine_type.ONNXRUNTIME,
                "Cls.engine_type": engine_type.ONNXRUNTIME,
                "Rec.engine_type": engine_type.ONNXRUNTIME,
                "Det.max_candidates": configuration.limits.max_lines_per_page,
                "Det.model_path": str(model_paths["PP-OCRv6_det_small.onnx"]),
                "Cls.model_path": str(model_paths["ch_ppocr_mobile_v2.0_cls_mobile.onnx"]),
                "Rec.model_path": str(model_paths["PP-OCRv6_rec_small.onnx"]),
            }
            self._engine = rapid_ocr(params=params)
        except (AttributeError, PackageNotFoundError) as exc:
            raise OcrDependencyError(
                "the installed RapidOCR package does not expose the required 3.x API"
            ) from exc
        except _BACKEND_FAILURES as exc:
            raise OcrDependencyError("the optional RapidOCR runtime could not initialize") from exc

    def recognize(self, image: Image.Image) -> OcrEngineResult:
        """Run OCR and convert backend-specific output into validated stable values."""

        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=False)
        try:
            output = self._engine(buffer.getvalue())
        except _BACKEND_FAILURES as exc:
            raise OcrProcessingError("RapidOCR failed while processing a rendered page") from exc

        raw_lines = getattr(output, "txts", None)
        raw_confidences = getattr(output, "scores", None)
        raw_boxes = getattr(output, "boxes", None)
        if raw_lines is None and raw_confidences is None and raw_boxes is None:
            return OcrEngineResult(lines=(), confidences=())
        if raw_lines is None or raw_confidences is None or raw_boxes is None:
            raise OcrProcessingError("RapidOCR returned incomplete text/confidence/geometry output")
        try:
            lines = tuple(raw_lines)
            confidences = tuple(raw_confidences)
            boxes = tuple(raw_boxes)
        except TypeError as exc:
            raise OcrProcessingError("RapidOCR returned non-iterable output") from exc
        if len(lines) != len(confidences) or len(lines) != len(boxes):
            raise OcrProcessingError("RapidOCR returned mismatched text/confidence/geometry output")

        accepted_lines: list[str] = []
        accepted_confidences: list[float] = []
        accepted_boxes: list[OcrQuadrilateral] = []
        for line, confidence, box in zip(lines, confidences, boxes, strict=True):
            if not isinstance(line, str) or not line.strip():
                raise OcrProcessingError("RapidOCR returned an invalid text line")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise OcrProcessingError("RapidOCR returned an invalid confidence value")
            accepted_lines.append(line)
            accepted_confidences.append(round(float(confidence), 6))
            accepted_boxes.append(_validated_box(box, image.width, image.height))
        return OcrEngineResult(
            lines=tuple(accepted_lines),
            confidences=tuple(accepted_confidences),
            boxes=tuple(accepted_boxes),
        )


def create_ocr_engine(configuration: OcrConfig) -> OcrEngine:
    """Create the selected real OCR engine without importing it at package import time."""

    return RapidOcrEngine(configuration)


def current_ocr_processor_descriptor(media_type: MediaType) -> OcrProcessorDescriptor:
    """Capture installed engine, backend, renderer, profile, and model-byte provenance."""

    try:
        engine_version = version(OCR_ENGINE_NAME)
        inference_version = version(OCR_INFERENCE_BACKEND_NAME)
        renderer_version = version(PDF_RENDERER_NAME) if media_type is MediaType.PDF else None
    except PackageNotFoundError as exc:
        raise OcrDependencyError(
            "OCR dependencies are not installed; install PageTrace with the 'ocr' extra"
        ) from exc
    model_paths = _bundled_model_paths()
    return OcrProcessorDescriptor(
        name=OCR_PROCESSOR_NAME,
        version=OCR_PROCESSOR_VERSION,
        engine_name=OCR_ENGINE_NAME,
        engine_version=engine_version,
        inference_backend_name=OCR_INFERENCE_BACKEND_NAME,
        inference_backend_version=inference_version,
        inference_profile=OCR_INFERENCE_PROFILE,
        model_profile=RAPIDOCR_MODEL_PROFILE,
        model_fingerprint=_model_fingerprint(model_paths),
        pdf_renderer_name=PDF_RENDERER_NAME if media_type is MediaType.PDF else None,
        pdf_renderer_version=renderer_version,
    )


def _bundled_model_paths() -> dict[str, Path]:
    spec = importlib.util.find_spec(OCR_ENGINE_NAME)
    if spec is None or spec.submodule_search_locations is None:
        raise OcrDependencyError("RapidOCR is unavailable; install PageTrace with the 'ocr' extra")
    locations = tuple(spec.submodule_search_locations)
    if len(locations) != 1:
        raise OcrDependencyError("RapidOCR package location is ambiguous")
    model_directory = Path(locations[0]) / "models"
    paths = {name: model_directory / name for name in _MODEL_FILES}
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise OcrDependencyError("the required bundled RapidOCR model profile is missing or unsafe")
    return paths


def _model_fingerprint(model_paths: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    try:
        for name in sorted(model_paths):
            digest.update(name.encode())
            digest.update(b"\0")
            with model_paths[name].open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
    except OSError as exc:
        raise OcrDependencyError("bundled RapidOCR models could not be fingerprinted") from exc
    return digest.hexdigest()


def _validated_box(value: object, width: int, height: int) -> OcrQuadrilateral:
    if not isinstance(value, Iterable):
        raise OcrProcessingError("RapidOCR returned a non-iterable text box")
    points: tuple[object, ...] = tuple(value)
    if len(points) != 4:
        raise OcrProcessingError("RapidOCR text boxes must contain four points")

    accepted: list[OcrPoint] = []
    for point in points:
        if not isinstance(point, Iterable):
            raise OcrProcessingError("RapidOCR returned a non-iterable text-box point")
        coordinates: tuple[object, ...] = tuple(point)
        if len(coordinates) != 2:
            raise OcrProcessingError("RapidOCR text-box points must contain two coordinates")
        x = _validated_coordinate(coordinates[0], width, "x")
        y = _validated_coordinate(coordinates[1], height, "y")
        accepted.append((x, y))

    xs = tuple(point[0] for point in accepted)
    ys = tuple(point[1] for point in accepted)
    if min(xs) >= max(xs) or min(ys) >= max(ys):
        raise OcrProcessingError("RapidOCR returned a degenerate text box")
    return accepted[0], accepted[1], accepted[2], accepted[3]


def _validated_coordinate(value: object, maximum: int, axis: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise OcrProcessingError(f"RapidOCR returned an invalid {axis} coordinate")
    coordinate = round(float(value), 6)
    if not 0 <= coordinate <= maximum:
        raise OcrProcessingError(f"RapidOCR returned an out-of-bounds {axis} coordinate")
    return 0.0 if coordinate == 0 else coordinate
