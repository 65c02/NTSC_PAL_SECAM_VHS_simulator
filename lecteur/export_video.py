"""
Export MP4 : enregistrer ce que le téléviseur montre, pas ce que le fichier contient.

L'export refait exactement le trajet du lecteur — les mêmes shaders, la même
voie son, les mêmes réglages — puis écrit le résultat dans un fichier. Deux
principes le gouvernent :

* **on enregistre ce qu'on voit.** Pas l'image décodée nue, mais l'image telle
  que la passe de présentation la produit : courbure, réponse du tube, halo,
  lignes de balayage. Le réglage qu'on vient de faire est celui qu'on retrouve
  dans le fichier ;

* **la géométrie suit la cible, pas la fenêtre.** Les lignes de balayage sont
  intégrées sur la surface du pixel de DESTINATION. Exporter en 1440 points de
  haut depuis une fenêtre de 700 donne donc des lignes bien plus franches, et
  c'est juste : il y a deux fois plus de pixels pour les porter.

Le travail se fait dans le fil de l'interface, et il le faut : le contexte
OpenGL y est attaché, et l'y arracher pour le confier à un fil de travail
coûterait plus de complications que l'export ne dure de secondes.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PyQt5 import QtCore, QtWidgets

from tvcolor.constantes import obtenir_norme
from tvcolor.son import ChaineSon, ParametresSon

TAUX_AUDIO = 48000
CANAUX = 2


@dataclass
class ReglagesExport:
    """Ce que l'utilisateur choisit avant de lancer l'export."""

    destination: str
    hauteur: int = 1080
    """Hauteur de l'image exportée. La largeur en découle par le format de la
    norme — 4:3 — arrondie à un nombre pair, ce qu'exige le codage 4:2:0."""

    debit: int = 12_000_000
    """Débit vidéo visé, en bits par seconde."""

    codec: str = "libx264"
    preset: str = "medium"
    exporter_le_son: bool = True


