"""
Fenêtre du simulateur radio.

On charge un fichier, on choisit un service, on écoute. Les réglages agissent
pendant la lecture : la chaîne est en flux, et changer le rapport porteuse/bruit
au milieu d'une phrase s'entend immédiatement — c'est là tout l'intérêt.

Le fil de production tourne à part et remplit une file ; le rappel audio, lui,
ne fait que recopier. Faire tourner les filtres dans le rappel serait plus
simple et se paierait au premier hoquet : le pilote audio n'attend pas.
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from gui.widgets_base import Curseur, Glissiere, Groupe, note

from .chaine import ChaineRadio, ParametresRadio, filtre_haut_parleur
from .services import F_AUDIO, SERVICES, obtenir_service
from .source_audio import charger, ecrire_mp3, ecrire_wav, reponse_en_frequence

FORMATS = "Audio (*.mp3 *.wav *.flac *.m4a *.ogg *.opus *.aac *.wma)"
TAILLE_BLOC = 4_096


class Lecture(QtCore.QObject):
    """Produit le son traité, dans son propre fil, et le sert au pilote audio."""

    position_changee = QtCore.pyqtSignal(float)
    finie = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio = np.zeros(0)
        self.parametres = ParametresRadio()
        self._chaine = ChaineRadio(self.parametres)
        self._verrou = threading.Lock()
        self._file: queue.Queue = queue.Queue(maxsize=12)
        self._fil: threading.Thread | None = None
        self._arret = threading.Event()
        self._flux = None
        self._indice = 0
        self._reconstruire = False
        self.dernier_bloc = np.zeros(TAILLE_BLOC)

    # -- réglages --------------------------------------------------------

    def definir_parametres(self, parametres: ParametresRadio) -> None:
        with self._verrou:
            changement = parametres.service != self.parametres.service
            self.parametres = parametres
            self._reconstruire = self._reconstruire or changement

    def definir_source(self, audio: np.ndarray) -> None:
        self.arreter()
        self.audio = np.asarray(audio, dtype=np.float64)
        self._indice = 0

    @property
    def duree(self) -> float:
        return self.audio.size / F_AUDIO if self.audio.size else 0.0

    def position(self) -> float:
        return self._indice / F_AUDIO

    def chercher(self, secondes: float) -> None:
        with self._verrou:
            self._indice = int(np.clip(secondes, 0.0, self.duree) * F_AUDIO)
            self._reconstruire = True

    # -- transport -------------------------------------------------------

    def en_lecture(self) -> bool:
        return self._fil is not None and self._fil.is_alive()

    def lire(self) -> None:
        if self.en_lecture() or self.audio.size == 0:
            return
        import sounddevice as sd

        self._arret.clear()
        while not self._file.empty():
            self._file.get_nowait()

        self._fil = threading.Thread(target=self._produire, daemon=True)
        self._fil.start()

        def rappel(sortie, trames, _temps, _statut):
            try:
                bloc = self._file.get_nowait()
            except queue.Empty:
                sortie.fill(0.0)
                return
            if bloc.size < trames:
                bloc = np.pad(bloc, (0, trames - bloc.size))
            sortie[:, 0] = np.clip(bloc[:trames], -1.0, 1.0)

        self._flux = sd.OutputStream(
            samplerate=F_AUDIO, channels=1, blocksize=TAILLE_BLOC, callback=rappel
        )
        self._flux.start()

    def arreter(self) -> None:
        self._arret.set()
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None
        if self._fil is not None:
            self._fil.join(timeout=1.0)
            self._fil = None

    def _produire(self) -> None:
        while not self._arret.is_set():
            with self._verrou:
                if self._reconstruire:
                    self._chaine = ChaineRadio(self.parametres)
                    self._reconstruire = False
                else:
                    self._chaine.parametres = self.parametres
                taille = self._chaine.taille_de_bloc(TAILLE_BLOC)
                debut = self._indice
                bloc = self.audio[debut : debut + taille]
                self._indice = debut + taille
                if bloc.size == 0:
                    self._indice = 0
                    bloc = self.audio[:taille]

            sortie = self._chaine.traiter(bloc)
            self.dernier_bloc = sortie
            try:
                self._file.put(sortie, timeout=1.0)
            except queue.Full:
                continue
            self.position_changee.emit(debut / F_AUDIO)


class FenetreRadio(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Radio — AM, FM, BLU : de l'émetteur au haut-parleur")
        self.resize(1240, 800)
        self.setAcceptDrops(True)

        self._silencieux = False
        self.lecture = Lecture(self)
        self.lecture.position_changee.connect(self._sur_position)

        self._construire()
        self._appliquer()

        self._minuteur = QtCore.QTimer(self)
        self._minuteur.timeout.connect(self._rafraichir_instruments)
        self._minuteur.start(80)

    # ------------------------------------------------------------------

    def _construire(self) -> None:
        self._construire_barre()

        self.instruments = self._construire_instruments()
        panneau = self._construire_panneau()

        separation = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        conteneur = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(conteneur)
        colonne.setContentsMargins(6, 6, 6, 6)
        colonne.addWidget(self.instruments, 1)
        colonne.addWidget(self._construire_transport())
        separation.addWidget(conteneur)
        separation.addWidget(panneau)
        separation.setStretchFactor(0, 1)
        separation.setSizes([840, 400])
        self.setCentralWidget(separation)

        self._etat = QtWidgets.QLabel("Aucun fichier — Ctrl+O pour en ouvrir un")
        self.statusBar().addWidget(self._etat, 1)

    def _construire_barre(self) -> None:
        barre = self.addToolBar("Source")
        barre.setMovable(False)
        barre.addAction("Ouvrir…", self._ouvrir).setShortcut("Ctrl+O")
        barre.addSeparator()

        barre.addWidget(QtWidgets.QLabel("  Service  "))
        self.combo_service = QtWidgets.QComboBox()
        for code, service in SERVICES.items():
            self.combo_service.addItem(service.nom, code)
        self.combo_service.setCurrentIndex(self.combo_service.findData("pmr446"))
        self.combo_service.currentIndexChanged.connect(self._sur_service)
        self.combo_service.setMinimumWidth(280)
        barre.addWidget(self.combo_service)

        barre.addSeparator()
        self.action_export = barre.addAction("Exporter…", self._exporter)
        self.action_export.setShortcut("Ctrl+E")
        self.action_export.setEnabled(False)

    def _construire_transport(self) -> QtWidgets.QWidget:
        self.bouton_lecture = QtWidgets.QToolButton()
        self.bouton_lecture.setText("▶")
        self.bouton_lecture.setFixedWidth(40)
        self.bouton_lecture.clicked.connect(self._basculer)

        self.barre_position = Glissiere(QtCore.Qt.Horizontal)
        self.barre_position.setEnabled(False)
        self.barre_position.sliderMoved.connect(
            lambda ms: self.lecture.chercher(ms / 1000.0)
        )
        self.etiquette_temps = QtWidgets.QLabel("0:00 / 0:00")
        self.etiquette_temps.setStyleSheet("font-family: Consolas;")

        ligne = QtWidgets.QHBoxLayout()
        ligne.setContentsMargins(0, 0, 0, 0)
        ligne.addWidget(self.bouton_lecture)
        ligne.addWidget(self.barre_position, 1)
        ligne.addWidget(self.etiquette_temps)

        widget = QtWidgets.QWidget()
        widget.setLayout(ligne)
        return widget

    def _construire_instruments(self) -> QtWidgets.QWidget:
        import pyqtgraph as pg

        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        onglets = QtWidgets.QTabWidget()

        self.trace_spectre = pg.PlotWidget()
        self.trace_spectre.setLabel("bottom", "fréquence", units="Hz")
        self.trace_spectre.setLabel("left", "niveau", units="dB")
        self.trace_spectre.setLogMode(x=True, y=False)
        self.trace_spectre.setYRange(-90, 10)
        self.trace_spectre.showGrid(x=True, y=True, alpha=0.3)
        self.courbe_spectre = self.trace_spectre.plot(pen=pg.mkPen("#2b6cb0", width=1.4))
        onglets.addTab(self.trace_spectre, "Spectre de sortie")

        self.trace_onde = pg.PlotWidget()
        self.trace_onde.setLabel("bottom", "temps", units="s")
        self.trace_onde.setYRange(-1.05, 1.05)
        self.trace_onde.showGrid(x=True, y=True, alpha=0.3)
        self.courbe_onde = self.trace_onde.plot(pen=pg.mkPen("#c53030", width=1.0))
        onglets.addTab(self.trace_onde, "Forme d'onde")

        self.trace_hp = pg.PlotWidget()
        self.trace_hp.setLabel("bottom", "fréquence", units="Hz")
        self.trace_hp.setLabel("left", "gain", units="dB")
        self.trace_hp.setLogMode(x=True, y=False)
        self.trace_hp.showGrid(x=True, y=True, alpha=0.3)
        self.courbe_hp = self.trace_hp.plot(pen=pg.mkPen("#2f855a", width=2.0))
        onglets.addTab(self.trace_hp, "Haut-parleur")

        return onglets

    # ------------------------------------------------------------------

    @staticmethod
    def _page():
        defilement = QtWidgets.QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        defilement.setMinimumWidth(380)
        contenu = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(contenu)
        colonne.setContentsMargins(8, 8, 8, 8)
        colonne.setSpacing(8)
        defilement.setWidget(contenu)
        return defilement, colonne

    def _construire_panneau(self) -> QtWidgets.QWidget:
        onglets = QtWidgets.QTabWidget()
        onglets.addTab(self._onglet_service(), "Service")
        onglets.addTab(self._onglet_canal(), "Canal")
        onglets.addTab(self._onglet_poste(), "Poste")
        return onglets

    def _onglet_service(self) -> QtWidgets.QWidget:
        defilement, colonne = self._page()

        groupe = Groupe("Ce service")
        self.etiquette_service = note("")
        groupe.ajouter(self.etiquette_service)
        colonne.addWidget(groupe)

        groupe = Groupe("L'émetteur")
        self.curseur_niveau = Curseur("Niveau de modulation", 0.05, 1.50, 0.9, 0.01, "", 2)
        self.curseur_compression = Curseur("Compression du micro", 0.0, 24.0, 12.0, 1.0, " dB", 0)
        for curseur in (self.curseur_niveau, self.curseur_compression):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Le niveau de modulation est le potentiomètre d'entrée de "
            "l'émetteur, et il compte d'autant plus que la préaccentuation est "
            "forte : à 750 µs, un kilohertz ressort treize décibels et demi plus "
            "haut qu'il n'est entré.\n\n"
            "Le monter au-delà du réglage nominal fait entendre la "
            "SURMODULATION. Ce n'est pas un défaut à éviter : c'est le son "
            "ordinaire d'une CB, et en AM le détecteur d'enveloppe replie "
            "carrément la partie négative."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    def _onglet_canal(self) -> QtWidgets.QWidget:
        defilement, colonne = self._page()

        groupe = Groupe("Le bruit")
        self.case_bruit = QtWidgets.QCheckBox("Canal bruité")
        self.case_bruit.setChecked(True)
        self.case_bruit.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_bruit)
        self.curseur_cn = Curseur("Porteuse / bruit", -6.0, 60.0, 22.0, 1.0, " dB", 0)
        self.curseur_cn.valeur_changee.connect(self._appliquer)
        groupe.ajouter(self.curseur_cn)
        groupe.ajouter(note(
            "Rapport porteuse/bruit dans la bande du RÉCEPTEUR, ce qui est la "
            "seule définition qui ait un sens : le bruit thermique est blanc, "
            "donc sa puissance dépend de la largeur où on le mesure.\n\n"
            "Descendez-le lentement sur un service FM : le son reste propre, "
            "propre, propre… puis s'effondre d'un coup en craquements. C'est le "
            "SEUIL, et il n'a pas été programmé — c'est le vecteur de bruit qui "
            "se met à faire le tour de l'origine, et le discriminateur qui sort "
            "une impulsion à chaque tour."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("La propagation")
        self.curseur_fading = Curseur("Évanouissement", 0.0, 1.0, 0.0, 0.05, "", 2)
        self.curseur_vitesse = Curseur("Vitesse de l'évanouissement", 0.1, 20.0, 1.0, 0.1, " Hz", 1)
        self.curseur_parasites = Curseur("Parasites atmosphériques", 0.0, 1.0, 0.0, 0.05, "", 2)
        for curseur in (self.curseur_fading, self.curseur_vitesse, self.curseur_parasites):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "L'évanouissement est un processus gaussien complexe filtré : son "
            "module suit une loi de Rayleigh, ce qui est le résultat classique — "
            "et il n'a pas fallu l'écrire, il tombe du filtrage. Une fraction de "
            "hertz pour la propagation décamétrique de la CB, quelques hertz "
            "pour un poste VHF en voiture.\n\n"
            "Les parasites atmosphériques, eux, ne sont pas gaussiens mais "
            "IMPULSIONNELS : un souffle se supporte, un craquement fait "
            "sursauter. C'est la signature des ondes moyennes et du 27 MHz."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("Les voisins")
        self.curseur_cocanal = Curseur("Seconde station, même canal", 0.0, 1.0, 0.0, 0.05, "", 2)
        self.curseur_ecart = Curseur("Écart des deux porteuses", 100.0, 3000.0, 1000.0, 50.0, " Hz", 0)
        self.curseur_adjacent = Curseur("Station du canal voisin", 0.0, 2.0, 0.0, 0.05, "", 2)
        for curseur in (self.curseur_cocanal, self.curseur_ecart, self.curseur_adjacent):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Deux stations sur le même canal : leurs porteuses battent, et le "
            "détecteur d'enveloppe voit le module osciller à leur ÉCART. Le "
            "sifflement n'est pas ajouté — c'est la somme de deux nombres "
            "complexes, et sa fréquence est le réglage juste au-dessus.\n\n"
            "C'est pour cela que l'aéronautique est restée en amplitude : en "
            "fréquence, le plus fort aurait effacé l'autre en silence, et "
            "personne n'aurait su qu'il y avait eu collision. Essayez sur la VHF "
            "aéronautique, puis sur la VHF marine — la différence est le sujet."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    def _onglet_poste(self) -> QtWidgets.QWidget:
        defilement, colonne = self._page()

        groupe = Groupe("Le récepteur")
        self.curseur_desaccord = Curseur("Désaccord", -600.0, 600.0, 0.0, 10.0, " Hz", 0)
        self.curseur_squelch = Curseur("Silencieux", 0.0, 1.0, 0.0, 0.05, "", 2)
        for curseur in (self.curseur_desaccord, self.curseur_squelch):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Le désaccord ne s'entend presque pas en AM ni en FM. En bande "
            "latérale unique, il DÉCALE tout le spectre audio : les harmoniques "
            "cessent d'être des multiples de la fondamentale, et la voix prend "
            "le timbre que les cibistes appellent Donald. C'est pour cela qu'un "
            "poste BLU a un bouton d'accord fin.\n\n"
            "Le silencieux écoute le souffle ENTRE 5 et 7 kHz, là où il n'y a "
            "jamais de parole : fort = pas de signal, faible = signal présent. "
            "Le « pschit » de fin de transmission en découle tout seul."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("Le haut-parleur")
        self.case_hp = QtWidgets.QCheckBox("Écouter par le haut-parleur du poste")
        self.case_hp.setChecked(True)
        self.case_hp.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_hp)
        self.curseur_volume = Curseur("Volume", 0.0, 3.0, 1.0, 0.05, "", 2)
        self.curseur_volume.valeur_changee.connect(self._appliquer)
        groupe.ajouter(self.curseur_volume)
        self.etiquette_hp = note("")
        groupe.ajouter(self.etiquette_hp)
        groupe.ajouter(note(
            "Un talkie-walkie ne sonne pas comme un talkie-walkie à cause de sa "
            "modulation : un fichier simplement filtré entre 300 et 3000 Hz n'y "
            "ressemble pas. C'est le transducteur de trente-six millimètres monté "
            "dans un boîtier plastique fermé qui fait le timbre — il ne descend "
            "pas, il résonne à onze cents hertz, et il s'éteint vite.\n\n"
            "Décochez la case pour entendre ce que le démodulateur a rendu, "
            "avant le haut-parleur. L'écart est saisissant."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    # ------------------------------------------------------------------

    def _parametres(self) -> ParametresRadio:
        return ParametresRadio(
            service=self.combo_service.currentData(),
            cn_db=self.curseur_cn.valeur() if self.case_bruit.isChecked() else None,
            desaccord=self.curseur_desaccord.valeur(),
            compression_db=self.curseur_compression.valeur(),
            niveau_entree=self.curseur_niveau.valeur(),
            squelch=self.curseur_squelch.valeur(),
            evanouissement=self.curseur_fading.valeur(),
            vitesse_evanouissement=self.curseur_vitesse.valeur(),
            parasites=self.curseur_parasites.valeur(),
            co_canal=self.curseur_cocanal.valeur(),
            ecart_co_canal=self.curseur_ecart.valeur(),
            adjacent=self.curseur_adjacent.valeur(),
            haut_parleur=self.case_hp.isChecked(),
            volume=self.curseur_volume.valeur(),
        )

    def _sur_service(self, *_args) -> None:
        """Un service change tous les réglages nominaux du poste d'un coup."""
        service = obtenir_service(self.combo_service.currentData())
        precedent, self._silencieux = self._silencieux, True
        try:
            self.curseur_niveau.definir(service.niveau_modulation)
            self.curseur_compression.definir(service.compression_db)
            self.curseur_cn.definir(service.cn_defaut)
        finally:
            self._silencieux = precedent
        self._appliquer()

    def _appliquer(self, *_args) -> None:
        if self._silencieux:
            return
        parametres = self._parametres()
        self.lecture.definir_parametres(parametres)

        service = obtenir_service(parametres.service)
        basse, haute = service.bande_mhz
        self.etiquette_service.setText(
            f"{service.nom}\n\n"
            f"{service.caractere}\n\n"
            f"Modulation {service.modulation} · bande {basse:.3f}–{haute:.3f} MHz · "
            f"canaux de {service.espacement / 1e3:.2f} kHz · "
            f"audio {service.audio_basse:.0f}–{service.audio_haute:.0f} Hz · "
            f"puissance {service.puissance:g} W.\n\n"
            + (
                f"Excursion ±{service.excursion / 1e3:.1f} kHz, indice β = "
                f"{service.indice_modulation_fm:.2f}, largeur de Carson "
                f"{service.largeur_carson / 1e3:.0f} kHz, gain de démodulation "
                f"+{service.gain_fm_db():.1f} dB."
                if service.modulation == "FM"
                else f"Largeur occupée {service.largeur_carson / 1e3:.1f} kHz."
            )
            + f"\n\nSimulé sur une enveloppe complexe à {service.f_travail / 1e3:.0f} kHz."
        )
        self.etiquette_hp.setText(
            f"{service.haut_parleur.nom} — {service.haut_parleur.coupure_basse:.0f} à "
            f"{service.haut_parleur.coupure_haute:.0f} Hz, résonance à "
            f"{service.haut_parleur.resonance:.0f} Hz "
            f"(+{service.haut_parleur.pointe_db:.0f} dB)."
        )
        frequences, gains = reponse_en_frequence(
            filtre_haut_parleur(service.haut_parleur, F_AUDIO)
        )
        garde = frequences > 20.0
        self.courbe_hp.setData(frequences[garde], gains[garde])

    # ------------------------------------------------------------------

    def _ouvrir(self) -> None:
        chemin, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Ouvrir un fichier audio", "", FORMATS
        )
        if chemin:
            self._ouvrir_chemin(chemin)

    def _ouvrir_chemin(self, chemin: str) -> None:
        try:
            audio = charger(chemin)
        except Exception as erreur:
            QtWidgets.QMessageBox.critical(self, "Lecture impossible", str(erreur))
            return
        self.lecture.definir_source(audio)
        self.barre_position.setEnabled(True)
        self.barre_position.setRange(0, max(1, int(self.lecture.duree * 1000)))
        self.action_export.setEnabled(True)
        self._etat.setText(
            f"{Path(chemin).name} — {self.lecture.duree:.1f} s, "
            f"{F_AUDIO / 1000:.0f} kHz mono"
        )
        self._basculer()

    def _basculer(self) -> None:
        if self.lecture.en_lecture():
            self.lecture.arreter()
            self.bouton_lecture.setText("▶")
        else:
            self.lecture.lire()
            self.bouton_lecture.setText("❚❚")

    def _sur_position(self, secondes: float) -> None:
        if not self.barre_position.isSliderDown():
            self.barre_position.setValue(int(secondes * 1000))
        self.etiquette_temps.setText(
            f"{int(secondes // 60)}:{int(secondes % 60):02d} / "
            f"{int(self.lecture.duree // 60)}:{int(self.lecture.duree % 60):02d}"
        )

    def _rafraichir_instruments(self) -> None:
        bloc = self.lecture.dernier_bloc
        if bloc is None or bloc.size < 64:
            return
        temps = np.arange(bloc.size) / F_AUDIO
        self.courbe_onde.setData(temps, np.clip(bloc, -1.2, 1.2))

        fenetre = np.hanning(bloc.size)
        spectre = np.abs(np.fft.rfft(bloc * fenetre)) / (bloc.size / 4)
        frequences = np.fft.rfftfreq(bloc.size, 1.0 / F_AUDIO)
        garde = frequences > 20.0
        self.courbe_spectre.setData(
            frequences[garde], 20.0 * np.log10(np.maximum(spectre[garde], 1e-6))
        )

    def _exporter(self) -> None:
        from .chaine import transmettre

        chemin, filtre = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter le son reçu", "radio.wav",
            "WAV (*.wav);;MP3 (*.mp3)",
        )
        if not chemin:
            return

        lisait = self.lecture.en_lecture()
        self.lecture.arreter()
        self.bouton_lecture.setText("▶")

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            sortie = transmettre(self.lecture.audio, self._parametres())
            crete = float(np.max(np.abs(sortie)))
            if crete > 1.0:
                sortie = sortie / crete
            if chemin.lower().endswith(".mp3") or "MP3" in filtre:
                if not chemin.lower().endswith(".mp3"):
                    chemin += ".mp3"
                ecrire_mp3(chemin, sortie)
            else:
                if not chemin.lower().endswith(".wav"):
                    chemin += ".wav"
                ecrire_wav(chemin, sortie)
        except Exception as erreur:
            QtWidgets.QMessageBox.critical(self, "Export impossible", str(erreur))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self._etat.setText(f"Exporté : {Path(chemin).name}")
        if lisait:
            self._basculer()

    # ------------------------------------------------------------------

    def dragEnterEvent(self, evenement):  # noqa: N802 - API Qt
        if evenement.mimeData().hasUrls():
            evenement.acceptProposedAction()

    def dropEvent(self, evenement):  # noqa: N802 - API Qt
        for url in evenement.mimeData().urls():
            chemin = url.toLocalFile()
            if chemin:
                self._ouvrir_chemin(chemin)
                break

    def closeEvent(self, evenement):  # noqa: N802 - API Qt
        self.lecture.arreter()
        super().closeEvent(evenement)


def principal(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    application = QtWidgets.QApplication(argv)
    application.setApplicationName("Radio")
    fenetre = FenetreRadio()
    fenetre.show()
    for argument in argv[1:]:
        if Path(argument).exists():
            fenetre._ouvrir_chemin(argument)
            break
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(principal())
