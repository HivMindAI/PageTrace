import json
import tomllib
from importlib import resources
from importlib.metadata import version
from pathlib import Path

import pagetrace
import pagetrace.corpus
import pagetrace.extraction
import pagetrace.ocr
import pagetrace.qa
import pagetrace.quality
import pagetrace.retrieval
import pagetrace.structure
import pagetrace.web


def test_package_imports() -> None:
    """The installed top-level package is importable."""
    assert pagetrace.__name__ == "pagetrace"
    assert pagetrace.extraction.__name__ == "pagetrace.extraction"
    assert pagetrace.ocr.__name__ == "pagetrace.ocr"
    assert pagetrace.qa.__name__ == "pagetrace.qa"
    assert pagetrace.quality.__name__ == "pagetrace.quality"
    assert pagetrace.retrieval.__name__ == "pagetrace.retrieval"
    assert pagetrace.structure.__name__ == "pagetrace.structure"
    assert pagetrace.corpus.__name__ == "pagetrace.corpus"
    assert pagetrace.web.__name__ == "pagetrace.web"


def test_package_version_matches_distribution_metadata() -> None:
    """The public version stays aligned with installed distribution metadata."""
    assert pagetrace.__version__ == version("pagetrace")


def test_release_versions_are_synchronized() -> None:
    """Python and web release metadata describe the same portfolio version."""

    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    web_package = json.loads((root / "web" / "package.json").read_text(encoding="utf-8"))
    web_lock = json.loads((root / "web" / "package-lock.json").read_text(encoding="utf-8"))

    expected = project["project"]["version"]
    assert expected == pagetrace.__version__
    assert web_package["version"] == expected
    assert web_lock["version"] == expected
    assert web_lock["packages"][""]["version"] == expected


def test_typing_marker_is_packaged() -> None:
    """The PEP 561 marker is exposed with the package."""
    typing_marker = resources.files("pagetrace").joinpath("py.typed")

    assert typing_marker.is_file()


def test_web_application_is_packaged() -> None:
    """The backend wheel contains the pre-built evidence desk."""

    web_root = resources.files("pagetrace.web").joinpath("dist")
    index = web_root.joinpath("index.html")
    assets = web_root.joinpath("assets")

    assert index.is_file()
    assert "PageTrace Evidence Desk" in index.read_text(encoding="utf-8")
    assert assets.is_dir()
    assert any(item.name.endswith(".js") for item in assets.iterdir())
    assert any(item.name.endswith(".css") for item in assets.iterdir())
