"""PaperTrail: turn a letter into a checklist where every item cites its source."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("papertrail")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"
