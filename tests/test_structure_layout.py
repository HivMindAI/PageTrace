from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import pagetrace.structure.layout as structure_layout
from pagetrace.documents import MediaType, ingest_document
from pagetrace.structure import (
    DEFAULT_STRUCTURE_CONFIG,
    StructureConfig,
    StructureDependencyError,
    StructureLimitError,
    StructureLimits,
    StructureProcessingError,
)
from pagetrace.structure.layout import (
    current_structure_processor_descriptor,
    extract_pdf_layout,
)
from tests.conftest import TextPdfFactory


class _Context:
    def __init__(self, pages: list[object]) -> None:
        self.pages = pages

    def __enter__(self) -> _Context:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Row:
    def __init__(self, cells: list[tuple[float, float, float, float] | None]) -> None:
        self.cells = cells


class _Table:
    def __init__(
        self,
        bbox: tuple[float, float, float, float],
        cells: list[list[tuple[float, float, float, float] | None]],
        text: list[list[str | None]],
    ) -> None:
        self.bbox = bbox
        self.rows = [_Row(row) for row in cells]
        self._text = text

    def extract(self, **_settings: float) -> list[list[str | None]]:
        return self._text


class _Page:
    width = 200
    height = 200

    def __init__(self, words: object, tables: object) -> None:
        self._words = words
        self._tables = tables
        self.word_settings: dict[str, object] | None = None
        self.table_settings: dict[str, object] | None = None

    def extract_words(self, **settings: object) -> object:
        self.word_settings = settings
        return self._words

    def find_tables(self, *, table_settings: dict[str, object]) -> object:
        self.table_settings = table_settings
        return self._tables


def test_image_processor_descriptor_has_no_pdf_backend() -> None:
    descriptor = current_structure_processor_descriptor(MediaType.PNG)

    assert descriptor.pdf_layout_backend_name is None
    assert descriptor.pdf_layout_backend_version is None


def test_pdf_processor_descriptor_requires_installed_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(_name: str) -> str:
        from importlib.metadata import PackageNotFoundError

        raise PackageNotFoundError

    monkeypatch.setattr("pagetrace.structure.layout.version", _missing)

    with pytest.raises(StructureDependencyError, match=r"structure.*extra"):
        current_structure_processor_descriptor(MediaType.PDF)

    monkeypatch.setattr("pagetrace.structure.layout.version", lambda _name: "0.11.9")
    descriptor = current_structure_processor_descriptor(MediaType.PDF)
    assert descriptor.pdf_layout_backend_name == "pdfplumber"
    assert descriptor.pdf_layout_backend_version == "0.11.9"


