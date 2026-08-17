"""
Lecture vidéo et audio : un seul démultiplexage, le son comme horloge.

Le décodage se fait dans un fil séparé et transmet les images par signal Qt,
ce qui leur fait traverser la frontière des fils sans verrou explicite.

**Le son mène la marche, et ce n'est pas un détail d'implémentation.** Un
décrochage audio s'entend immédiatement — craquement, silence, changement de
hauteur — alors qu'une image affichée deux millisecondes trop tôt ou trop tard
ne se voit pas. On asservit donc l'image au temps réellement écoulé dans le
flux sonore, jamais l'inverse. Sans piste audio, on retombe sur une horloge
absolue, en accumulant les périodes plutôt qu'en dormant d'une durée fixe : un
`sleep` de durée fixe ferait dériver la lecture de plusieurs secondes sur un
film entier.

PyAV démultiplexe et décode les deux flux d'une seule passe sur le fichier, ce
qui donne des estampilles cohérentes entre l'image et le son — condition
nécessaire à toute synchronisation honnête.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
import sounddevice as sd
from PyQt5 import QtCore

from tvcolor.constantes import obtenir_norme
from tvcolor.son import ChaineSon, ParametresSon

TAUX_SORTIE = 48000
CANAUX = 2
IMAGES_EN_AVANCE = 8
"""Profondeur de la file d'images. Assez pour absorber une image longue à
décoder, assez peu pour qu'un déplacement dans la vidéo réponde tout de suite."""

SECONDES_AUDIO_EN_AVANCE = 0.6


@dataclass
class InfosVideo:
    chemin: str
    largeur: int
    hauteur: int
    images_par_seconde: float
    duree: float
    a_du_son: bool

    def resume(self) -> str:
        son = "son" if self.a_du_son else "muet"
        return (
            f"{Path(self.chemin).name} — {self.largeur}×{self.hauteur}, "
            f"{self.images_par_seconde:.2f} im/s, {son}, "
            f"{int(self.duree // 60)}:{int(self.duree % 60):02d}"
        )


