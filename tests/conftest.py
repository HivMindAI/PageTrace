from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


@pytest.fixture
def pdf_factory() -> "PdfFactory":
    return PdfFactory()


@pytest.fixture
def image_factory() -> "ImageFactory":
    return ImageFactory()


@pytest.fixture
def text_pdf_factory() -> "TextPdfFactory":
    return TextPdfFactory()


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


class TextPdfFactory:
    def __call__(self, path: Path, texts: Sequence[str | None]) -> Path:
        writer = PdfWriter()
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
        font_reference = writer._add_object(font)
        for text in texts:
            page = writer.add_blank_page(width=200, height=200)
            if text is None:
                continue
            resources = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
            )
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 10 100 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Resources")] = resources
            page[NameObject("/Contents")] = writer._add_object(stream)
        with path.open("wb") as output:
            writer.write(output)
        return path
