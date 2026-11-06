"""DotDE: export and import Linux desktop environment configurations."""

from importlib import metadata as _metadata
from pathlib import Path as _Path


def _read_version() -> str:
    try:
        return _metadata.version("dotde")
    except _metadata.PackageNotFoundError:
        version_file = _Path(__file__).resolve().parents[2] / "version"
        try:
            return version_file.read_text().strip()
        except OSError:
            return "0.0.0"


__version__ = _read_version()
