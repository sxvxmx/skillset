"""deckcheck - presentation consistency linter."""

from .model import Deck, Finding, Rect, Report, Severity, Slide
from .loaders import load, load_pdf, load_pptx

__all__ = [
    "Deck",
    "Finding",
    "Rect",
    "Report",
    "Severity",
    "Slide",
    "load",
    "load_pdf",
    "load_pptx",
]
__version__ = "0.1.0"
