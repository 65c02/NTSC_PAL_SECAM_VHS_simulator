"""
Lecture vidéo : décodage dans un fil séparé, cadencé sur l'horloge du fichier.

Le décodage d'une image 1080p coûte quelques millisecondes ; fait dans le fil
de l'interface, il saccaderait le rendu. Un fil dédié décode donc en avance et
transmet les images par signal Qt, ce qui les fait traverser la frontière des
fils sans verrou explicite.

La cadence est tenue par une horloge absolue et non par un `sleep` de durée
fixe : accumuler les retards image après image ferait dériver la lecture de
plusieurs secondes sur un film entier.

Le son n'est pas géré. OpenCV ne décode que l'image, et ajouter une chaîne
audio synchronisée demanderait une dépendance de plus pour un projet qui parle
de couleur.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PyQt5 import QtCore


@dataclass
class InfosVideo:
    chemin: str
    largeur: int
    hauteur: int
    images_par_seconde: float
    nombre_images: int

    @property
    def duree(self) -> float:
        return self.nombre_images / self.images_par_seconde if self.images_par_seconde else 0.0

    def resume(self) -> str:
        return (
            f"{Path(self.chemin).name} — {self.largeur}×{self.hauteur}, "
            f"{self.images_par_seconde:.2f} im/s, "
            f"{int(self.duree // 60)}:{int(self.duree % 60):02d}"
        )


class SourceVideo(QtCore.QObject):
    """Décode un fichier vidéo et émet ses images, à la bonne cadence."""

    image_prete = QtCore.pyqtSignal(object)
    position_changee = QtCore.pyqtSignal(int)
    terminee = QtCore.pyqtSignal()
    erreur = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._capture: cv2.VideoCapture | None = None
        self._infos: InfosVideo | None = None
        self._fil: threading.Thread | None = None

        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self._lecture = False
        self._vitesse = 1.0
        self._boucle = True
        self._cible_recherche = -1

    # ------------------------------------------------------------------

    @property
    def infos(self) -> InfosVideo | None:
        return self._infos

    @property
    def en_lecture(self) -> bool:
        return self._lecture

    def ouvrir(self, chemin: str) -> InfosVideo:
        self.fermer()
        capture = cv2.VideoCapture(chemin)
        if not capture.isOpened():
            raise OSError(f"impossible d'ouvrir la vidéo : {chemin}")

        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        if not (1.0 <= fps <= 240.0):     # certains conteneurs mentent
            fps = 25.0

        self._capture = capture
        self._infos = InfosVideo(
            chemin=chemin,
            largeur=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            hauteur=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            images_par_seconde=float(fps),
            nombre_images=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        )

        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle_decodage, daemon=True,
                                     name="decodage-video")
        self._fil.start()
        return self._infos

    def fermer(self) -> None:
        self._arret.set()
        if self._fil is not None:
            self._fil.join(timeout=2.0)
            self._fil = None
        with self._verrou:
            if self._capture is not None:
                self._capture.release()
                self._capture = None
        self._infos = None
        self._lecture = False

    # ------------------------------------------------------------------

    def lire(self) -> None:
        self._lecture = True

    def pause(self) -> None:
        self._lecture = False

    def basculer(self) -> None:
        self._lecture = not self._lecture

    def definir_vitesse(self, vitesse: float) -> None:
        self._vitesse = max(0.05, float(vitesse))

    def definir_boucle(self, actif: bool) -> None:
        self._boucle = bool(actif)

    def chercher(self, numero_image: int) -> None:
        with self._verrou:
            self._cible_recherche = max(0, int(numero_image))

    def avancer_d_une_image(self) -> None:
        """Décode une image et la publie, sans lancer la lecture."""
        with self._verrou:
            if self._capture is None:
                return
            ok, brute = self._capture.read()
            position = int(self._capture.get(cv2.CAP_PROP_POS_FRAMES))
        if ok:
            self.image_prete.emit(self._convertir(brute))
            self.position_changee.emit(position)

    # ------------------------------------------------------------------

    @staticmethod
    def _convertir(brute: np.ndarray) -> np.ndarray:
        # OpenCV livre du BGR ; OpenGL attend du RGB. `ascontiguousarray`
        # garantit que le téléversement pourra se faire d'un seul memcpy.
        return np.ascontiguousarray(cv2.cvtColor(brute, cv2.COLOR_BGR2RGB))

    def _boucle_decodage(self) -> None:
        prochaine = time.perf_counter()

        while not self._arret.is_set():
            with self._verrou:
                capture = self._capture
                cible = self._cible_recherche
                self._cible_recherche = -1

            if capture is None:
                break

            if cible >= 0:
                with self._verrou:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, cible)
                prochaine = time.perf_counter()
                if not self._lecture:
                    self.avancer_d_une_image()
                continue

            if not self._lecture:
                time.sleep(0.01)
                prochaine = time.perf_counter()
                continue

            maintenant = time.perf_counter()
            if maintenant < prochaine:
                time.sleep(min(0.004, prochaine - maintenant))
                continue

            with self._verrou:
                if self._capture is None:
                    break
                ok, brute = self._capture.read()
                position = int(self._capture.get(cv2.CAP_PROP_POS_FRAMES))

            if not ok:
                if self._boucle:
                    with self._verrou:
                        if self._capture is not None:
                            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    prochaine = time.perf_counter()
                    continue
                self._lecture = False
                self.terminee.emit()
                continue

            try:
                self.image_prete.emit(self._convertir(brute))
                self.position_changee.emit(position)
            except RuntimeError:
                break   # l'objet Qt a été détruit pendant l'émission

            # Horloge absolue : le pas est ajouté à l'échéance précédente, pas
            # à l'instant courant. Un retard ponctuel se rattrape au lieu de
            # s'accumuler.
            periode = 1.0 / (self._infos.images_par_seconde * self._vitesse)
            prochaine += periode
            if maintenant - prochaine > 0.5:     # trop de retard : on resynchronise
                prochaine = maintenant + periode
