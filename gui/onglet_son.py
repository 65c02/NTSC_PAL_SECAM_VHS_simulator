"""
Le banc de mesure de la voie son.

Le banc image travaille sur une image fixe ; celui-ci travaille sur un signal
d'essai — sinusoïde, balayage, bruit — ou sur un fichier qu'on lui donne. Dans
les deux cas le principe est le même : on fait passer le signal par la porteuse
son de la norme choisie, et l'on mesure ce qui en ressort au lieu de se fier à
une formule.

Deux instruments :

* la **réponse en fréquence**, mesurée point par point. Rien ne garantit
  *a priori* qu'une chaîne contenant un limiteur, une modulation et une
  démodulation se comporte comme le produit de ses filtres ;
* le **spectre** de l'essai, avant et après, où l'on voit d'un coup d'œil le
  souffle, le ronflement et les harmoniques que la chaîne a fabriqués.

Et deux chiffres : le rapport signal/bruit et le taux de distorsion.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets

from tvcolor import son as son_tv
from tvcolor.constantes import NORMES, obtenir_norme

from .widgets_base import Curseur, Groupe, note

TAUX = 48000

SIGNAUX = [
    ("sinus", "Sinusoïde à 1 kHz"),
    ("balayage", "Balayage 30 Hz → 15 kHz"),
    ("bruit", "Bruit rose"),
    ("accords", "Accords — trois harmoniques"),
]


def signal_d_essai(genre: str, duree: float = 2.0, taux: int = TAUX) -> np.ndarray:
    """Fabrique un signal d'essai. Aucun ne dépasse 0,5 : le limiteur de
    l'émetteur doit rester au repos tant qu'on ne le cherche pas."""
    n = int(taux * duree)
    t = np.arange(n) / taux

    if genre == "sinus":
        return 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)

    if genre == "balayage":
        # Balayage exponentiel : chaque octave dure autant que la suivante,
        # ce qui donne autant de place aux graves qu'aux aigus à l'oreille.
        f0, f1 = 30.0, 15000.0
        k = np.log(f1 / f0) / duree
        phase = 2.0 * np.pi * f0 * (np.exp(k * t) - 1.0) / k
        return 0.5 * np.sin(phase)

    if genre == "bruit":
        blanc = np.random.default_rng(4).normal(0.0, 1.0, n)
        spectre = np.fft.rfft(blanc)
        freqs = np.fft.rfftfreq(n, 1.0 / taux)
        spectre[1:] /= np.sqrt(freqs[1:])      # -3 dB par octave
        spectre[0] = 0.0
        rose = np.fft.irfft(spectre, n)
        return 0.5 * rose / max(np.abs(rose).max(), 1e-9)

    fondamentale = 220.0
    somme = sum(np.sin(2.0 * np.pi * fondamentale * k * t) / k for k in (1, 2, 3, 5))
    return 0.5 * somme / max(np.abs(somme).max(), 1e-9)


class OngletSon(QtWidgets.QScrollArea):
    """Réglages et instruments de la voie son."""

    modifie = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self._norme = "PAL-BG"
        self._rapport_sb: float | None = None
        self._fichier: np.ndarray | None = None
        self._silencieux = False

        contenu = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(contenu)
        colonne.setContentsMargins(8, 8, 8, 8)
        colonne.setSpacing(8)
        self.setWidget(contenu)

        self._construire_source(colonne)
        self._construire_voie(colonne)
        self._construire_instruments(colonne)
        colonne.addStretch(1)

        self.rafraichir()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _construire_source(self, colonne) -> None:
        groupe = Groupe("Signal d'essai")
        self.combo_signal = QtWidgets.QComboBox()
        for code, libelle in SIGNAUX:
            self.combo_signal.addItem(libelle, code)
        self.combo_signal.currentIndexChanged.connect(self._changer)
        groupe.ajouter(self.combo_signal)

        ligne = QtWidgets.QHBoxLayout()
        self.bouton_fichier = QtWidgets.QPushButton("Charger un son…")
        self.bouton_fichier.clicked.connect(self._charger_fichier)
        self.bouton_oublier = QtWidgets.QPushButton("Oublier")
        self.bouton_oublier.setEnabled(False)
        self.bouton_oublier.clicked.connect(self._oublier_fichier)
        ligne.addWidget(self.bouton_fichier, 1)
        ligne.addWidget(self.bouton_oublier)
        boite = QtWidgets.QWidget()
        boite.setLayout(ligne)
        groupe.ajouter(boite)

        self.etiquette_fichier = note("")
        groupe.ajouter(self.etiquette_fichier)
        colonne.addWidget(groupe)

    def _construire_voie(self, colonne) -> None:
        groupe = Groupe("La porteuse son")
        self.case_active = QtWidgets.QCheckBox("Faire passer le son par la porteuse")
        self.case_active.setChecked(True)
        self.case_active.toggled.connect(self._changer)
        groupe.ajouter(self.case_active)

        self.etiquette_porteuse = note("")
        groupe.ajouter(self.etiquette_porteuse)
        colonne.addWidget(groupe)

        groupe = Groupe("Le canal — le même que celui de l'image")
        self.etiquette_cn = note("")
        groupe.ajouter(self.etiquette_cn)
        groupe.ajouter(note(
            "Le rapport signal/bruit se règle dans l'onglet Image. Il n'y a "
            "qu'un canal et qu'une densité de bruit ; ce que la voie son en "
            "récolte se déduit de sa largeur de bande et de sa puissance "
            "d'émission, sans rien choisir."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("Défauts du récepteur")
        self.curseur_intercarrier = Curseur(
            "Ronflement intercarrier", 0.0, 1.0, 0.0, 0.05, "", 2
        )
        self.curseur_niveau_video = Curseur("Niveau vidéo moyen", 0.0, 1.0, 0.5, 0.05, "", 2)
        self.curseur_desaccord = Curseur(
            "Désaccord de l'oscillateur", -20e3, 20e3, 0.0, 500.0, "Hz", 0
        )
        self.curseur_gain = Curseur(
            "Niveau d'entrée du modulateur", -12.0, 30.0, 0.0, 1.0, "dB", 0
        )
        self.curseur_gain_sortie = Curseur(
            "Gain de sortie du poste", -12.0, 24.0, 0.0, 1.0, "dB", 0
        )
        for curseur in (self.curseur_intercarrier, self.curseur_niveau_video,
                        self.curseur_desaccord, self.curseur_gain,
                        self.curseur_gain_sortie):
            curseur.valeur_changee.connect(self._changer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Un poste à intercarrier tire le son du battement entre les deux "
            "porteuses : toute modulation parasite de la porteuse image finit "
            "dans le haut-parleur. Le ronflement monte donc avec le niveau "
            "vidéo — un générique blanc faisait ronfler les postes mal réglés."
        ))
        colonne.addWidget(groupe)

    def _construire_instruments(self, colonne) -> None:
        groupe = Groupe("Mesures")
        self.etiquette_bilan = QtWidgets.QLabel("")
        self.etiquette_bilan.setStyleSheet("font-family: Consolas;")
        self.etiquette_bilan.setWordWrap(True)
        groupe.ajouter(self.etiquette_bilan)

        self.trace_reponse = pg.PlotWidget()
        self.trace_reponse.setMinimumHeight(150)
        self.trace_reponse.setLabel("bottom", "fréquence", units="Hz")
        self.trace_reponse.setLabel("left", "gain", units="dB")
        self.trace_reponse.setLogMode(x=True, y=False)
        self.trace_reponse.showGrid(x=True, y=True, alpha=0.3)
        groupe.ajouter(self.trace_reponse)

        self.trace_spectre = pg.PlotWidget()
        self.trace_spectre.setMinimumHeight(150)
        self.trace_spectre.setLabel("bottom", "fréquence", units="Hz")
        self.trace_spectre.setLabel("left", "niveau", units="dB")
        self.trace_spectre.setLogMode(x=True, y=False)
        self.trace_spectre.showGrid(x=True, y=True, alpha=0.3)
        self.trace_spectre.addLegend(offset=(-10, 10))
        groupe.ajouter(self.trace_spectre)

        ligne = QtWidgets.QHBoxLayout()
        self.bouton_ecouter_avant = QtWidgets.QPushButton("Écouter l'original")
        self.bouton_ecouter_apres = QtWidgets.QPushButton("Écouter par la porteuse")
        self.bouton_ecouter_avant.clicked.connect(lambda: self._ecouter(False))
        self.bouton_ecouter_apres.clicked.connect(lambda: self._ecouter(True))
        ligne.addWidget(self.bouton_ecouter_avant)
        ligne.addWidget(self.bouton_ecouter_apres)
        boite = QtWidgets.QWidget()
        boite.setLayout(ligne)
        groupe.ajouter(boite)
        colonne.addWidget(groupe)

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------

    def definir_contexte(self, norme: str, rapport_sb: float | None) -> None:
        """Reçoit la norme et le bruit choisis dans l'onglet Image."""
        change = (norme, rapport_sb) != (self._norme, self._rapport_sb)
        self._norme, self._rapport_sb = norme, rapport_sb
        if change:
            self.rafraichir()

    def parametres(self) -> son_tv.ParametresSon:
        return son_tv.ParametresSon(
            actif=self.case_active.isChecked(),
            rapport_signal_bruit=self._rapport_sb,
            intercarrier=self.curseur_intercarrier.valeur(),
            niveau_video=self.curseur_niveau_video.valeur(),
            desaccord=self.curseur_desaccord.valeur(),
            gain_entree=10.0 ** (self.curseur_gain.valeur() / 20.0),
            gain_sortie=10.0 ** (self.curseur_gain_sortie.valeur() / 20.0),
        )

    def signal(self) -> np.ndarray:
        if self._fichier is not None:
            return self._fichier
        return signal_d_essai(self.combo_signal.currentData())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _changer(self, *_args) -> None:
        if self._silencieux:
            return
        self.rafraichir()
        self.modifie.emit()

    def _charger_fichier(self) -> None:
        chemin, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Charger un son", "",
            "Sons et vidéos (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.mp4 *.mkv)",
        )
        if not chemin:
            return
        try:
            import av

            conteneur = av.open(chemin)
            flux = next((f for f in conteneur.streams if f.type == "audio"), None)
            if flux is None:
                raise ValueError("aucune piste audio dans ce fichier")
            reechantillonneur = av.AudioResampler(
                format="flt", layout="mono", rate=TAUX
            )
            morceaux = []
            duree = 0
            for trame in conteneur.decode(flux):
                for part in reechantillonneur.resample(trame):
                    bloc = part.to_ndarray().reshape(-1)
                    morceaux.append(bloc)
                    duree += bloc.size
                if duree > TAUX * 20:      # vingt secondes suffisent à mesurer
                    break
            conteneur.close()
            if not morceaux:
                raise ValueError("piste audio vide")
            audio = np.concatenate(morceaux).astype(np.float64)
            crete = max(np.abs(audio).max(), 1e-9)
            self._fichier = 0.5 * audio / crete
        except Exception as raison:                      # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Chargement impossible", f"{type(raison).__name__} : {raison}"
            )
            return

        from pathlib import Path

        self.etiquette_fichier.setText(
            f"{Path(chemin).name} — {self._fichier.size / TAUX:.1f} s, "
            "ramené en mono et normalisé à mi-échelle"
        )
        self.bouton_oublier.setEnabled(True)
        self._changer()

    def _oublier_fichier(self) -> None:
        self._fichier = None
        self.etiquette_fichier.setText("")
        self.bouton_oublier.setEnabled(False)
        self._changer()

    def _ecouter(self, par_la_porteuse: bool) -> None:
        try:
            import sounddevice as sd
        except Exception:                                # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Écoute", "sounddevice n'est pas disponible."
            )
            return

        audio = self.signal()
        if par_la_porteuse:
            audio = son_tv.transmettre(
                audio, TAUX, obtenir_norme(self._norme), self.parametres()
            )
        try:
            sd.stop()
            sd.play(np.asarray(audio, np.float32) * 0.8, TAUX)
        except Exception as raison:                      # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Écoute", str(raison))

    # ------------------------------------------------------------------
    # Mesure et tracés
    # ------------------------------------------------------------------

    def rafraichir(self) -> None:
        norme = obtenir_norme(self._norme)
        voie = norme.son
        parametres = self.parametres()

        detail = (
            f"FM, ±{voie.deviation / 1e3:.0f} kHz, préaccentuation "
            f"{voie.preaccentuation * 1e6:.0f} µs"
            if voie.modulation == "FM"
            else f"AM, taux {voie.taux_am:.0%}, sans préaccentuation"
        )
        self.etiquette_porteuse.setText(
            f"{norme.nom} — porteuse à +{voie.decalage / 1e6:.1f} MHz de la "
            f"porteuse image. {detail}. Émise à {voie.niveau_porteuse_db:.0f} dB "
            f"sous l'image, bande audio {voie.bande_audio / 1e3:.0f} kHz."
        )

        if self._rapport_sb is None:
            self.etiquette_cn.setText("Canal parfait — aucun bruit.")
        else:
            cn = son_tv.rapport_porteuse_bruit(norme, self._rapport_sb)
            gain = son_tv.gain_de_demodulation_db(voie)
            self.etiquette_cn.setText(
                f"Image {self._rapport_sb:.0f} dB  →  porteuse son {cn:.1f} dB.  "
                + (
                    f"La démodulation de fréquence en rend environ {gain:.0f} dB."
                    if gain > 0
                    else "La démodulation d'amplitude n'en rend aucun."
                )
            )

        self._mesurer(norme, parametres)

    def _mesurer(self, norme, parametres) -> None:
        bilan = son_tv.evaluer(norme, TAUX, parametres)
        self.etiquette_bilan.setText(
            f"Signal / bruit  {bilan.rapport_signal_bruit:6.1f} dB\n"
            f"Distorsion      {bilan.distorsion:6.2f} %\n"
            + (
                f"Porteuse/bruit  {bilan.porteuse_bruit:6.1f} dB"
                if bilan.porteuse_bruit is not None
                else "Porteuse/bruit     — (canal parfait)"
            )
        )

        frequences, gains = son_tv.reponse_en_frequence(
            norme, TAUX, parametres, points=16, duree=0.15
        )
        self.trace_reponse.clear()
        self.trace_reponse.plot(
            frequences, gains, pen=pg.mkPen("#2b6cb0", width=2), symbol="o", symbolSize=4
        )
        self.trace_reponse.addLine(y=0.0, pen=pg.mkPen("#a0aec0", style=QtCore.Qt.DashLine))
        self.trace_reponse.setYRange(-40.0, 10.0)

        entree = self.signal()
        sortie = np.asarray(
            son_tv.transmettre(entree, TAUX, norme, parametres), dtype=np.float64
        )
        self.trace_spectre.clear()
        for nom, x, couleur in (
            ("avant", entree, "#a0aec0"),
            ("après", sortie, "#c53030"),
        ):
            n = min(x.size, 1 << 15)
            fenetre = np.hanning(n)
            spectre = np.abs(np.fft.rfft(x[:n] * fenetre)) / (n / 4)
            freqs = np.fft.rfftfreq(n, 1.0 / TAUX)
            db = 20.0 * np.log10(np.maximum(spectre, 1e-9))
            self.trace_spectre.plot(
                freqs[1:], db[1:], pen=pg.mkPen(couleur, width=1), name=nom
            )
        self.trace_spectre.setYRange(-120.0, 0.0)
        self.trace_spectre.setXRange(np.log10(20.0), np.log10(24000.0))
