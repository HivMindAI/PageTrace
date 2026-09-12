from importlib import resources
from importlib.metadata import version

import pagetrace
import pagetrace.extraction


def test_package_imports() -> None:
    """The installed top-level package is importable."""
    assert pagetrace.__name__ == "pagetrace"
    assert pagetrace.extraction.__name__ == "pagetrace.extraction"


def test_package_version_matches_distribution_metadata() -> None:
    """The public development version stays aligned with package metadata."""
    assert pagetrace.__version__ == version("pagetrace")


def test_typing_marker_is_packaged() -> None:
    """The PEP 561 marker is exposed with the package."""
    typing_marker = resources.files("pagetrace").joinpath("py.typed")

    assert typing_marker.is_file()
