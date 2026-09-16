from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

import pagetrace.ocr.engine as engine_module
from pagetrace.documents import MediaType
from pagetrace.ocr import OcrConfig, OcrDependencyError, OcrProcessingError
from pagetrace.ocr.engine import RapidOcrEngine, current_ocr_processor_descriptor


def test_real_rapidocr_uses_bundled_models_and_cpu_backend() -> None:
    image = Image.new("RGB", (1_200, 260), "white")
    font_paths = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    font_path = next((path for path in font_paths if path.is_file()), None)
    if font_path is None:
        pytest.skip("a deterministic TrueType test font is unavailable")
    font = ImageFont.truetype(str(font_path), 96)
    ImageDraw.Draw(image).text((30, 60), "PAGETRACE 2026", font=font, fill="black")

    ocr_engine = RapidOcrEngine(OcrConfig())
    result = ocr_engine.recognize(image)
    descriptor = current_ocr_processor_descriptor(MediaType.PNG)

    assert " ".join(result.lines) == "PAGETRACE 2026"
    assert all(confidence > 0.9 for confidence in result.confidences)
    assert descriptor.engine_name == "rapidocr"
    assert descriptor.inference_backend_name == "onnxruntime"
    assert descriptor.inference_profile == "cpu-single-thread"
    assert len(descriptor.model_fingerprint) == 64
    assert descriptor.pdf_renderer_name is None


def test_pdf_descriptor_records_renderer_version() -> None:
    descriptor = current_ocr_processor_descriptor(MediaType.PDF)

    assert descriptor.pdf_renderer_name == "pypdfium2"
    assert descriptor.pdf_renderer_version


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (SimpleNamespace(txts=("text",), scores=None), "incomplete"),
        (SimpleNamespace(txts=1, scores=1), "non-iterable"),
        (SimpleNamespace(txts=("one",), scores=(0.9, 0.8)), "mismatched"),
        (SimpleNamespace(txts=("",), scores=(0.9,)), "invalid text line"),
        (SimpleNamespace(txts=(7,), scores=(0.9,)), "invalid text line"),
        (SimpleNamespace(txts=("text",), scores=(True,)), "invalid confidence"),
        (SimpleNamespace(txts=("text",), scores=(float("nan"),)), "invalid confidence"),
        (SimpleNamespace(txts=("text",), scores=(1.1,)), "invalid confidence"),
    ],
)
def test_rapidocr_rejects_malformed_backend_output(output: object, message: str) -> None:
    ocr_engine = _engine_with_output(output)

    with pytest.raises(OcrProcessingError, match=message):
        ocr_engine.recognize(Image.new("RGB", (2, 2)))


def test_rapidocr_accepts_explicit_no_text_result() -> None:
    ocr_engine = _engine_with_output(SimpleNamespace(txts=None, scores=None))

    assert ocr_engine.recognize(Image.new("RGB", (2, 2))).lines == ()


def test_rapidocr_wraps_backend_processing_failure() -> None:
    def fail(_data: bytes) -> object:
        raise RuntimeError("backend failed")

    ocr_engine = object.__new__(RapidOcrEngine)
    ocr_engine._engine = fail

    with pytest.raises(OcrProcessingError, match="processing"):
        ocr_engine.recognize(Image.new("RGB", (2, 2)))


def test_engine_initialization_rejects_incompatible_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "_bundled_model_paths", lambda: {})
    monkeypatch.setattr("pagetrace.ocr.engine.importlib.import_module", lambda _name: object())

    with pytest.raises(OcrDependencyError, match=r"3\.x API"):
        RapidOcrEngine(OcrConfig())


def test_engine_initialization_wraps_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _EngineType:
        ONNXRUNTIME = "onnxruntime"

    def fail(*, params: dict[str, object]) -> object:
        assert params
        raise ValueError("bad runtime")

    module = SimpleNamespace(EngineType=_EngineType, RapidOCR=fail)
    models = {name: Path(name) for name in engine_module._MODEL_FILES}
    monkeypatch.setattr(engine_module, "_bundled_model_paths", lambda: models)
    monkeypatch.setattr("pagetrace.ocr.engine.importlib.import_module", lambda _name: module)

    with pytest.raises(OcrDependencyError, match="could not initialize"):
        RapidOcrEngine(OcrConfig())


def test_descriptor_reports_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(engine_module, "version", missing)

    with pytest.raises(OcrDependencyError, match="install PageTrace"):
        current_ocr_processor_descriptor(MediaType.PNG)


def test_bundled_model_discovery_rejects_missing_or_ambiguous_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pagetrace.ocr.engine.importlib.util.find_spec", lambda _name: None)
    with pytest.raises(OcrDependencyError, match="unavailable"):
        engine_module._bundled_model_paths()

    ambiguous = SimpleNamespace(submodule_search_locations=(str(tmp_path), str(tmp_path / "other")))
    monkeypatch.setattr("pagetrace.ocr.engine.importlib.util.find_spec", lambda _name: ambiguous)
    with pytest.raises(OcrDependencyError, match="ambiguous"):
        engine_module._bundled_model_paths()

    single = SimpleNamespace(submodule_search_locations=(str(tmp_path),))
    monkeypatch.setattr("pagetrace.ocr.engine.importlib.util.find_spec", lambda _name: single)
    with pytest.raises(OcrDependencyError, match="missing or unsafe"):
        engine_module._bundled_model_paths()


def _engine_with_output(output: object) -> RapidOcrEngine:
    def return_output(_data: bytes) -> object:
        return output

    ocr_engine = object.__new__(RapidOcrEngine)
    ocr_engine._engine = return_output
    return ocr_engine
