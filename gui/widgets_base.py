"""Petits widgets réutilisables : curseur à valeur réelle, séparateurs, titres."""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets


class Glissiere(QtWidgets.QSlider):
    """Glissière sourde à la molette.

    Les curseurs vivent dans un panneau qui défile, et le comportement par
    défaut de Qt y est franchement traître : la molette agit sur la glissière
    survolée au lieu de faire défiler le panneau. On croit parcourir les
    réglages, on est en train de les changer — et sur une barre de position de
    vidéo, un cran de molette saute dans le film.

    En ignorant l'événement, on le laisse remonter au parent, qui lui sait
    défiler. Le réglage reste accessible au clic et aux flèches du clavier.
    """

    def wheelEvent(self, evenement):  # noqa: N802 - API Qt
        evenement.ignore()


class Curseur(QtWidgets.QWidget):
    """Curseur à valeur réelle, avec libellé, unité et valeur lisible.

    Qt ne fournit que des curseurs entiers. On travaille donc en pas entiers
    et l'on convertit à l'affichage comme à la lecture.
    """

    valeur_changee = QtCore.pyqtSignal(float)

    def __init__(
        self,
        libelle: str,
        mini: float,
        maxi: float,
        valeur: float,
        pas: float = 0.1,
        unite: str = "",
        decimales: int = 2,
        parent=None,
    ):
        super().__init__(parent)
        self._mini, self._pas = mini, pas
        self._unite, self._decimales = unite, decimales

        self._titre = QtWidgets.QLabel(libelle)
        self._valeur = QtWidgets.QLabel()
        self._valeur.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._valeur.setMinimumWidth(74)
        police = self._valeur.font()
        police.setFamily("Consolas")
        self._valeur.setFont(police)

        self._curseur = Glissiere(QtCore.Qt.Horizontal)
        self._curseur.setMinimum(0)
        self._curseur.setMaximum(int(round((maxi - mini) / pas)))
        self._curseur.valueChanged.connect(self._sur_changement)

        haut = QtWidgets.QHBoxLayout()
        haut.setContentsMargins(0, 0, 0, 0)
        haut.addWidget(self._titre)
        haut.addStretch(1)
        haut.addWidget(self._valeur)

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 2, 0, 2)
        disposition.setSpacing(1)
        disposition.addLayout(haut)
        disposition.addWidget(self._curseur)

        self.definir(valeur)

    # ------------------------------------------------------------------

    def valeur(self) -> float:
        return self._mini + self._curseur.value() * self._pas

    def definir(self, valeur: float) -> None:
        cran = int(round((valeur - self._mini) / self._pas))
        self._curseur.setValue(max(0, min(cran, self._curseur.maximum())))
        self._rafraichir()

    def definir_libelle(self, libelle: str) -> None:
        self._titre.setText(libelle)

    def _sur_changement(self, _valeur: int) -> None:
        self._rafraichir()
        self.valeur_changee.emit(self.valeur())

    def _rafraichir(self) -> None:
        texte = f"{self.valeur():.{self._decimales}f}"
        if self._unite:
            texte += f" {self._unite}"
        self._valeur.setText(texte)


class Groupe(QtWidgets.QGroupBox):
    """Cadre titré, avec une disposition verticale déjà en place."""

    def __init__(self, titre: str, parent=None):
        super().__init__(titre, parent)
        self.disposition = QtWidgets.QVBoxLayout(self)
        self.disposition.setContentsMargins(8, 6, 8, 8)
        self.disposition.setSpacing(3)

    def ajouter(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self.disposition.addWidget(widget)
        return widget

    def ajouter_ligne(self, libelle: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        ligne = QtWidgets.QHBoxLayout()
        ligne.setContentsMargins(0, 0, 0, 0)
        etiquette = QtWidgets.QLabel(libelle)
        ligne.addWidget(etiquette)
        ligne.addStretch(1)
        ligne.addWidget(widget)
        conteneur = QtWidgets.QWidget()
        conteneur.setLayout(ligne)
        self.disposition.addWidget(conteneur)
        widget.setProperty("etiquette", etiquette)
        return widget


def note(texte: str) -> QtWidgets.QLabel:
    """Petite explication en gris sous un réglage."""
    etiquette = QtWidgets.QLabel(texte)
    etiquette.setWordWrap(True)
    etiquette.setStyleSheet("color: palette(mid); font-size: 11px;")
    return etiquette
