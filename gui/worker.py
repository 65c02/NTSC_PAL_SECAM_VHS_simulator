"""
Fil d'exécution de rendu.

Un passage complet dans la chaîne prend de l'ordre de 250 ms. C'est court,
mais bien assez pour figer l'interface à chaque mouvement de curseur. Le
rendu est donc confié à un fil séparé, avec deux garde-fous :

* **coalescence** — si l'utilisateur fait glisser un curseur, des dizaines de
  demandes arrivent. On n'en garde qu'une seule en attente, la plus récente ;
  les intermédiaires sont abandonnées sans jamais avoir été calculées.
* **jeton** — chaque demande porte un numéro. Un résultat dont le jeton n'est
  plus le dernier émis est ignoré à l'arrivée : on n'affiche jamais une image
  périmée arrivée après une plus fraîche.
"""

from __future__ import annotations

import copy
import traceback

import numpy as np
from PyQt5 import QtCore

from tvcolor.pipeline import Parametres, Resultat, encoder_decoder


class _Calculateur(QtCore.QObject):
    """Objet déplacé dans le fil de rendu ; ne touche jamais à l'interface."""

    termine = QtCore.pyqtSignal(object, int)
    echoue = QtCore.pyqtSignal(str, int)

    @QtCore.pyqtSlot(object, object, int)
    def executer(self, image: np.ndarray, params: Parametres, jeton: int) -> None:
        try:
            self.termine.emit(encoder_decoder(image, params), jeton)
        except Exception:
            self.echoue.emit(traceback.format_exc(), jeton)


class MoteurDeRendu(QtCore.QObject):
    """Ordonnanceur de rendu, côté interface."""

    resultat_pret = QtCore.pyqtSignal(object)
    erreur = QtCore.pyqtSignal(str)
    occupation_changee = QtCore.pyqtSignal(bool)

    _demande = QtCore.pyqtSignal(object, object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fil = QtCore.QThread()
        self._fil.setObjectName("rendu-tvcolor")
        self._calculateur = _Calculateur()
        self._calculateur.moveToThread(self._fil)
        self._demande.connect(self._calculateur.executer)
        self._calculateur.termine.connect(self._sur_termine)
        self._calculateur.echoue.connect(self._sur_echec)
        self._fil.start()

        self._jeton = 0
        self._occupe = False
        self._en_attente: tuple | None = None

    # -- API ---------------------------------------------------------------

    def demander(self, image: np.ndarray, params: Parametres) -> None:
        """Demande un rendu. Écrase toute demande en attente non encore lancée."""
        self._en_attente = (image, copy.deepcopy(params))
        if not self._occupe:
            self._lancer_suivant()

    def arreter(self) -> None:
        self._en_attente = None
        self._fil.quit()
        self._fil.wait(3000)

    @property
    def occupe(self) -> bool:
        return self._occupe

    # -- interne -----------------------------------------------------------

    def _lancer_suivant(self) -> None:
        if self._en_attente is None:
            if self._occupe:
                self._occupe = False
                self.occupation_changee.emit(False)
            return
        image, params = self._en_attente
        self._en_attente = None
        self._jeton += 1
        if not self._occupe:
            self._occupe = True
            self.occupation_changee.emit(True)
        self._demande.emit(image, params, self._jeton)

    @QtCore.pyqtSlot(object, int)
    def _sur_termine(self, resultat: Resultat, jeton: int) -> None:
        if jeton == self._jeton:
            self.resultat_pret.emit(resultat)
        self._lancer_suivant()

    @QtCore.pyqtSlot(str, int)
    def _sur_echec(self, message: str, jeton: int) -> None:
        if jeton == self._jeton:
            self.erreur.emit(message)
        self._lancer_suivant()
