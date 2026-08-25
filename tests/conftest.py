from collections.abc import Mapping
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter


@pytest.fixture
def pdf_factory() -> "PdfFactory":
    return PdfFactory()


@pytest.fixture
def image_factory() -> "ImageFactory":
    return ImageFactory()


class PdfFactory:
    def __call__(
        self,
        path: Path,
        *,
        pages: int = 1,
        metadata: Mapping[str, str] | None = None,
        encrypted: bool = False,
        rotation: int | None = None,
    ) -> Path:
        writer = PdfWriter()
        for _ in range(pages):
            page = writer.add_blank_page(width=72, height=144)
            if rotation is not None:
                page.rotate(rotation)
        if metadata is not None:
            writer.add_metadata(dict(metadata))
        if encrypted:
            writer.encrypt("test-password")
        with path.open("wb") as stream:
            writer.write(stream)
        return path


class ImageFactory:
    def __call__(
        self,
        path: Path,
        *,
        image_format: str,
        size: tuple[int, int] = (4, 3),
    ) -> Path:
        image = Image.new("RGB", size, color=(20, 40, 60))
        image.save(path, format=image_format)
        return path
