"""
Lecteur vidéo temps réel avec codage NTSC / PAL / SECAM sur GPU.

La bibliothèque `tvcolor` reconstruit le signal composite avec toute la
rigueur possible, mais à raison d'un quart de seconde par image : c'est un
banc de mesure, pas un lecteur. Ce module fait le même trajet sur le
processeur graphique, en temps réel, au prix d'approximations assumées et
documentées :

* les filtres analogiques (Butterworth d'ordre 4) deviennent des filtres à
  réponse impulsionnelle finie tronqués ;
* le signal composite est échantillonné sur la grille de la norme plutôt
  qu'à quatre fois la sous-porteuse ;
* les préaccentuations SECAM basse fréquence sont omises — transparentes à
  l'aller-retour, elles ne se manifestent qu'en présence de bruit.

Tout le reste est identique, constantes normatives comprises : elles sont
lues dans `tvcolor.constantes`, il n'y a pas de seconde source de vérité.
L'écart entre les deux chaînes est mesuré par `tests/test_shaders.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

from PyQt5 import QtCore  # noqa: E402

QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

__all__ = ["lancer"]


def lancer(argv=None) -> int:
    """Point d'entrée de l'application de lecture."""
    from .app import lancer as _lancer

    return _lancer(argv)