def test_extract_pdf_layout_validates_words_tables_and_stable_order(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = text_pdf_factory(tmp_path / "source.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=tmp_path / "store")
    later = _Table(
        (100, 120, 190, 180),
        [[(100, 120, 190, 180)]],
        [["later"]],
    )
    earlier = _Table(
        (10, 120, 90, 180),
        [[(10, 120, 50, 180), None]],
        [[" first ", None]],
    )
    page = _Page(
        [{"text": "Enough", "x0": 10, "top": 90, "x1": 55, "bottom": 105}],
        [later, earlier],
    )
    _install_pdfplumber(monkeypatch, [page])

    layout = extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)

    assert layout[0].words[0].text == "Enough"
    assert [table.bounding_box.x0 for table in layout[0].tables] == [10, 100]
    assert layout[0].tables[0].row_count == 1
    assert layout[0].tables[0].column_count == 2
    assert len(layout[0].tables[0].cells) == 1
    assert layout[0].tables[0].cells[0].text == " first "
    assert page.word_settings == {
        "x_tolerance": 3.0,
        "y_tolerance": 3.0,
        "keep_blank_chars": False,
        "use_text_flow": False,
        "split_at_punctuation": False,
        "expand_ligatures": True,
        "return_chars": False,
    }
    assert page.table_settings == {
        "horizontal_strategy": "lines",
        "vertical_strategy": "lines",
    }


def test_extract_pdf_layout_enforces_page_and_span_limits(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = text_pdf_factory(tmp_path / "source.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=tmp_path / "store")
    words = [
        {"text": "one", "x0": 1, "top": 1, "x1": 10, "bottom": 10},
        {"text": "two", "x0": 12, "top": 1, "x1": 20, "bottom": 10},
    ]
    _install_pdfplumber(monkeypatch, [_Page(words, [])])
    configuration = StructureConfig(limits=StructureLimits(max_spans_per_page=1))

    with pytest.raises(StructureLimitError, match="span limit"):
        extract_pdf_layout(source.read_bytes(), manifest, configuration)

    _install_pdfplumber(monkeypatch, [])
    with pytest.raises(StructureProcessingError, match="page count"):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)


@pytest.mark.parametrize(
    ("words", "message"),
    [
        (None, "word output"),
        ([{"text": " ", "x0": 1, "top": 1, "x1": 2, "bottom": 2}], "word text"),
        ([{"text": "word", "x0": 1, "top": 1, "x1": 201, "bottom": 2}], "outside"),
    ],
)
def test_extract_pdf_layout_rejects_invalid_backend_words(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
    words: object,
    message: str,
) -> None:
    source = text_pdf_factory(tmp_path / "source.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=tmp_path / "store")
    _install_pdfplumber(monkeypatch, [_Page(words, [])])

    with pytest.raises(StructureProcessingError, match=message):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)


def test_extract_pdf_layout_rejects_dimension_mismatch(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = text_pdf_factory(tmp_path / "source.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=tmp_path / "store")
    page = _Page([], [])
    page.width = 199
    _install_pdfplumber(monkeypatch, [page])

    with pytest.raises(StructureProcessingError, match="width"):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)

    page.width = 200
    page.height = 199
    with pytest.raises(StructureProcessingError, match="height"):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)


def test_extract_pdf_layout_reports_import_and_parser_failures(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = text_pdf_factory(tmp_path / "source.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=tmp_path / "store")

    def _missing(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(structure_layout, "importlib", SimpleNamespace(import_module=_missing))
    with pytest.raises(StructureDependencyError, match=r"structure.*extra"):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)

    def _failed_open(_source: object) -> object:
        raise OSError

    monkeypatch.setattr(
        structure_layout,
        "importlib",
        SimpleNamespace(import_module=lambda _name: SimpleNamespace(open=_failed_open)),
    )
    with pytest.raises(StructureProcessingError, match="could not extract"):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("not_list", "table output"),
        ("empty_grid", "empty table grid"),
        ("rows", "inconsistent table rows"),
        ("cells", "inconsistent table cells"),
        ("outside", "outside its table"),
    ],
)
def test_extract_pdf_layout_rejects_invalid_backend_tables(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    message: str,
) -> None:
    source = text_pdf_factory(tmp_path / "source.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=tmp_path / "store")
    if case == "not_list":
        tables: object = None
    elif case == "empty_grid":
        tables = [_Table((10, 10, 100, 100), [], [])]
    elif case == "rows":
        tables = [_Table((10, 10, 100, 100), [[(10, 10, 50, 50)]], [])]
    elif case == "cells":
        tables = [
            _Table(
                (10, 10, 100, 100),
                [[(10, 10, 50, 50), (50, 10, 100, 50)]],
                [["one"]],
            )
        ]
    else:
        tables = [_Table((10, 10, 100, 100), [[(100, 100, 150, 150)]], [["outside"]])]
    _install_pdfplumber(monkeypatch, [_Page([], tables)])

    with pytest.raises(StructureProcessingError, match=message):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)


def test_extract_pdf_layout_rejects_non_pdf_manifest(
    tmp_path: Path,
    image_factory: Any,
) -> None:
    source = image_factory(tmp_path / "source.png", image_format="PNG")
    manifest = ingest_document(source, store=tmp_path / "store")

    with pytest.raises(StructureProcessingError, match="requires a PDF"):
        extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)


def test_real_pdfplumber_extracts_positioned_words_and_vector_table(tmp_path: Path) -> None:
    pytest.importorskip("pdfplumber")
    source = _write_table_pdf(tmp_path / "table.pdf")
    manifest = ingest_document(source, store=tmp_path / "store")

    layout = extract_pdf_layout(source.read_bytes(), manifest, DEFAULT_STRUCTURE_CONFIG)

    assert [word.text for word in layout[0].words] == ["A", "B", "C", "D"]
    assert len(layout[0].tables) == 1
    table = layout[0].tables[0]
    assert (table.row_count, table.column_count) == (2, 2)
    assert [cell.text for cell in table.cells] == ["A", "B", "C", "D"]


def _install_pdfplumber(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[object],
) -> None:
    module = SimpleNamespace(open=lambda _source: _Context(pages))
    monkeypatch.setattr(
        structure_layout,
        "importlib",
        SimpleNamespace(import_module=lambda _name: module),
    )


def _write_table_pdf(path: Path) -> Path:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    content = DecodedStreamObject()
    content.set_data(
        b"0.5 w "
        b"20 40 m 180 40 l S 20 80 m 180 80 l S 20 120 m 180 120 l S "
        b"20 40 m 20 120 l S 100 40 m 100 120 l S 180 40 m 180 120 l S "
        b"BT /F1 10 Tf 30 95 Td (A) Tj ET "
        b"BT /F1 10 Tf 110 95 Td (B) Tj ET "
        b"BT /F1 10 Tf 30 55 Td (C) Tj ET "
        b"BT /F1 10 Tf 110 55 Td (D) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as stream:
        writer.write(stream)
    return path