def dimensions(hauteur: int) -> tuple[int, int]:
    """Dimensions d'une image exportée, au format 4:3 et en nombres pairs.

    Le codage 4:2:0 sous-échantillonne la chrominance d'un facteur deux dans
    les deux directions : une dimension impaire n'a rien à quoi s'accrocher, et
    les encodeurs la refusent ou l'arrondissent en silence.
    """
    hauteur = max(64, int(hauteur) // 2 * 2)
    largeur = int(round(hauteur * 4.0 / 3.0)) // 2 * 2
    return largeur, hauteur


class ExportateurMP4(QtCore.QObject):
    """Convertit une vidéo en la faisant passer par le téléviseur."""

    progression = QtCore.pyqtSignal(int, int)     # image courante, total
    terminee = QtCore.pyqtSignal(str)
    echouee = QtCore.pyqtSignal(str)

    def __init__(self, vue, parent=None):
        super().__init__(parent)
        self.vue = vue
        self._annule = False

    def annuler(self) -> None:
        self._annule = True

    # ------------------------------------------------------------------

    def exporter(
        self,
        source: str,
        reglages: ReglagesExport,
        norme: str,
        parametres_son: ParametresSon,
    ) -> None:
        """Lit `source`, rend chaque image, écrit `reglages.destination`."""
        self._annule = False
        entree = sortie = None
        try:
            entree = av.open(source)
            flux_video = next(
                (f for f in entree.streams if f.type == "video"), None
            )
            if flux_video is None:
                raise ValueError("le fichier ne contient pas de piste vidéo")
            flux_video.thread_type = "AUTO"
            flux_audio = next(
                (f for f in entree.streams if f.type == "audio"), None
            )

            largeur, hauteur = dimensions(reglages.hauteur)
            cadence = flux_video.average_rate or Fraction(25, 1)

            sortie = av.open(reglages.destination, mode="w")
            piste_video = sortie.add_stream(reglages.codec, rate=cadence)
            piste_video.width = largeur
            piste_video.height = hauteur
            piste_video.pix_fmt = "yuv420p"
            piste_video.bit_rate = int(reglages.debit)
            try:
                piste_video.options = {"preset": reglages.preset}
            except Exception:
                pass

            piste_audio = None
            if flux_audio is not None and reglages.exporter_le_son:
                piste_audio = sortie.add_stream("aac", rate=TAUX_AUDIO)
                piste_audio.bit_rate = 192_000

            total = self._compter_images(flux_video, cadence)

            son = None
            if piste_audio is not None:
                son = self._preparer_son(source, norme, parametres_son)

            n = self._ecrire_images(
                entree, flux_video, sortie, piste_video, largeur, hauteur, total
            )
            if self._annule:
                raise InterruptedError

            if piste_audio is not None and son is not None:
                self._ecrire_son(sortie, piste_audio, son)

            for paquet in piste_video.encode():
                sortie.mux(paquet)
            if piste_audio is not None:
                for paquet in piste_audio.encode():
                    sortie.mux(paquet)

            sortie.close()
            entree.close()
            self.terminee.emit(f"{n} images écrites dans {Path(reglages.destination).name}")
            return

        except InterruptedError:
            message = "export interrompu"
        except Exception as raison:                      # noqa: BLE001
            message = f"{type(raison).__name__} : {raison}"

        for objet in (sortie, entree):
            try:
                if objet is not None:
                    objet.close()
            except Exception:
                pass
        if self._annule:
            Path(reglages.destination).unlink(missing_ok=True)
        self.echouee.emit(message)

    # ------------------------------------------------------------------

    @staticmethod
    def _compter_images(flux, cadence) -> int:
        if flux.frames:
            return int(flux.frames)
        if flux.duration and flux.time_base:
            return int(float(flux.duration * flux.time_base) * float(cadence))
        return 0

    def _ecrire_images(
        self, entree, flux, sortie, piste, largeur, hauteur, total
    ) -> int:
        n = 0
        for trame in entree.decode(flux):
            if self._annule:
                return n

            self.vue.definir_image(trame.to_ndarray(format="rgb24"))
            rendue = self.vue.rendre_pour_export(largeur, hauteur)
            if rendue is None:
                raise RuntimeError("le rendu hors écran n'a rien produit")

            image = av.VideoFrame.from_ndarray(rendue, format="rgb24")
            for paquet in piste.encode(image):
                sortie.mux(paquet)

            n += 1
            self.progression.emit(n, total)
            # L'interface doit rester vivante : c'est le même fil qui dessine.
            QtWidgets.QApplication.processEvents()
        return n

    @staticmethod
    def _preparer_son(source: str, norme: str, parametres: ParametresSon) -> np.ndarray:
        """Décode toute la piste et la fait passer par la porteuse, d'un trait.

        Un second passage sur le fichier, uniquement pour le son. C'est plus
        simple que de l'entrelacer avec les images, et le coût est dérisoire :
        la chaîne son tourne à moins d'un dixième du temps réel.

        Le niveau vidéo, dont dépend le ronflement intercarrier, est ici figé à
        sa valeur de réglage plutôt que suivi image par image. C'est la seule
        différence avec la lecture, et elle est assumée : suivre le niveau
        exigerait d'entrelacer les deux décodages pour un effet que personne
        n'entendrait.
        """
        conteneur = av.open(source)
        try:
            flux = next((f for f in conteneur.streams if f.type == "audio"), None)
            if flux is None:
                return np.zeros(0, np.float32)
            reechantillonneur = av.AudioResampler(
                format="flt", layout="stereo", rate=TAUX_AUDIO
            )
            chaine = ChaineSon(obtenir_norme(norme), TAUX_AUDIO, parametres)
            morceaux = []
            for trame in conteneur.decode(flux):
                for part in reechantillonneur.resample(trame):
                    bloc = part.to_ndarray().reshape(-1, CANAUX)
                    morceaux.append(chaine.traiter(bloc))
            if not morceaux:
                return np.zeros(0, np.float32)
            return np.concatenate(morceaux)
        finally:
            conteneur.close()

    @staticmethod
    def _ecrire_son(sortie, piste, mono: np.ndarray) -> None:
        """Encode le son traité. Mono dupliqué sur deux canaux."""
        if mono.size == 0:
            return
        stereo = np.repeat(np.asarray(mono, np.float32)[None, :], CANAUX, axis=0)

        taille = 1024
        for debut in range(0, stereo.shape[1], taille):
            morceau = np.ascontiguousarray(stereo[:, debut : debut + taille])
            trame = av.AudioFrame.from_ndarray(morceau, format="fltp", layout="stereo")
            trame.rate = TAUX_AUDIO
            for paquet in piste.encode(trame):
                sortie.mux(paquet)
