"""
Interface graphique Qt5 du simulateur.

Deux précautions prises ici, avant toute autre importation :

* on impose PyQt5 à pyqtgraph. La machine peut avoir PyQt5 et PyQt6 installés
  côte à côte, et pyqtgraph choisirait alors le premier qu'il trouve — ce qui
  produirait un mélange des deux liaisons dans le même processus, et un
  plantage immédiat ;
* on active la mise à l'échelle pour les écrans à forte densité, sans quoi
  l'interface est illisible sur un portable moderne.
"""

from __future__ import annotations

import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

from PyQt5 import QtCore  # noqa: E402

QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

__all__ = ["lancer"]


def lancer(argv=None) -> int:
    """Point d'entrée de l'application."""
    from .app import lancer as _lancer

    return _lancer(argv)
