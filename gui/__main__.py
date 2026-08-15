"""Permet de lancer l'interface par `python -m gui`."""

from __future__ import annotations

import sys
from pathlib import Path

# Autorise l'exécution depuis n'importe quel répertoire.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gui import lancer  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(lancer())
