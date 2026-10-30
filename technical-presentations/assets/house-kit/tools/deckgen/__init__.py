"""deckgen - one layout, two renderers (PDF + PPTX)."""
from .layout import Deck, Para, Run, Slide, TextBlock, Rect, Line_, Image, para
from .backends import to_pdf, to_pptx

__all__ = [
    "Deck", "Para", "Run", "Slide", "TextBlock", "Rect", "Line_", "Image",
    "para", "to_pdf", "to_pptx",
]
