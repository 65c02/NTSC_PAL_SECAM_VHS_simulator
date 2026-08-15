"""
Comparateur d'images — original, décodé, différence.

Les vues partagent le même zoom et le même déplacement : on regarde toujours
le même détail dans les trois, faute de quoi la comparaison ne vaut rien.
Un curseur horizontal désigne la ligne de balayage que l'oscilloscope
affichera — c'est ce qui relie l'image au signal.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets

pg.setConfigOptions(imageAxisOrder="row-major", antialias=False)

MODES = [
    ("triple", "Original · Décodé · Différence"),
    ("double", "Original · Décodé"),
    ("decode", "Décodé seul"),
    ("difference", "Différence seule"),
    ("original", "Original seul"),
]

_PANNEAUX = {
    "triple": ("source", "finale", "difference"),
    "double": ("source", "finale"),
    "decode": ("finale",),
    "difference": ("difference",),
    "original": ("source",),
}

_TITRES = {
    "source": "Image d'origine",
    "finale": "Après aller-retour",
    "difference": "Différence amplifiée",
}


class VueImages(QtWidgets.QWidget):
    """Trois vues liées, plus le curseur de sélection de ligne."""

    ligne_choisie = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: dict[str, np.ndarray] = {}
        self._elements: dict[str, pg.ImageItem] = {}
        self._graphes: dict[str, pg.PlotItem] = {}
        self._hauteur = 1
        self._ligne = 0

        self._toile = pg.GraphicsLayoutWidget()
        self._toile.setBackground("#101014")

        self._combo_mode = QtWidgets.QComboBox()
        for code, libelle in MODES:
            self._combo_mode.addItem(libelle, code)
        self._combo_mode.currentIndexChanged.connect(self._reconstruire)

        self._gain = QtWidgets.QDoubleSpinBox()
        self._gain.setRange(1.0, 40.0)
        self._gain.setSingleStep(1.0)
        self._gain.setValue(6.0)
        self._gain.setPrefix("×")
        self._gain.setToolTip(
            "Amplification de la différence. L'écart est centré sur le gris "
            "moyen : ce qui reste gris est identique."
        )
        self._gain.valueChanged.connect(self._rafraichir_difference)

        barre = QtWidgets.QHBoxLayout()
        barre.setContentsMargins(4, 2, 4, 2)
        barre.addWidget(QtWidgets.QLabel("Affichage"))
        barre.addWidget(self._combo_mode, 1)
        barre.addSpacing(12)
        barre.addWidget(QtWidgets.QLabel("Gain de différence"))
        barre.addWidget(self._gain)

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(2)
        disposition.addLayout(barre)
        disposition.addWidget(self._toile, 1)

        self._curseur_ligne = pg.InfiniteLine(
            angle=0, movable=True, pen=pg.mkPen("#ffcc33", width=1)
        )
        self._curseur_ligne.sigPositionChanged.connect(self._sur_curseur)

        self._reconstruire()

    # ------------------------------------------------------------------

    def afficher(self, source: np.ndarray, finale: np.ndarray, gain: float | None = None) -> None:
        """Met à jour les trois images."""
        self._images["source"] = source
        self._images["finale"] = finale
        self._hauteur = source.shape[0]
        if gain is not None:
            self._gain.setValue(gain)
        self._calculer_difference()
        premiere_fois = not any(e.image is not None for e in self._elements.values())
        for nom, element in self._elements.items():
            if nom in self._images:
                element.setImage(self._images[nom], autoLevels=False, levels=(0.0, 1.0))
        self._curseur_ligne.setBounds((0, max(0, self._hauteur - 1)))
        if premiere_fois:
            self.recadrer()
            # On se place d'emblée au milieu de l'image : la ligne 0 est celle
            # dont le filtre en peigne n'a pas de prédécesseur, elle n'est donc
            # pas représentative.
            self.definir_ligne(self._hauteur // 2)

    def recadrer(self) -> None:
        for graphe in self._graphes.values():
            graphe.vb.autoRange(padding=0.02)
            break

    def ligne_selectionnee(self) -> int:
        return self._ligne

    def definir_ligne(self, ligne: int) -> None:
        self._curseur_ligne.setPos(float(ligne))

    # ------------------------------------------------------------------

    def _calculer_difference(self) -> None:
        if "source" not in self._images or "finale" not in self._images:
            return
        ecart = self._images["finale"] - self._images["source"]
        self._images["difference"] = np.clip(0.5 + self._gain.value() * ecart, 0.0, 1.0)

    def _rafraichir_difference(self) -> None:
        self._calculer_difference()
        if "difference" in self._elements and "difference" in self._images:
            self._elements["difference"].setImage(
                self._images["difference"], autoLevels=False, levels=(0.0, 1.0)
            )

    def _sur_curseur(self) -> None:
        ligne = int(round(self._curseur_ligne.value()))
        if ligne != self._ligne:
            self._ligne = ligne
            self.ligne_choisie.emit(ligne)

    def _reconstruire(self) -> None:
        """Recompose la grille de vues selon le mode d'affichage choisi."""
        plage = None
        if self._graphes:
            premier = next(iter(self._graphes.values()))
            plage = premier.vb.viewRange()

        self._toile.clear()
        self._elements.clear()
        self._graphes.clear()

        panneaux = _PANNEAUX[self._combo_mode.currentData()]
        reference = None
        for nom in panneaux:
            graphe = self._toile.addPlot(title=_TITRES[nom])
            graphe.setAspectLocked(True)
            graphe.invertY(True)
            graphe.hideAxis("left")
            graphe.hideAxis("bottom")
            graphe.setMenuEnabled(False)

            element = pg.ImageItem(axisOrder="row-major")
            graphe.addItem(element)
            if nom in self._images:
                element.setImage(self._images[nom], autoLevels=False, levels=(0.0, 1.0))

            if reference is None:
                reference = graphe
            else:
                graphe.setXLink(reference)
                graphe.setYLink(reference)

            self._elements[nom] = element
            self._graphes[nom] = graphe

        # Le curseur de ligne se place sur la vue décodée si elle est visible,
        # sinon sur la première.
        hote = self._graphes.get("finale") or (reference if reference else None)
        if hote is not None:
            hote.addItem(self._curseur_ligne)
            self._curseur_ligne.setBounds((0, max(0, self._hauteur - 1)))
            self._curseur_ligne.setPos(float(self._ligne))

        if plage is not None and reference is not None:
            reference.vb.setRange(xRange=plage[0], yRange=plage[1], padding=0)
        elif reference is not None:
            reference.vb.autoRange(padding=0.02)
