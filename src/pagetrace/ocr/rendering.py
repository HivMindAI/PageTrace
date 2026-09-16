"""Bounded rendering of only the pages selected by Milestone 2A routing."""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from pagetrace.documents import DocumentManifest, MediaType
from pagetrace.ocr.errors import OcrDependencyError, OcrLimitError, OcrProcessingError
from pagetrace.ocr.models import PDF_RENDERER_NAME, OcrConfig

_RENDER_FAILURES = (OSError, RuntimeError, TypeError, ValueError)


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """One bounded page raster ready for the OCR adapter."""

    page_number: int
    image: Image.Image

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


def render_selected_pages(
    source_bytes: bytes,
    manifest: DocumentManifest,
    selected_page_numbers: tuple[int, ...],
    configuration: OcrConfig,
) -> Iterator[RenderedPage]:
    """Render selected pages in document order while enforcing pixel limits."""

    _preflight_rendering(manifest, selected_page_numbers, configuration)
    if not selected_page_numbers:
        return
    if manifest.media_type is MediaType.PDF:
        yield from _render_pdf_pages(source_bytes, manifest, selected_page_numbers, configuration)
    else:
        yield _load_image_page(source_bytes, manifest, configuration)


def _preflight_rendering(
    manifest: DocumentManifest,
    selected_page_numbers: tuple[int, ...],
    configuration: OcrConfig,
) -> None:
    if tuple(sorted(set(selected_page_numbers))) != selected_page_numbers:
        raise OcrProcessingError("selected OCR pages must be unique and in document order")
    if any(number < 1 or number > manifest.page_count for number in selected_page_numbers):
        raise OcrProcessingError("selected OCR page number is outside the document")
    if len(selected_page_numbers) > configuration.limits.max_pages_per_document:
        raise OcrLimitError(
            "OCR selection exceeds the "
            f"{configuration.limits.max_pages_per_document}-page document limit"
        )

    total_pixels = 0
    selected = set(selected_page_numbers)
    for page in manifest.pages:
        if page.page_number not in selected:
            continue
        if manifest.media_type is MediaType.PDF:
            width, height = _planned_pdf_dimensions(
                float(page.width),
                float(page.height),
                page.rotation_degrees or 0,
                configuration.render_dpi,
            )
        else:
            width, height = int(page.width), int(page.height)
        pixels = width * height
        if pixels > configuration.limits.max_pixels_per_page:
            raise OcrLimitError(
                f"page {page.page_number} would exceed the "
                f"{configuration.limits.max_pixels_per_page}-pixel OCR limit"
            )
        total_pixels += pixels
        if total_pixels > configuration.limits.max_pixels_per_document:
            raise OcrLimitError(
                "selected pages would exceed the "
                f"{configuration.limits.max_pixels_per_document}-pixel document OCR limit"
            )


def _planned_pdf_dimensions(
    width_points: float, height_points: float, rotation: int, render_dpi: int
) -> tuple[int, int]:
    if rotation in (90, 270):
        width_points, height_points = height_points, width_points
    scale = render_dpi / 72
    return math.ceil(width_points * scale), math.ceil(height_points * scale)


def _render_pdf_pages(
    source_bytes: bytes,
    manifest: DocumentManifest,
    selected_page_numbers: tuple[int, ...],
    configuration: OcrConfig,
) -> Iterator[RenderedPage]:
    try:
        pdfium = importlib.import_module(PDF_RENDERER_NAME)
    except ImportError as exc:
        raise OcrDependencyError(
            "PDF OCR rendering is unavailable; install PageTrace with the 'ocr' extra"
        ) from exc
    document: Any = None
    try:
        document = pdfium.PdfDocument(source_bytes)
        if len(document) != manifest.page_count:
            raise OcrProcessingError(
                "PDFium page count does not match the verified document manifest"
            )
        total_pixels = 0
        for page_number in selected_page_numbers:
            page: Any = None
            bitmap: Any = None
            try:
                page = document[page_number - 1]
                bitmap = page.render(
                    scale=configuration.render_dpi / 72,
                    rotation=0,
                    prefer_bgrx=True,
                    rev_byteorder=True,
                    fill_color=(255, 255, 255, 255),
                )
                image = bitmap.to_pil().convert("RGB").copy()
            finally:
                if bitmap is not None:
                    bitmap.close()
                if page is not None:
                    page.close()
            total_pixels = _enforce_actual_pixels(
                image.width,
                image.height,
                page_number,
                total_pixels,
                configuration,
            )
            yield RenderedPage(page_number=page_number, image=image)
    except (OcrLimitError, OcrProcessingError):
        raise
    except _RENDER_FAILURES as exc:
        raise OcrProcessingError("PDFium could not render a selected OCR page") from exc
    finally:
        if document is not None:
            document.close()


def _load_image_page(
    source_bytes: bytes, manifest: DocumentManifest, configuration: OcrConfig
) -> RenderedPage:
    expected_format = "PNG" if manifest.media_type is MediaType.PNG else "JPEG"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(source_bytes)) as source:
                if source.format != expected_format or source.size != (
                    int(manifest.pages[0].width),
                    int(manifest.pages[0].height),
                ):
                    raise OcrProcessingError(
                        "stored image metadata no longer matches the verified manifest"
                    )
                if getattr(source, "n_frames", 1) != 1:
                    raise OcrProcessingError("stored OCR image unexpectedly has multiple frames")
                source.load()
                image = source.convert("RGB").copy()
    except OcrProcessingError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise OcrLimitError("stored image exceeds Pillow's decompression-bomb limit") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise OcrProcessingError("Pillow could not decode the verified OCR image") from exc
    _enforce_actual_pixels(image.width, image.height, 1, 0, configuration)
    return RenderedPage(page_number=1, image=image)


def _enforce_actual_pixels(
    width: int,
    height: int,
    page_number: int,
    previous_total: int,
    configuration: OcrConfig,
) -> int:
    pixels = width * height
    if pixels > configuration.limits.max_pixels_per_page:
        raise OcrLimitError(
            f"page {page_number} rendered output exceeds the "
            f"{configuration.limits.max_pixels_per_page}-pixel OCR limit"
        )
    total = previous_total + pixels
    if total > configuration.limits.max_pixels_per_document:
        raise OcrLimitError(
            "rendered output exceeds the "
            f"{configuration.limits.max_pixels_per_document}-pixel document OCR limit"
        )
    return total
