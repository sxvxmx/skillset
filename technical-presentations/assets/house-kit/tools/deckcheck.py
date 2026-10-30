#!/usr/bin/env python3
"""deckcheck - presentation consistency linter.

    python tools/deckcheck.py reference.pdf
    python tools/deckcheck.py deck.pptx --strict --minutes 20
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deckcheck.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
