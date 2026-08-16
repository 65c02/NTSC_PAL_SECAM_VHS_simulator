"""
Fenêtre du lecteur : une vidéo, une norme, et tous les réglages sous la main.

L'idée directrice est la comparaison immédiate. Les touches 1, 2 et 3 basculent
entre NTSC, PAL et SECAM sans interrompre la lecture : c'est en passant de
l'une à l'autre sur la même image, à la même seconde, que les différences
sautent aux yeux — bien mieux qu'en lisant un tableau.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from gui.widgets_base import Curseur, Glissiere, Groupe, note
from tvcolor import mires
from tvcolor.constantes import NORMES

from .normes_gl import QUALITES
from .source_video import SourceVideo
from .vue_gl import ParametresRendu, VueTelevision

FORMATS = "Vidéos (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.mpg *.mpeg *.wmv *.flv)"

RACCOURCIS_NORMES = {
    QtCore.Qt.Key_1: "NTSC-M",
    QtCore.Qt.Key_2: "PAL-BG",
    QtCore.Qt.Key_3: "SECAM-L",
}


def _formater(secondes: float) -> str:
    secondes = max(0.0, secondes)
    return f"{int(secondes // 60)}:{int(secondes % 60):02d}"


class FenetreLecteur(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Téléviseur — lecture vidéo en NTSC, PAL ou SECAM")
        self.resize(1500, 940)
        self.setAcceptDrops(True)

        self.source = SourceVideo(self)
        self.source.image_prete.connect(self._sur_image)
        self.source.position_changee.connect(self._sur_position)
        self.source.erreur.connect(self._sur_erreur)

        self._silencieux = False
        self._position = 0.0
        self._tailles_separation: list[int] = []

        self._construire()
        self._charger_mire()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _construire(self) -> None:
        self.vue = VueTelevision()
        self.vue.fps_mesure.connect(self._sur_fps)

        self._barre_transport = self._construire_transport()
        self._panneau = self._construire_panneau()

        conteneur = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(conteneur)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(4)
        colonne.addWidget(self.vue, 1)
        colonne.addWidget(self._barre_transport)

        self._separation = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._separation.addWidget(conteneur)
        self._separation.addWidget(self._panneau)
        self._separation.setStretchFactor(0, 1)
        self._separation.setStretchFactor(1, 0)
        self._separation.setSizes([1150, 350])
        self.setCentralWidget(self._separation)

        self._construire_barre_outils()

        self._etat = QtWidgets.QLabel("Aucune vidéo — mire de barres de couleur")
        self._etat_fps = QtWidgets.QLabel("")
        self.statusBar().addWidget(self._etat, 1)
        self.statusBar().addPermanentWidget(self._etat_fps)

    def _construire_barre_outils(self) -> None:
        barre = self._barre_outils = self.addToolBar("Source")
        barre.setMovable(False)

        barre.addAction("Ouvrir une vidéo…", self._ouvrir).setShortcut("Ctrl+O")
        barre.addSeparator()

        barre.addWidget(QtWidgets.QLabel("  Norme  "))
        self.combo_norme = QtWidgets.QComboBox()
        for code, norme in NORMES.items():
            self.combo_norme.addItem(norme.nom, code)
        self.combo_norme.setCurrentIndex(self.combo_norme.findData("SECAM-L"))
        self.combo_norme.currentIndexChanged.connect(self._appliquer)
        barre.addWidget(self.combo_norme)

        barre.addWidget(QtWidgets.QLabel("   Qualité  "))
        self.combo_qualite = QtWidgets.QComboBox()
        for nom, taps in QUALITES.items():
            self.combo_qualite.addItem(f"{nom} ({taps} coefficients)", nom)
        self.combo_qualite.setCurrentIndex(1)
        self.combo_qualite.currentIndexChanged.connect(self._appliquer)
        barre.addWidget(self.combo_qualite)

        barre.addSeparator()
        barre.addWidget(QtWidgets.QLabel("   Mire  "))
        self.combo_mire = QtWidgets.QComboBox()
        self.combo_mire.addItem("— aucune —", None)
        for nom in mires.CATALOGUE:
            self.combo_mire.addItem(nom, nom)
        self.combo_mire.setCurrentIndex(1)
        self.combo_mire.currentIndexChanged.connect(self._charger_mire)
        barre.addWidget(self.combo_mire)

        barre.addSeparator()
        action = barre.addAction("Plein écran")
        action.setShortcut("F11")
        action.setToolTip("Plein écran, interface masquée (F11 ou Échap pour revenir)")
        action.triggered.connect(self._basculer_plein_ecran)

    def _construire_transport(self) -> QtWidgets.QWidget:
        self.bouton_lecture = QtWidgets.QToolButton()
        self.bouton_lecture.setText("▶")
        self.bouton_lecture.setFixedWidth(38)
        self.bouton_lecture.clicked.connect(self._basculer_lecture)

        self.barre_position = Glissiere(QtCore.Qt.Horizontal)
        self.barre_position.setEnabled(False)
        self.barre_position.sliderMoved.connect(self._chercher)
        self.barre_position.sliderReleased.connect(
            lambda: self._chercher(self.barre_position.value())
        )

        self.etiquette_temps = QtWidgets.QLabel("0:00 / 0:00")
        self.etiquette_temps.setStyleSheet("font-family: Consolas;")

        self.combo_vitesse = QtWidgets.QComboBox()
        for libelle, valeur in (("0,25×", 0.25), ("0,5×", 0.5), ("1×", 1.0),
                                ("2×", 2.0), ("4×", 4.0)):
            self.combo_vitesse.addItem(libelle, valeur)
        self.combo_vitesse.setCurrentIndex(2)
        self.combo_vitesse.currentIndexChanged.connect(
            lambda: self.source.definir_vitesse(self.combo_vitesse.currentData())
        )

        self.case_boucle = QtWidgets.QCheckBox("Boucler")
        self.case_boucle.setChecked(True)
        self.case_boucle.toggled.connect(self.source.definir_boucle)

        self.bouton_son = QtWidgets.QToolButton()
        self.bouton_son.setText("🔊")
        self.bouton_son.setCheckable(True)
        self.bouton_son.setFixedWidth(32)
        self.bouton_son.setToolTip("Couper le son")
        self.bouton_son.toggled.connect(self._basculer_son)

        self.barre_volume = Glissiere(QtCore.Qt.Horizontal)
        self.barre_volume.setRange(0, 100)
        self.barre_volume.setValue(80)
        self.barre_volume.setFixedWidth(90)
        self.barre_volume.setToolTip("Volume")
        self.barre_volume.valueChanged.connect(
            lambda v: self.source.definir_volume(v / 100.0)
        )

        ligne = QtWidgets.QHBoxLayout()
        ligne.setContentsMargins(6, 0, 6, 4)
        ligne.addWidget(self.bouton_lecture)
        ligne.addWidget(self.barre_position, 1)
        ligne.addWidget(self.etiquette_temps)
        ligne.addWidget(self.combo_vitesse)
        ligne.addWidget(self.bouton_son)
        ligne.addWidget(self.barre_volume)
        ligne.addWidget(self.case_boucle)

        widget = QtWidgets.QWidget()
        widget.setLayout(ligne)
        return widget

    def _construire_panneau(self) -> QtWidgets.QWidget:
        defilement = QtWidgets.QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        defilement.setMinimumWidth(330)

        contenu = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(contenu)
        colonne.setContentsMargins(8, 8, 8, 8)
        colonne.setSpacing(8)
        defilement.setWidget(contenu)

        # --- décodage ---
        groupe = Groupe("Décodage")
        self.combo_separateur = QtWidgets.QComboBox()
        self.combo_separateur.addItem("Filtre en peigne (1H en NTSC, 2H en PAL)", 0)
        self.combo_separateur.addItem("Réjecteur de sous-porteuse", 1)
        self.combo_separateur.currentIndexChanged.connect(self._appliquer)
        groupe.ajouter(QtWidgets.QLabel("Séparation luminance / chrominance"))
        groupe.ajouter(self.combo_separateur)

        self.case_ligne_retard = QtWidgets.QCheckBox("Ligne à retard (PAL-D)")
        self.case_ligne_retard.setChecked(True)
        self.case_ligne_retard.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_ligne_retard)
        groupe.ajouter(note(
            "Décochez pour retrouver le PAL-S des premiers récepteurs, et voir "
            "les barres de Hanover dès que la phase dérive."
        ))
        colonne.addWidget(groupe)

        # --- canal ---
        groupe = Groupe("Canal de transmission")
        self.case_bruit = QtWidgets.QCheckBox("Bruit")
        # Coché d'emblée : une réception parfaite n'a jamais existé, et le
        # grain fait partie de l'image autant que le fourmillement des points.
        # On coche AVANT de connecter — pendant la construction du panneau, la
        # barre d'outils n'existe pas encore et `_appliquer` échouerait.
        self.case_bruit.setChecked(True)
        self.case_bruit.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_bruit)

        self.curseur_bruit = Curseur("Rapport signal/bruit", 12.0, 60.0, 38.0, 1.0, "dB", 0)
        self.curseur_phase = Curseur("Phase différentielle", 0.0, 90.0, 0.0, 1.0, "°", 0)
        self.curseur_gain = Curseur("Gain différentiel", -1.0, 1.0, 0.0, 0.05, "", 2)
        for curseur in (self.curseur_bruit, self.curseur_phase, self.curseur_gain):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Poussez la phase différentielle et changez de norme avec les "
            "touches 1, 2 et 3 : le NTSC tourne, le PAL pâlit, le SECAM ignore."
        ))
        colonne.addWidget(groupe)

        # --- image ---
        groupe = Groupe("Image")
        self.curseur_chroma = Curseur("Amplitude de chrominance", 0.0, 2.0, 1.0, 0.05, "×", 2)
        self.curseur_saturation = Curseur("Saturation au décodage", 0.0, 2.0, 1.0, 0.05, "×", 2)
        for curseur in (self.curseur_chroma, self.curseur_saturation):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        colonne.addWidget(groupe)

        # --- restitution ---
        groupe = Groupe("Le tube")

        self.case_tube = QtWidgets.QCheckBox("Simuler la définition du tube")
        self.case_tube.setChecked(True)
        self.case_tube.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_tube)

        self.curseur_definition = Curseur(
            "Définition horizontale", 150.0, 900.0, 380.0, 10.0, "lignes", 0
        )
        self.curseur_definition.valeur_changee.connect(self._appliquer)
        groupe.ajouter(self.curseur_definition)
        groupe.ajouter(note(
            "Le spot du faisceau et l'amplificateur vidéo n'ont jamais restitué "
            "4,4 MHz à pleine amplitude. Un téléviseur d'appartement affichait "
            "300 à 400 lignes : il rendait la sous-porteuse à moins du quart. "
            "Décochez pour obtenir un écran parfait — qui montre le résidu bien "
            "plus nettement qu'aucun tube ne l'a jamais fait."
        ))

        # Pas de 0,01 et non 0,02 : le curseur est entier sous le capot, et
        # avec un pas de deux centièmes la valeur par défaut de 0,15 n'était
        # tout simplement pas atteignable — elle se serait posée sur 0,16.
        self.curseur_courbure = Curseur("Courbure de la dalle", 0.0, 1.0, 0.15, 0.01, "", 2)
        self.curseur_coins = Curseur("Arrondi des coins", 0.0, 1.0, 0.0, 0.05, "", 2)
        for curseur in (self.curseur_courbure, self.curseur_coins):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "La dalle est une calotte sphérique, sur laquelle le balayage peint "
            "l'image à longueur d'arc constante. Le rayon va de 1,6 demi-diagonale "
            "à fond — un poste des années 60 — à 4 vers 0,40, typique des années "
            "80. Ce n'est pas une distorsion en barillet réglée au jugé : c'est "
            "l'intersection d'un rayon avec la sphère."
        ))

        self.curseur_halo = Curseur("Halo (dalle de verre)", 0.0, 1.0, 0.06, 0.02, "×", 2)
        self.curseur_halo_seuil = Curseur("Seuil du halo", 0.0, 0.95, 0.55, 0.05, "", 2)
        self.curseur_halo_rayon = Curseur("Rayon du halo", 0.005, 0.10, 0.025, 0.005, "", 3)
        for curseur in (self.curseur_halo, self.curseur_halo_seuil,
                        self.curseur_halo_rayon):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "La dalle de verre diffuse une part de la lumière du luminophore, "
            "et le spot s'épanouit quand le courant de faisceau monte. Seuil à "
            "zéro : tout diffuse, comme la halation. Seuil relevé : seules les "
            "hautes lumières bavent, comme un faisceau saturé."
        ))

        self.combo_echantillonnage = QtWidgets.QComboBox()
        for libelle, code in (
            ("normatif — 4 points par cycle", "normatif"),
            ("double — 8 points par cycle", "double"),
            ("triple — 12 points par cycle", "triple"),
            ("résolution de l'écran", "ecran"),
        ):
            self.combo_echantillonnage.addItem(libelle, code)
        self.combo_echantillonnage.setCurrentIndex(0)
        self.combo_echantillonnage.currentIndexChanged.connect(self._appliquer)
        groupe.ajouter(QtWidgets.QLabel("Grille de calcul du signal"))
        groupe.ajouter(self.combo_echantillonnage)
        groupe.ajouter(note(
            "Quatre points par cycle suffisent à représenter la sous-porteuse, "
            "mais le résidu prend alors la forme d'un escalier. Au-delà, il "
            "redevient la sinusoïde qu'il est. Le nombre de lignes, lui, reste "
            "normatif — 576 lignes, ce sont de vraies lignes."
        ))
        colonne.addWidget(groupe)

        # --- tube ---
        groupe = Groupe("Aspect")
        self.curseur_lignes = Curseur("Lignes de balayage", 0.0, 1.0, 0.0, 0.05, "", 2)
        self.curseur_masque = Curseur("Masque du tube", 0.0, 1.0, 0.0, 0.05, "", 2)
        self.curseur_luminosite = Curseur("Luminosité", 0.5, 2.5, 1.0, 0.05, "×", 2)
        for curseur in (self.curseur_lignes, self.curseur_masque, self.curseur_luminosite):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)

        self.case_animer = QtWidgets.QCheckBox("Faire ramper les points")
        self.case_animer.setChecked(True)
        self.case_animer.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_animer)

        self.case_proportions = QtWidgets.QCheckBox("Conserver les proportions")
        self.case_proportions.setChecked(True)
        self.case_proportions.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_proportions)
        colonne.addWidget(groupe)

        self.etiquette_norme = note("")
        colonne.addWidget(self.etiquette_norme)
        colonne.addStretch(1)
        return defilement

    # ------------------------------------------------------------------
    # Réglages
    # ------------------------------------------------------------------

    def _parametres(self) -> ParametresRendu:
        return ParametresRendu(
            norme=self.combo_norme.currentData(),
            qualite=self.combo_qualite.currentData(),
            separateur=self.combo_separateur.currentData(),
            ligne_retard=self.case_ligne_retard.isChecked(),
            amplitude_chroma=self.curseur_chroma.valeur(),
            saturation=self.curseur_saturation.valeur(),
            phase_differentielle=self.curseur_phase.valeur(),
            gain_differentiel=self.curseur_gain.valeur(),
            rapport_signal_bruit=(
                self.curseur_bruit.valeur() if self.case_bruit.isChecked() else None
            ),
            lignes_balayage=self.curseur_lignes.valeur(),
            masque_tube=self.curseur_masque.valeur(),
            luminosite=self.curseur_luminosite.valeur(),
            definition_tube=(
                self.curseur_definition.valeur() if self.case_tube.isChecked() else 0.0
            ),
            echantillonnage=self.combo_echantillonnage.currentData(),
            courbure=self.curseur_courbure.valeur(),
            arrondi_coins=self.curseur_coins.valeur(),
            halo_intensite=self.curseur_halo.valeur(),
            halo_seuil=self.curseur_halo_seuil.valeur(),
            halo_rayon=self.curseur_halo_rayon.valeur(),
            animer=self.case_animer.isChecked(),
            conserver_proportions=self.case_proportions.isChecked(),
        )

    def _appliquer(self, *_args) -> None:
        if self._silencieux:
            return
        parametres = self._parametres()
        famille = NORMES[parametres.norme].famille
        self.case_ligne_retard.setEnabled(famille == "PAL")
        self.combo_separateur.setEnabled(famille != "SECAM")
        self.vue.appliquer(parametres)
        self.etiquette_norme.setText(self.vue.description())

    # ------------------------------------------------------------------
    # Source
    # ------------------------------------------------------------------

    def _charger_mire(self, *_args) -> None:
        nom = self.combo_mire.currentData()
        if nom is None:
            return
        self.source.pause()
        self._maj_bouton()
        image = mires.obtenir_mire(nom, 576, 768)
        self.vue.definir_image((np.clip(image, 0, 1) * 255).astype(np.uint8))
        self._etat.setText(f"Mire : {nom}")
        self._appliquer()

    def _ouvrir(self) -> None:
        chemin, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Ouvrir une vidéo", "", FORMATS + ";;Tous les fichiers (*)"
        )
        if chemin:
            self._ouvrir_chemin(chemin)

    def _ouvrir_chemin(self, chemin: str) -> None:
        try:
            infos = self.source.ouvrir(chemin)
        except Exception as erreur:
            QtWidgets.QMessageBox.critical(self, "Lecture impossible", str(erreur))
            return

        self._silencieux = True
        self.combo_mire.setCurrentIndex(0)
        self._silencieux = False

        # La barre est graduée en millisecondes : la seconde entière serait un
        # cran trop gros pour se placer précisément dans un plan.
        self.barre_position.setEnabled(infos.duree > 0)
        self.barre_position.setRange(0, max(1, int(infos.duree * 1000)))
        self.source.definir_vitesse(self.combo_vitesse.currentData())
        self.source.definir_boucle(self.case_boucle.isChecked())
        self.source.definir_volume(self.barre_volume.value() / 100.0)
        self.source.definir_muet(self.bouton_son.isChecked())
        self.barre_volume.setEnabled(infos.a_du_son)
        self.bouton_son.setEnabled(infos.a_du_son)
        self.source.avancer_d_une_image()
        self.source.lire()
        self._maj_bouton()
        self._etat.setText(infos.resume())

    def _basculer_lecture(self) -> None:
        if self.source.infos is None:
            return
        self.source.basculer()
        self._maj_bouton()

    def _maj_bouton(self) -> None:
        self.bouton_lecture.setText("❚❚" if self.source.en_lecture else "▶")

    def _chercher(self, millisecondes: int) -> None:
        if self.source.infos is not None:
            self.source.chercher(millisecondes / 1000.0)

    def _basculer_son(self, coupe: bool) -> None:
        self.source.definir_muet(coupe)
        self.bouton_son.setText("🔇" if coupe else "🔊")

    # ------------------------------------------------------------------
    # Réactions
    # ------------------------------------------------------------------

    @QtCore.pyqtSlot(object)
    def _sur_image(self, image: np.ndarray) -> None:
        self.vue.definir_image(image)

    @QtCore.pyqtSlot(float)
    def _sur_position(self, secondes: float) -> None:
        self._position = secondes
        infos = self.source.infos
        if infos is None:
            return
        if not self.barre_position.isSliderDown():
            self.barre_position.blockSignals(True)
            self.barre_position.setValue(int(secondes * 1000))
            self.barre_position.blockSignals(False)
        self.etiquette_temps.setText(
            f"{_formater(secondes)} / {_formater(infos.duree)}"
        )

    @QtCore.pyqtSlot(str)
    def _sur_erreur(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Erreur de lecture", message)

    @QtCore.pyqtSlot(float)
    def _sur_fps(self, fps: float) -> None:
        self._etat_fps.setText(f"rendu : {fps:.0f} images/s")

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def keyPressEvent(self, evenement):  # noqa: N802 - API Qt
        touche = evenement.key()
        if touche == QtCore.Qt.Key_Space:
            self._basculer_lecture()
        elif touche in RACCOURCIS_NORMES:
            rang = self.combo_norme.findData(RACCOURCIS_NORMES[touche])
            if rang >= 0:
                self.combo_norme.setCurrentIndex(rang)
        elif touche == QtCore.Qt.Key_Escape and self.isFullScreen():
            self._basculer_plein_ecran()
        elif touche == QtCore.Qt.Key_F11:
            # Le raccourci porté par l'action de la barre d'outils cesse d'agir
            # dès que celle-ci est masquée : en plein écran, il n'y a donc que
            # cette voie-ci pour revenir.
            self._basculer_plein_ecran()
        elif touche in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right):
            if self.source.infos is not None:
                delta = -5.0 if touche == QtCore.Qt.Key_Left else 5.0
                self.source.chercher(max(0.0, self._position + delta))
        elif touche == QtCore.Qt.Key_M:
            self.bouton_son.toggle()
        else:
            super().keyPressEvent(evenement)

    def _basculer_plein_ecran(self) -> None:
        """Plein écran, et l'interface avec lui.

        Le but de l'outil est de regarder une image ; en plein écran on ne
        garde donc que la dalle. Barre d'outils, panneau de réglages, transport
        et barre d'état disparaissent — l'écran n'affiche plus que le tube, sur
        fond noir.

        On mémorise le partage du séparateur avant de replier le panneau :
        masquer un volet de QSplitter met sa largeur à zéro, et sans cela il
        reviendrait écrasé.
        """
        if self.isFullScreen():
            self.showNormal()
            self._montrer_interface(True)
        else:
            self._tailles_separation = self._separation.sizes()
            self._montrer_interface(False)
            self.showFullScreen()

    def _montrer_interface(self, visible: bool) -> None:
        self._barre_outils.setVisible(visible)
        self._panneau.setVisible(visible)
        self._barre_transport.setVisible(visible)
        self.statusBar().setVisible(visible)
        if visible and self._tailles_separation:
            self._separation.setSizes(self._tailles_separation)

    def dragEnterEvent(self, evenement):  # noqa: N802 - API Qt
        if evenement.mimeData().hasUrls():
            evenement.acceptProposedAction()

    def dropEvent(self, evenement):  # noqa: N802 - API Qt
        for url in evenement.mimeData().urls():
            chemin = url.toLocalFile()
            if chemin and Path(chemin).is_file():
                self._ouvrir_chemin(chemin)
                break

    def resizeEvent(self, evenement):  # noqa: N802 - API Qt
        # La finesse d'affichage — combien de pixels d'écran par ligne de
        # balayage — figure dans la description, et elle ne dépend que de la
        # taille de la fenêtre. Sans ce rappel, elle resterait figée sur la
        # valeur du dernier changement de réglage.
        super().resizeEvent(evenement)
        self.etiquette_norme.setText(self.vue.description())

    def closeEvent(self, evenement):  # noqa: N802 - API Qt
        self.source.fermer()
        super().closeEvent(evenement)


def lancer(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # Le format doit être choisi AVANT la création de QApplication : après, le
    # contexte partagé est déjà créé et l'appel n'a plus aucun effet.
    format_gl = QtGui.QSurfaceFormat()
    format_gl.setVersion(3, 3)
    format_gl.setProfile(QtGui.QSurfaceFormat.CoreProfile)
    format_gl.setDepthBufferSize(0)
    format_gl.setStencilBufferSize(0)
    format_gl.setSwapInterval(1)
    QtGui.QSurfaceFormat.setDefaultFormat(format_gl)

    application = QtWidgets.QApplication(argv)
    application.setApplicationName("Téléviseur NTSC/PAL/SECAM")

    fenetre = FenetreLecteur()
    fenetre.show()

    for argument in argv[1:]:
        if Path(argument).is_file():
            fenetre._ouvrir_chemin(argument)
            break

    return application.exec_()


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(lancer())