class SourceVideo(QtCore.QObject):
    """Décode un fichier, joue son son, et émet ses images à l'heure."""

    image_prete = QtCore.pyqtSignal(object)
    position_changee = QtCore.pyqtSignal(float)   # en secondes
    terminee = QtCore.pyqtSignal()
    erreur = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._infos: InfosVideo | None = None
        self._conteneur = None
        self._flux_video = None
        self._flux_audio = None
        self._reechantillonneur = None

        self._fil: threading.Thread | None = None
        self._arret = threading.Event()
        self._lecture = False
        self._vitesse = 1.0
        self._boucle = True
        self._volume = 0.8
        self._muet = False

        self._chaine_son: ChaineSon | None = None
        self._parametres_son = ParametresSon(actif=False)
        self._norme_son = "PAL-BG"
        self._verrou_son = threading.Lock()
        self._niveau_video = 0.5
        """Niveau vidéo moyen de la dernière image présentée.

        Il alimente le ronflement intercarrier, qui n'est pas un bruit de fond
        constant : c'est la modulation de la porteuse image qui le fabrique, et
        il monte donc avec la luminosité de l'image. Un générique blanc faisait
        ronfler les postes mal réglés, un fondu au noir les faisait taire."""

        self._verrou = threading.Lock()
        self._file_video: deque = deque()
        self._verrou_audio = threading.Lock()
        self._file_audio: deque = deque()
        self._audio_en_file = 0.0        # durée de son en attente, en secondes

        self._sortie_audio: sd.OutputStream | None = None
        self._latence = 0.0
        self._temps_audio = 0.0
        self._origine_horloge = 0.0
        self._depart_horloge = 0.0
        self._cible_recherche: float | None = None
        self._rattrapage: float | None = None
        """Instant visé par le dernier déplacement, tant qu'il n'est pas atteint.

        Un conteneur ne se déplace qu'à une image-clé, parfois très en amont —
        les trois secondes de la vidéo d'essai n'en contiennent qu'une seule,
        au début. Il faut donc décoder et JETER jusqu'à l'instant demandé,
        puis caler l'horloge sur la première image réellement conservée. Sans
        cela l'horloge annoncerait la position demandée pendant que l'écran
        montrerait le début du fichier."""

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------

    @property
    def infos(self) -> InfosVideo | None:
        return self._infos

    @property
    def en_lecture(self) -> bool:
        return self._lecture

    @property
    def position(self) -> float:
        return self._horloge()

    # ------------------------------------------------------------------
    # Ouverture et fermeture
    # ------------------------------------------------------------------

    def ouvrir(self, chemin: str) -> InfosVideo:
        self.fermer()
        conteneur = av.open(chemin)
        if not conteneur.streams.video:
            conteneur.close()
            raise OSError(f"aucun flux vidéo dans : {chemin}")

        flux_video = conteneur.streams.video[0]
        # Le décodage image par image profite de plusieurs fils : PyAV le fait
        # tout seul si on le lui demande.
        flux_video.thread_type = "AUTO"
        flux_audio = conteneur.streams.audio[0] if conteneur.streams.audio else None

        cadence = float(flux_video.average_rate or 25.0)
        if not (1.0 <= cadence <= 240.0):
            cadence = 25.0

        duree = 0.0
        if flux_video.duration is not None:
            duree = float(flux_video.duration * flux_video.time_base)
        elif conteneur.duration is not None:
            duree = conteneur.duration / av.time_base

        self._conteneur = conteneur
        self._flux_video = flux_video
        self._flux_audio = flux_audio
        self._reechantillonneur = (
            av.audio.resampler.AudioResampler(
                format="flt", layout="stereo", rate=TAUX_SORTIE
            )
            if flux_audio is not None
            else None
        )

        self._infos = InfosVideo(
            chemin=chemin,
            largeur=flux_video.codec_context.width,
            hauteur=flux_video.codec_context.height,
            images_par_seconde=cadence,
            duree=duree,
            a_du_son=flux_audio is not None,
        )

        self._temps_audio = 0.0
        self._depart_horloge = 0.0
        self._origine_horloge = time.perf_counter()
        self._ouvrir_sortie_audio()

        self._arret.clear()
        self._fil = threading.Thread(
            target=self._boucle_de_lecture, daemon=True, name="lecture-video"
        )
        self._fil.start()
        return self._infos

    def fermer(self) -> None:
        self._arret.set()
        self._lecture = False
        if self._fil is not None:
            self._fil.join(timeout=2.0)
            self._fil = None
        self._fermer_sortie_audio()
        with self._verrou:
            if self._conteneur is not None:
                try:
                    self._conteneur.close()
                except Exception:
                    pass
                self._conteneur = None
        self._file_video.clear()
        with self._verrou_audio:
            self._file_audio.clear()
            self._audio_en_file = 0.0
        self._infos = None

    # ------------------------------------------------------------------
    # Commandes
    # ------------------------------------------------------------------

    def lire(self) -> None:
        if self._infos is None:
            return
        self._recaler_horloge(self._horloge())
        self._lecture = True
        if self._sortie_audio is not None and not self._sortie_audio.active:
            try:
                self._sortie_audio.start()
            except Exception:
                pass

    def pause(self) -> None:
        self._lecture = False
        if self._sortie_audio is not None and self._sortie_audio.active:
            try:
                self._sortie_audio.stop()
            except Exception:
                pass

    def basculer(self) -> None:
        self.pause() if self._lecture else self.lire()

    def definir_vitesse(self, vitesse: float) -> None:
        self._vitesse = max(0.05, float(vitesse))

    def definir_boucle(self, actif: bool) -> None:
        self._boucle = bool(actif)

    def definir_volume(self, volume: float) -> None:
        self._volume = float(np.clip(volume, 0.0, 2.0))

    def definir_muet(self, muet: bool) -> None:
        self._muet = bool(muet)

    def definir_son_tv(self, norme: str, parametres: ParametresSon) -> None:
        """Règle la voie son : la norme dont on emprunte la porteuse, et le reste.

        La chaîne n'est reconstruite que si la norme change vraiment. La
        reconstruire à chaque mouvement de curseur remettrait à zéro l'état de
        ses filtres et la phase de son modulateur, et l'on entendrait un
        claquement à chaque cran — le contraire de ce qu'on cherche à régler.
        """
        with self._verrou_son:
            self._parametres_son = parametres
            if parametres.actif and self._chaine_son is None or norme != self._norme_son:
                self._norme_son = norme
                self._chaine_son = (
                    ChaineSon(obtenir_norme(norme), TAUX_SORTIE, parametres)
                    if parametres.actif
                    else None
                )
            elif self._chaine_son is not None:
                self._chaine_son.parametres = parametres
            if not parametres.actif:
                self._chaine_son = None

    def description_son(self) -> str:
        with self._verrou_son:
            return self._chaine_son.description() if self._chaine_son else ""

    def _passer_par_la_porteuse(self, bloc: np.ndarray) -> np.ndarray:
        """Fait subir au son le voyage que lui imposait la porteuse de la norme.

        Le traitement a lieu dans le fil de décodage, jamais dans le rappel de
        la carte son : celui-ci doit rendre la main en quelques centaines de
        microsecondes, et la modulation-démodulation en demande davantage.

        La sortie est monophonique — c'est ce que transportait la porteuse — et
        on la recopie sur les deux canaux, faute de quoi le son sortirait d'un
        seul haut-parleur.
        """
        with self._verrou_son:
            chaine = self._chaine_son
            if chaine is None:
                return bloc
            chaine.parametres.niveau_video = self._niveau_video
            mono = chaine.traiter(bloc)
        return np.repeat(mono[:, None], CANAUX, axis=1).astype(np.float32)

    @property
    def son_actif(self) -> bool:
        """Le son sert-il d'horloge ?

        Hors de la vitesse normale, non : lire plus vite en gardant la hauteur
        demanderait un rééchantillonnage à préservation de tempo, et lire plus
        vite sans y toucher donnerait le miaulement d'une bande accélérée. On
        coupe donc le son et l'on repasse à l'horloge absolue, ce qui est
        franc et prévisible.
        """
        return (
            self._sortie_audio is not None
            and self._infos is not None
            and self._infos.a_du_son
            and abs(self._vitesse - 1.0) < 1e-3
        )

    def chercher(self, secondes: float) -> None:
        with self._verrou:
            self._cible_recherche = max(0.0, float(secondes))

    # ------------------------------------------------------------------
    # Sortie audio
    # ------------------------------------------------------------------

    def _ouvrir_sortie_audio(self) -> None:
        if self._flux_audio is None:
            return
        try:
            self._sortie_audio = sd.OutputStream(
                samplerate=TAUX_SORTIE,
                channels=CANAUX,
                dtype="float32",
                blocksize=0,
                latency="low",
                callback=self._alimenter,
            )
            self._latence = float(self._sortie_audio.latency or 0.0)
        except Exception as souci:
            # Pas de périphérique, pas de pilote : on continue en muet plutôt
            # que de refuser de lire la vidéo.
            self._sortie_audio = None
            self.erreur.emit(f"sortie audio indisponible : {souci}")

    def _fermer_sortie_audio(self) -> None:
        if self._sortie_audio is not None:
            try:
                self._sortie_audio.stop()
                self._sortie_audio.close()
            except Exception:
                pass
            self._sortie_audio = None

    def _alimenter(self, sortie, images, horodatage, statut) -> None:
        """Appelé par le pilote audio. Doit être court et ne rien allouer de gros.

        C'est ici que naît l'horloge de référence : à chaque échantillon remis
        au périphérique, on avance `_temps_audio` de la durée correspondante.
        La latence de sortie est retranchée, faute de quoi l'image précéderait
        le son de tout le tampon du pilote.
        """
        gain = 0.0 if self._muet else self._volume
        ecrits = 0
        with self._verrou_audio:
            while ecrits < images and self._file_audio:
                pts, bloc = self._file_audio[0]
                n = min(len(bloc), images - ecrits)
                sortie[ecrits : ecrits + n] = bloc[:n] * gain
                self._temps_audio = pts + n / TAUX_SORTIE - self._latence
                if n == len(bloc):
                    self._file_audio.popleft()
                else:
                    self._file_audio[0] = (pts + n / TAUX_SORTIE, bloc[n:])
                self._audio_en_file -= n / TAUX_SORTIE
                ecrits += n
        if ecrits < images:
            sortie[ecrits:] = 0.0   # file vide : silence plutôt que craquement
            # Et l'horloge continue d'avancer. Le périphérique consomme ces
            # échantillons de silence comme les autres : le temps passe.
            #
            # Sans cela, l'horloge se figeait dès que la file se vidait — ce
            # qui arrive précisément à la fin du fichier. Les dernières images
            # n'étaient alors jamais publiées, la file vidéo ne se vidait pas,
            # et la condition de rebouclage n'était jamais atteinte : le mode
            # « boucler » restait sans effet.
            self._temps_audio += (images - ecrits) / TAUX_SORTIE

    # ------------------------------------------------------------------
    # Horloge
    # ------------------------------------------------------------------

    def _horloge(self) -> float:
        if self.son_actif and self._lecture:
            return self._temps_audio
        if not self._lecture:
            return self._depart_horloge
        ecoule = time.perf_counter() - self._origine_horloge
        return self._depart_horloge + ecoule * self._vitesse

    def _recaler_horloge(self, secondes: float) -> None:
        self._depart_horloge = secondes
        self._origine_horloge = time.perf_counter()
        self._temps_audio = secondes

    # ------------------------------------------------------------------
    # Boucle de décodage
    #
    # La méthode ne s'appelle pas `_boucle` : ce nom est déjà celui de
    # l'attribut qui dit s'il faut relire le fichier en boucle. Les deux se
    # seraient écrasés, et le fil de décodage aurait reçu un booléen à
    # appeler à la place de sa fonction.
    # ------------------------------------------------------------------

    def _boucle_de_lecture(self) -> None:
        paquets = None
        fin_de_flux = False

        while not self._arret.is_set():
            with self._verrou:
                cible = self._cible_recherche
                self._cible_recherche = None

            if cible is not None:
                paquets = self._appliquer_recherche(cible)
                fin_de_flux = False
                continue

            if paquets is None:
                paquets = self._nouveau_flux()
                if paquets is None:
                    return

            if not self._lecture:
                time.sleep(0.01)
                continue

            fin_de_flux = self._remplir(paquets) or fin_de_flux
            self._presenter()

            if fin_de_flux and not self._file_video:
                if self._boucle:
                    paquets = self._appliquer_recherche(0.0)
                    fin_de_flux = False
                    continue
                self._lecture = False
                self.terminee.emit()

            time.sleep(0.002)

    def _nouveau_flux(self):
        with self._verrou:
            if self._conteneur is None:
                return None
            flux = [self._flux_video]
            if self._flux_audio is not None:
                flux.append(self._flux_audio)
            return self._conteneur.demux(*flux)

    def _appliquer_recherche(self, secondes: float):
        with self._verrou:
            if self._conteneur is None:
                return None
            position = int(secondes / self._flux_video.time_base)
            try:
                self._conteneur.seek(
                    position, stream=self._flux_video, backward=True, any_frame=False
                )
            except Exception:
                pass
            # Les décodeurs gardent un état interne : sans purge, les premières
            # images après un saut seraient celles d'avant.
            self._flux_video.codec_context.flush_buffers()
            if self._flux_audio is not None:
                self._flux_audio.codec_context.flush_buffers()

        self._file_video.clear()
        with self._verrou_audio:
            self._file_audio.clear()
            self._audio_en_file = 0.0
        # La chaîne son porte l'état de ses filtres et la phase de son
        # modulateur : après un saut, ils décrivent un morceau de son qui n'a
        # plus rien à voir avec celui qui arrive.
        with self._verrou_son:
            if self._chaine_son is not None:
                self._chaine_son.reinitialiser()
        self._rattrapage = secondes
        self._recaler_horloge(secondes)
        self.position_changee.emit(secondes)
        return self._nouveau_flux()

    def _remplir(self, paquets) -> bool:
        """Décode jusqu'à ce que les files soient garnies. Vrai si le flux est fini."""
        while (
            len(self._file_video) < IMAGES_EN_AVANCE
            and self._audio_en_file < SECONDES_AUDIO_EN_AVANCE
        ):
            try:
                paquet = next(paquets)
            except StopIteration:
                return True
            except Exception:
                return True

            try:
                trames = paquet.decode()
            except Exception:
                continue

            for trame in trames:
                pts = (
                    float(trame.pts * paquet.stream.time_base)
                    if trame.pts is not None
                    else self._horloge()
                )

                # Rattrapage après un déplacement : on jette tout ce qui
                # précède l'instant demandé, sans le convertir ni le
                # rééchantillonner — c'est là que le temps se gagne.
                if self._rattrapage is not None and pts < self._rattrapage - 0.02:
                    continue

                if paquet.stream.type == "video":
                    if self._rattrapage is not None:
                        # Première image utile : c'est elle qui donne l'heure.
                        self._recaler_horloge(pts)
                        self._rattrapage = None
                    self._file_video.append((pts, trame.to_ndarray(format="rgb24")))
                elif self._reechantillonneur is not None:
                    for morceau in self._reechantillonneur.resample(trame):
                        bloc = morceau.to_ndarray().reshape(-1, CANAUX)
                        bloc = self._passer_par_la_porteuse(bloc)
                        with self._verrou_audio:
                            self._file_audio.append((pts, bloc))
                            self._audio_en_file += len(bloc) / TAUX_SORTIE
        return False

    def _presenter(self) -> None:
        """Émet les images dont l'heure est venue."""
        maintenant = self._horloge()
        derniere = None

        while self._file_video and self._file_video[0][0] <= maintenant:
            derniere = self._file_video.popleft()

        # S'il y a du retard, on ne publie que la dernière image due : afficher
        # les intermédiaires ne ferait qu'aggraver le retard sans rien montrer.
        if derniere is None:
            return
        # Niveau vidéo moyen, pour le ronflement intercarrier. Un pixel sur
        # seize dans chaque direction suffit largement : on cherche une moyenne
        # d'image, pas un détail.
        image = derniere[1]
        self._niveau_video = float(image[::16, ::16].mean()) / 255.0

        try:
            self.image_prete.emit(derniere[1])
            self.position_changee.emit(derniere[0])
        except RuntimeError:
            pass   # l'objet Qt a été détruit pendant l'émission

    # ------------------------------------------------------------------

    def avancer_d_une_image(self) -> None:
        """Décode et publie une image sans lancer la lecture."""
        if self._infos is None:
            return
        flux = self._nouveau_flux()
        if flux is None:
            return
        for paquet in flux:
            if paquet.stream.type != "video":
                continue
            for trame in paquet.decode():
                self.image_prete.emit(trame.to_ndarray(format="rgb24"))
                if trame.pts is not None:
                    self.position_changee.emit(
                        float(trame.pts * paquet.stream.time_base)
                    )
                return
