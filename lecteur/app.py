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
from tvcolor.tube import CAMERA_PAR_DEFAUT, CAMERAS, obtenir_camera

from tvcolor.son import (
    ParametresSon,
    gain_de_demodulation_db,
    rapport_porteuse_bruit,
)

from .export_video import ExportateurMP4, ReglagesExport, dimensions
from .normes_gl import QUALITES
from .source_video import SourceVideo, format_tv, ramener_au_format_tv
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
        # Cadence de la source, que la caméra à tubes réclame : une cible se
        # décharge une fois par TRAME, pas une fois par image reçue.
        self._cadence_source = 0.0
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
        self.combo_qualite.setCurrentIndex(self.combo_qualite.findData("haute"))
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
        self.action_export = barre.addAction("Exporter en MP4…", self._exporter)
        self.action_export.setShortcut("Ctrl+E")
        self.action_export.setToolTip(
            "Enregistre la vidéo telle que le téléviseur la montre, son compris"
        )
        self.action_export.setEnabled(False)

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
        # Jusqu'à 200 % : au-delà de la position normale, c'est déjà une
        # amplification, et la source la réclame souvent.
        self.barre_volume.setRange(0, 200)
        self.barre_volume.setValue(80)
        self.barre_volume.setFixedWidth(90)
        self.barre_volume.setToolTip(
            "Volume — au-delà de 100 %, amplification.\n"
            "Pour davantage, voir « gain de sortie » dans l'onglet Son."
        )
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
        """Les réglages, en deux onglets.

        L'image et le son partagent la norme et le canal, mais rien d'autre :
        les séparer évite un panneau interminable où l'on cherche son réglage.
        Le rapport signal/bruit reste du côté image, et c'est voulu — il n'y a
        qu'un canal, et c'est lui qui décide du sort des deux.
        """
        self.onglets = QtWidgets.QTabWidget()
        self.onglets.addTab(self._onglet_image(), "Image")
        self.onglets.addTab(self._onglet_camera(), "Caméra")
        self.onglets.addTab(self._onglet_bruit(), "Bruit")
        self.onglets.addTab(self._onglet_magnetoscope(), "Magnétoscope")
        self.onglets.addTab(self._onglet_son(), "Son")
        return self.onglets

    @staticmethod
    def _page() -> tuple[QtWidgets.QScrollArea, QtWidgets.QVBoxLayout]:
        defilement = QtWidgets.QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        defilement.setMinimumWidth(330)
        contenu = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(contenu)
        colonne.setContentsMargins(8, 8, 8, 8)
        colonne.setSpacing(8)
        defilement.setWidget(contenu)
        return defilement, colonne

    def _onglet_image(self) -> QtWidgets.QWidget:
        defilement, colonne = self._page()

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
        self.curseur_courbure = Curseur("Courbure de la dalle", 0.0, 1.0, 0.30, 0.01, "", 2)
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

        self.curseur_halo = Curseur("Halo (dalle de verre)", 0.0, 1.0, 0.10, 0.02, "×", 2)
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

        self.case_comparaison = QtWidgets.QCheckBox(
            "Comparer au survol : à gauche la vidéo, à droite le téléviseur"
        )
        self.case_comparaison.setToolTip(
            "Passez la souris sur l'image : le volet suit le pointeur.\n"
            "Touche C pour l'allumer ou l'éteindre."
        )
        self.case_comparaison.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_comparaison)

        groupe.ajouter(note(
            "Les deux moitiés sont prises à la même coordonnée d'image, "
            "courbure de la dalle comprise : un point de la scène tombe au "
            "même endroit des deux côtés du volet, et l'on ne compare donc "
            "que le signal.\n\n"
            "À gauche, la vidéo telle qu'elle est entrée dans la chaîne — ni "
            "codage, ni canal, ni caméra, ni réponse du tube. Le réglage de "
            "luminosité ne s'y applique pas non plus : il est là pour rendre "
            "la lumière que les lignes de balayage et le masque ont prise, et "
            "de ce côté-ci il n'y a rien à rendre."
        ))

        self.case_format_tv = QtWidgets.QCheckBox("Ramener la vidéo au format d'un téléviseur")
        self.case_format_tv.setChecked(True)
        self.case_format_tv.setToolTip(
            "Rééchantillonne chaque image à la trame active de la norme —\n"
            "768 × 576 en 625 lignes, 640 × 480 en 525 — avant tout le reste."
        )
        self.case_format_tv.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_format_tv)

        self.etiquette_format_tv = note("")
        groupe.ajouter(self.etiquette_format_tv)
        colonne.addWidget(groupe)

        self.etiquette_norme = note("")
        colonne.addWidget(self.etiquette_norme)
        colonne.addStretch(1)
        return defilement

    # ------------------------------------------------------------------

    def _onglet_bruit(self) -> QtWidgets.QWidget:
        """Le canal — et il en faut UN, pas deux.

        Le bruit avait sa place dans l'onglet Image tant que l'image était
        seule à en souffrir. Depuis que la voie son existe, ce n'est plus vrai :
        il y a un canal, une densité de bruit, et deux porteuses qui y puisent.
        Le laisser du côté de l'image laissait croire qu'il lui appartenait.
        """
        defilement, colonne = self._page()

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

        groupe = Groupe("Ce que le son en récolte")
        self.etiquette_cn = note("")
        groupe.ajouter(self.etiquette_cn)
        groupe.ajouter(note(
            "Une seule densité de bruit, deux porteuses. Ce que la voie son en "
            "récolte se déduit de sa largeur de bande — cent trente kilohertz "
            "contre cinq mégahertz, seize décibels de gagnés — et de sa "
            "puissance d'émission, dix à treize décibels plus bas.\n\n"
            "Poussez le bruit et écoutez : en FM le son reste net bien après que "
            "l'image a commencé à neiger. En SECAM-L, dont le son est modulé en "
            "amplitude, les deux se dégradent ensemble."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    # ------------------------------------------------------------------

    def _onglet_camera(self) -> QtWidgets.QWidget:
        """La caméra à tubes — le tout premier maillon, avant même le codeur."""
        defilement, colonne = self._page()

        groupe = Groupe("Caméra")
        self.case_tube_camera = QtWidgets.QCheckBox("Filmer avec une caméra à tubes")
        self.case_tube_camera.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_tube_camera)

        self.combo_camera = QtWidgets.QComboBox()
        self.combo_camera.addItem("Réglage libre", None)
        for camera in CAMERAS.values():
            self.combo_camera.addItem(f"{camera.annee} — {camera.nom}", camera.code)
        self.combo_camera.setCurrentIndex(
            self.combo_camera.findData(CAMERA_PAR_DEFAUT)
        )
        self.combo_camera.currentIndexChanged.connect(self._sur_modele_camera)
        groupe.ajouter(QtWidgets.QLabel("Modèle"))
        groupe.ajouter(self.combo_camera)

        self.etiquette_camera = note("")
        groupe.ajouter(self.etiquette_camera)
        colonne.addWidget(groupe)

        # Les valeurs de départ viennent de la table des caméras, et non de
        # constantes recopiées ici : le menu afficherait sinon un modèle dont
        # les curseurs ne diraient pas tout à fait la même chose.
        depart = obtenir_camera(CAMERA_PAR_DEFAUT)

        groupe = Groupe("Le matériel")
        self.curseur_faisceau = Curseur(
            "Courant du faisceau", 1.0, 4.0, depart.faisceau, 0.05, " × blanc", 2
        )
        self.curseur_anti_comete = Curseur(
            "Circuit anti-comète", 0.0, 1.0, depart.anti_comete, 0.05, "", 2)
        self.curseur_remanence = Curseur(
            "Rémanence du tube", 0.0, 0.9, depart.remanence, 0.05, "", 2)
        self.curseur_genou = Curseur(
            "Genou de rémanence", 0.02, 1.20, depart.genou_remanence, 0.01, "", 2)
        self.curseur_charge_max = Curseur(
            "Capacité de la cible", 2.0, 40.0, depart.charge_maximale, 0.5,
            " × blanc", 1)
        self.curseur_biais = Curseur(
            "Lumière de biais", 0.0, 0.15, depart.lumiere_de_biais, 0.01, "", 2)
        self.curseur_desalignement = Curseur(
            "Désalignement des tubes", 0.0, 6.0, depart.desalignement, 0.1, " px", 1
        )
        self.curseur_masquage = Curseur(
            "Matrice de masquage", 0.0, 1.0, depart.masquage, 0.05, "", 2)
        self._curseurs_camera = (
            self.curseur_faisceau, self.curseur_anti_comete, self.curseur_remanence,
            self.curseur_genou, self.curseur_charge_max, self.curseur_biais,
            self.curseur_desalignement, self.curseur_masquage,
        )
        for curseur in self._curseurs_camera:
            curseur.valeur_changee.connect(self._sur_curseur_camera)
            groupe.ajouter(curseur)

        self.etiquette_tube = note("")
        groupe.ajouter(self.etiquette_tube)
        colonne.addWidget(groupe)

        groupe = Groupe("Le pont temporel")
        self.curseur_pont = Curseur(
            "Portée du pont", 0.0, 64.0, 0.0, 2.0, " px", 0
        )
        self.curseur_pont.valeur_changee.connect(self._appliquer)
        groupe.ajouter(self.curseur_pont)
        groupe.ajouter(note(
            "Celui-ci ne décrit pas la caméra — c'est pour cela que le menu des "
            "modèles n'y touche pas.\n\n"
            "La cible intègre en CONTINU pendant toute la trame ; une vidéo n'a "
            "que vingt-cinq images par seconde. Ce qui s'est passé entre deux "
            "images n'est pas dans le fichier, et la charge se dépose donc par "
            "paquets espacés : la traînée sort en chapelet de reflets distincts "
            "au lieu d'être continue. Mesuré sur un reflet de trois pixels "
            "avançant de douze par image : 22 % de la traînée allumée, le reste "
            "étant du trou.\n\n"
            "Le pont constate qu'un point se trouve ENTRE un reflet présent et "
            "une trace passée, et remplit le segment — ce qui ramène la traînée "
            "à 90 ou 100 % selon la vitesse.\n\n"
            "IL EST NUL PAR DÉFAUT, et c'est un choix. C'est une interpolation "
            "et non un phénomène, et sur une image chargée elle diverge du "
            "simulateur de référence : 41 % de blanc saturé contre 29 % sur une "
            "scène chaude en mouvement. On ne l'allume donc que pour ce à quoi "
            "il sert — un reflet vif et rapide qui sortirait en chapelet."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("La scène (ce que la caméra regarde)")
        self.curseur_eclat = Curseur("Éclat des reflets", 0.0, 100.0, 25.0, 1.0, " × blanc", 0)
        self.curseur_seuil_reflets = Curseur("Seuil des reflets", 0.4, 1.0, 0.75, 0.01, "", 2)
        for curseur in (self.curseur_eclat, self.curseur_seuil_reflets):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Ces deux-là ne décrivent pas la caméra mais le PLATEAU qu'elle "
            "filme, et le menu des modèles n'y touche donc pas : deux caméras "
            "différentes braquées sur les mêmes cymbales y voient les mêmes "
            "reflets.\n\n"
            "Ils existent parce qu'un fichier huit bits a déjà été écrêté par "
            "celui qui l'a fabriqué : aucun pixel n'y dépasse le blanc, et sans "
            "rien faire la cible ne serait jamais en surcharge. Il faut donc "
            "rendre aux reflets l'éclairement qu'ils avaient — vingt-cinq fois "
            "le blanc est modeste pour du chrome sous un projecteur."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("La queue de comète")
        groupe.ajouter(note(
            "Une caméra à tubes ne mesure pas la lumière : elle mesure la CHARGE "
            "que la lumière a soutirée à une cible photoconductrice, et c'est le "
            "courant qu'il faut au faisceau pour la remettre à niveau qui fait le "
            "signal vidéo.\n\n"
            "Or le faisceau a un débit maximal, réglé pour évacuer 130 % du blanc. "
            "Un reflet sur du chrome sous un projecteur ne fait pas 130 % du blanc, "
            "il en fait vingt-cinq fois. Le faisceau en évacue une tranche fixe par "
            "trame, et il lui faut vingt trames pour en venir à bout — pendant "
            "lesquelles le reflet s'est déplacé. La charge restée en arrière se lit "
            "tout ce temps AU MAXIMUM que le faisceau sait fournir, donc au blanc "
            "écrêté : d'où une traînée d'un blanc plat, derrière laquelle l'image "
            "disparaît, et qui s'arrête net.\n\n"
            "Philips a livré le circuit anti-comète en 1976 : pendant la "
            "suppression ligne, le faisceau est défocalisé et son courant "
            "fortement augmenté, le temps de vider l'excès. C'est pour cela que "
            "les traînées ont disparu des émissions à la fin de la décennie sans "
            "que personne n'ait changé de tube — passer du modèle de 1970 à celui "
            "de 1977 fait exactement cela."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("Les deux autres défauts")
        groupe.ajouter(note(
            "La RÉMANENCE est l'autre visage du même mécanisme : le faisceau ne "
            "décharge jamais tout à fait, et il en reste une fraction. Elle est "
            "bien pire dans les bas niveaux — un petit écart de potentiel se "
            "résorbe lentement — d'où les traînées molles sur les images sombres. "
            "La lumière de biais éclairait la cible en permanence de quelques pour "
            "cent pour la remonter hors de cette zone paresseuse. Le GENOU dit à "
            "quelle échelle de charge le faisceau commence à peiner : c'est lui, "
            "bien plus que la rémanence elle-même, qui sépare un vidicon d'un "
            "Plumbicon.\n\n"
            "Le DÉSALIGNEMENT est plus prosaïque : trois tubes, trois déviations, "
            "et un réglage qui dérivait avec la température. Nul au centre, "
            "croissant vers les bords, il borde les contours de liserés colorés."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("La colorimétrie de la caméra")
        groupe.ajouter(note(
            "Les courbes d'analyse idéales d'une caméra sont les fonctions "
            "colorimétriques des primaires de restitution — et celles-ci ont des "
            "LOBES NÉGATIFS. Aucun filtre ne sait soustraire de la lumière : on "
            "ne fabrique que des courbes tout-positives, qui les approchent. "
            "Chaque voie récolte donc une part de ses voisines, et l'image sort "
            "désaturée.\n\n"
            "D'où la MATRICE DE MASQUAGE, dans l'électronique de la caméra, aux "
            "coefficients hors diagonale négatifs : elle refabrique par "
            "soustraction électronique les lobes que l'optique ne pouvait pas "
            "faire. À 1 elle est l'inverse exacte de l'erreur et la caméra est "
            "juste ; à 0 il n'y en a pas du tout.\n\n"
            "Mesuré sur les barres de couleur : ΔE*ab moyen de 16,9 sans "
            "masquage contre 2,5 avec, et 37 % de saturation en moins. C'est le "
            "réglage de la table qui a le plus progressé entre 1966 et 1987 — "
            "bien plus que la rémanence."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    def _sur_modele_camera(self, *_args) -> None:
        """Pose les six réglages du matériel choisi, en un seul rendu.

        L'entrée « Réglage libre » ne touche à rien : elle est l'état dans lequel
        bascule le menu dès qu'on déplace un curseur, et la sélectionner
        soi-même ne doit donc rien changer.
        """
        if self._silencieux:
            return
        code = self.combo_camera.currentData()
        if code is None:
            return

        camera = obtenir_camera(code)
        self._silencieux = True
        try:
            self.curseur_faisceau.definir(camera.faisceau)
            self.curseur_anti_comete.definir(camera.anti_comete)
            self.curseur_remanence.definir(camera.remanence)
            self.curseur_genou.definir(camera.genou_remanence)
            self.curseur_charge_max.definir(camera.charge_maximale)
            self.curseur_biais.definir(camera.lumiere_de_biais)
            self.curseur_desalignement.definir(camera.desalignement)
            self.curseur_masquage.definir(camera.masquage)
        finally:
            self._silencieux = False
        self._appliquer()

    def _sur_curseur_camera(self, *_args) -> None:
        """Un curseur bougé : on n'est plus sur un modèle d'origine."""
        if self._silencieux:
            return
        if self.combo_camera.currentData() is not None:
            self._silencieux = True
            try:
                self.combo_camera.setCurrentIndex(0)
            finally:
                self._silencieux = False
        self._appliquer()

    # ------------------------------------------------------------------

    def _onglet_magnetoscope(self) -> QtWidgets.QWidget:
        """Le magnétoscope, entre le canal et le téléviseur — sa vraie place."""
        defilement, colonne = self._page()

        groupe = Groupe("Cassette VHS")
        self.case_vhs = QtWidgets.QCheckBox("Passer par une cassette")
        self.case_vhs.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_vhs)

        self.combo_vitesse_vhs = QtWidgets.QComboBox()
        for code, libelle in (
            ("SP", "SP — 3 heures, la meilleure définition"),
            ("LP", "LP — 6 heures"),
            ("EP", "EP — 9 heures, la plus mauvaise"),
        ):
            self.combo_vitesse_vhs.addItem(libelle, code)
        self.combo_vitesse_vhs.currentIndexChanged.connect(self._appliquer)
        groupe.ajouter(QtWidgets.QLabel("Vitesse de défilement"))
        groupe.ajouter(self.combo_vitesse_vhs)

        self.curseur_generation = Curseur("Génération de copie", 1.0, 4.0, 1.0, 1.0, "", 0)
        self.curseur_usure = Curseur("Usure de la bande", 0.0, 1.0, 0.15, 0.05, "", 2)
        self.curseur_gigue = Curseur("Gigue de défilement", 0.0, 1.0, 0.35, 0.05, "", 2)
        self.curseur_abandons = Curseur("Pertes de signal", 0.0, 1.0, 0.25, 0.05, "", 2)
        self.curseur_liseré = Curseur("Liseré de contour", 0.0, 2.0, 0.8, 0.05, "", 2)
        for curseur in (self.curseur_generation, self.curseur_usure,
                        self.curseur_gigue, self.curseur_abandons,
                        self.curseur_liseré):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)

        self.case_commutation = QtWidgets.QCheckBox(
            "Commutation des têtes (bas de l'image)"
        )
        self.case_commutation.setChecked(True)
        self.case_commutation.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_commutation)

        self.etiquette_vhs = note("")
        groupe.ajouter(self.etiquette_vhs)
        colonne.addWidget(groupe)

        groupe = Groupe("Ce que la cassette fait")
        groupe.ajouter(note(
            "Un magnétoscope n'enregistre pas le composite tel quel : il le "
            "DÉMONTE. La bande ne tient pas cinq mégahertz, et le contact "
            "tête/bande fluctue trop pour qu'un enregistrement en amplitude soit "
            "envisageable. D'où le procédé color-under — séparer, moduler la "
            "luminance en fréquence, et transposer la chrominance SOUS elle, à "
            "627 kHz.\n\n"
            "Le prix tient dans un chiffre : la couleur ne dispose plus que de "
            "400 kHz contre 1,3 MHz, et sa définition horizontale tombe à une "
            "trentaine de lignes quand la luminance en garde 240. C'est ce qui "
            "trahit une cassette même quand tout le reste est propre.\n\n"
            "La gigue ne fait PAS tourner la teinte : la porteuse de relecture "
            "est régénérée à partir du signal lu, et l'erreur de base de temps "
            "s'annule dans la démodulation. C'est même toute la raison d'être du "
            "color-under."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    # ------------------------------------------------------------------

    def _onglet_son(self) -> QtWidgets.QWidget:
        """La voie son : sa porteuse, et ce que le canal lui fait.

        Le son d'un téléviseur ne voyage pas dans le signal vidéo. Il occupe sa
        propre porteuse, quelques mégahertz plus haut dans le même canal, et
        c'est le même bruit qui frappe les deux. D'où l'unique réglage de bruit,
        resté du côté image : il n'y a qu'un canal.
        """
        defilement, colonne = self._page()

        groupe = Groupe("La porteuse son")
        self.case_son_tv = QtWidgets.QCheckBox("Faire passer le son par la porteuse")
        self.case_son_tv.setChecked(True)
        self.case_son_tv.toggled.connect(self._appliquer)
        groupe.ajouter(self.case_son_tv)
        groupe.ajouter(note(
            "Décochez pour entendre le fichier tel quel, et comparer. Le son "
            "restitué est monophonique : c'est ce que la porteuse transportait. "
            "Le NICAM et le Zweiton, qui ont apporté la stéréo, sont venus plus "
            "tard et sur d'autres porteuses encore."
        ))

        self.etiquette_porteuse = note("")
        groupe.ajouter(self.etiquette_porteuse)
        colonne.addWidget(groupe)

        groupe = Groupe("Défauts du récepteur")
        self.curseur_intercarrier = Curseur(
            "Ronflement intercarrier", 0.0, 1.0, 0.0, 0.05, "", 2
        )
        self.curseur_desaccord = Curseur(
            "Désaccord de l'oscillateur", -20e3, 20e3, 0.0, 500.0, "Hz", 0
        )
        self.curseur_gain_son = Curseur(
            "Niveau d'entrée du modulateur", -12.0, 30.0, 0.0, 1.0, "dB", 0
        )
        self.curseur_gain_sortie = Curseur(
            "Gain de sortie du poste", -12.0, 24.0, 0.0, 1.0, "dB", 0
        )
        for curseur in (self.curseur_intercarrier, self.curseur_desaccord,
                        self.curseur_gain_son, self.curseur_gain_sortie):
            curseur.valeur_changee.connect(self._appliquer)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Un récepteur à intercarrier tire le son du BATTEMENT entre porteuse "
            "image et porteuse son. Le procédé est d'une stabilité remarquable — "
            "la dérive de l'oscillateur s'annule dans la soustraction — mais toute "
            "modulation parasite de la porteuse image se retrouve dans le "
            "haut-parleur. D'où le ronflement de trame et le sifflement de ligne, "
            "qui montent avec la luminosité de l'image.\n\n"
            "Le NIVEAU D'ENTRÉE du modulateur est le réglage du studio, et ce "
            "n'est pas un bouton de volume : placé AVANT la modulation, il "
            "décide de l'excursion réellement employée, donc du rapport "
            "signal/bruit. Un décibel de gain ici en rend un — mesuré sur une "
            "source gravée bas dans un canal à 25 dB : 33 dB de signal/bruit "
            "sans gain, 45 avec douze décibels, 51 avec dix-huit.\n\n"
            "Servez-vous-en quand la source est faible : sous-moduler la "
            "porteuse, c'est gaspiller l'excursion que la norme accorde. "
            "Au-delà du point où l'excursion est pleine, le limiteur de "
            "l'émetteur écrête et la distorsion apparaît.\n\n"
            "Le gain de SORTIE, lui, est le bouton de volume du poste : il agit "
            "après la démodulation, amplifie donc le bruit autant que le signal, "
            "et ne rattrape aucune mauvaise réception. Il sert quand le fichier "
            "est gravé bas — ou simplement parce que la porteuse ne transportait "
            "qu'une voie, et que ramener une source stéréo en mono coûte jusqu'à "
            "trois décibels. Au-delà de la butée, l'étage de sortie sature en "
            "douceur au lieu d'écrêter carré."
        ))
        colonne.addWidget(groupe)

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
            vhs_actif=self.case_vhs.isChecked(),
            vhs_vitesse=self.combo_vitesse_vhs.currentData(),
            vhs_generation=int(self.curseur_generation.valeur()),
            vhs_usure=self.curseur_usure.valeur(),
            vhs_gigue=self.curseur_gigue.valeur(),
            vhs_abandons=self.curseur_abandons.valeur(),
            vhs_commutation=self.case_commutation.isChecked(),
            vhs_depassement=self.curseur_liseré.valeur(),
            tube_actif=self.case_tube_camera.isChecked(),
            tube_modele=self.combo_camera.currentData() or "",
            tube_faisceau=self.curseur_faisceau.valeur(),
            tube_anti_comete=self.curseur_anti_comete.valeur(),
            tube_remanence=self.curseur_remanence.valeur(),
            tube_genou=self.curseur_genou.valeur(),
            tube_charge_max=self.curseur_charge_max.valeur(),
            tube_pont=self.curseur_pont.valeur(),
            tube_masquage=self.curseur_masquage.valeur(),
            tube_biais=self.curseur_biais.valeur(),
            tube_eclat=self.curseur_eclat.valeur(),
            tube_seuil=self.curseur_seuil_reflets.valeur(),
            tube_desalignement=self.curseur_desalignement.valeur(),
            cadence_source=self._cadence_source,
            animer=self.case_animer.isChecked(),
            conserver_proportions=self.case_proportions.isChecked(),
            comparaison=self.case_comparaison.isChecked(),
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
        self._appliquer_son(parametres)

        if parametres.vhs_actif:
            luma, chroma = parametres.bandes_vhs()
            lignes_chroma = 2.0 * chroma * NORMES[parametres.norme].duree_ligne_active * 0.75
            self.etiquette_vhs.setText(
                f"Bande enregistrée : {luma / 1e6:.2f} MHz en luminance, "
                f"{chroma / 1e3:.0f} kHz en chrominance — soit environ "
                f"{lignes_chroma:.0f} lignes de définition de couleur, "
                f"contre {2 * luma * NORMES[parametres.norme].duree_ligne_active * 0.75:.0f} "
                "en luminance."
            )
        else:
            self.etiquette_vhs.setText("Aucune cassette : le signal va droit au téléviseur.")

        self._decrire_camera(parametres)

        norme = NORMES[parametres.norme]
        hauteur, largeur = format_tv(norme)
        if self.case_format_tv.isChecked():
            self.etiquette_format_tv.setText(
                f"Chaque image est ramenée à {largeur} × {hauteur} — la trame "
                f"active de la norme, en pixels carrés — avant d'entrer dans la "
                f"chaîne. Une source large y est mise en boîte aux lettres, "
                f"comme un film large diffusé à l'époque.\n\n"
                f"Ce n'est pas qu'une coquetterie : le sous-échantillonnage est "
                f"alors une moyenne d'aire, et non le choix de niveau de détail "
                f"de la carte graphique, qui laisse passer du repliement sur les "
                f"fines rayures — on prendrait pour du cross-color ce qui ne "
                f"serait qu'un défaut de rééchantillonnage."
            )
        else:
            self.etiquette_format_tv.setText(
                "La vidéo entre dans la chaîne à sa résolution d'origine. Le "
                "rééchantillonnage est alors laissé à la carte graphique."
            )

    def _decrire_camera(self, parametres: ParametresRendu) -> None:
        """Dit ce que la caméra choisie va faire, en trames et en pixels."""
        code = self.combo_camera.currentData()
        if code is None:
            self.etiquette_camera.setText(
                "Réglages libres — le menu ne décrit plus le matériel."
            )
        else:
            camera = obtenir_camera(code)
            self.etiquette_camera.setText(
                f"{camera.tube}, vers {camera.annee}. {camera.caractere}"
            )

        if not parametres.tube_actif:
            self.etiquette_tube.setText(
                "Aucune caméra : l'image est prise pour parfaite, comme dans "
                "tout le reste de ce simulateur."
            )
            return

        p = parametres.parametres_tube()
        trames = p.trainee_en_trames()
        secondes = trames / NORMES[parametres.norme].f_trame
        # Sous dix, un entier ne dirait rien : la différence entre un faisceau
        # de 1,15 et un de 1,45 est justement celle qui compte.
        encaisse = p.capacite()
        chiffres = ".2f" if encaisse < 10.0 else ".0f"
        texte = (
            f"Le faisceau encaisse {encaisse:{chiffres}} fois le blanc sans "
            f"laisser de traînée. "
        )
        if trames <= 0.0:
            texte += (
                f"Le reflet réglé à {p.eclat_reflets:.0f} fois le blanc passe "
                "sous cette limite : aucune queue de comète."
            )
        else:
            texte += (
                f"Un reflet à {p.eclat_reflets:.0f} fois le blanc met "
                f"{trames:.0f} trames à s'effacer, soit {secondes * 1000:.0f} ms. "
                f"Un objet qui traverse l'écran en une seconde traîne ainsi sur "
                f"{secondes * 100:.0f} % de la largeur."
            )
        self.etiquette_tube.setText(texte)

    def _parametres_son(self) -> ParametresSon:
        return ParametresSon(
            actif=self.case_son_tv.isChecked(),
            rapport_signal_bruit=(
                self.curseur_bruit.valeur() if self.case_bruit.isChecked() else None
            ),
            intercarrier=self.curseur_intercarrier.valeur(),
            desaccord=self.curseur_desaccord.valeur(),
            gain_entree=10.0 ** (self.curseur_gain_son.valeur() / 20.0),
            gain_sortie=10.0 ** (self.curseur_gain_sortie.valeur() / 20.0),
        )

    def _appliquer_son(self, parametres: ParametresRendu) -> None:
        reglages = self._parametres_son()
        self.source.definir_son_tv(parametres.norme, reglages)

        norme = NORMES[parametres.norme]
        voie = norme.son
        detail = (
            f"±{voie.deviation / 1e3:.0f} kHz d'excursion, "
            f"préaccentuation {voie.preaccentuation * 1e6:.0f} µs"
            if voie.modulation == "FM"
            else f"taux de modulation {voie.taux_am:.0%}, sans préaccentuation"
        )
        self.etiquette_porteuse.setText(
            f"{norme.nom}\n"
            f"Porteuse à +{voie.decalage / 1e6:.1f} MHz de la porteuse image, "
            f"modulée en {'fréquence' if voie.modulation == 'FM' else 'AMPLITUDE'}, "
            f"{detail}. Émise à {voie.niveau_porteuse_db:.0f} dB sous l'image, "
            f"bande audio {voie.bande_audio / 1e3:.0f} kHz."
        )

        if reglages.rapport_signal_bruit is None:
            self.etiquette_cn.setText("Canal parfait : aucun bruit sur aucune des deux voies.")
            return

        cn = rapport_porteuse_bruit(norme, reglages.rapport_signal_bruit)
        gain = gain_de_demodulation_db(voie)
        self.etiquette_cn.setText(
            f"Image {reglages.rapport_signal_bruit:.0f} dB  →  porteuse son "
            f"{cn:.1f} dB de rapport porteuse/bruit.\n"
            + (
                f"La démodulation de fréquence en récupère environ {gain:.0f} dB : "
                "le son tient largement."
                if gain > 0
                else "La démodulation d'amplitude n'en récupère AUCUN : "
                "le son se dégrade au même rythme que l'image."
            )
        )

    # ------------------------------------------------------------------
    # Source
    # ------------------------------------------------------------------

    def _charger_mire(self, *_args) -> None:
        nom = self.combo_mire.currentData()
        if nom is None:
            return
        self.source.pause()
        self._maj_bouton()
        # Une mire est une image fixe : plus de cadence, donc une trame par
        # image pour la caméra, sans quoi elle rattraperait le temps d'une vidéo
        # qui ne défile plus.
        self._cadence_source = 0.0
        self._appliquer()
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
        self.action_export.setEnabled(True)
        self._cadence_source = float(infos.images_par_seconde)
        self._appliquer()

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
        if self.case_format_tv.isChecked():
            image = ramener_au_format_tv(image, NORMES[self.combo_norme.currentData()])
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
        elif touche == QtCore.Qt.Key_C:
            # Porté par la fenêtre et non par la case, pour que le volet de
            # comparaison reste accessible en plein écran, où le panneau de
            # réglages est masqué — une case cachée ne reçoit plus rien.
            self.case_comparaison.toggle()
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

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _exporter(self) -> None:
        """Convertit la vidéo courante en MP4, effets de tube et son compris."""
        if self.source.infos is None:
            QtWidgets.QMessageBox.information(
                self, "Export", "Ouvrez d'abord une vidéo."
            )
            return

        source = self.source.infos.chemin
        defaut = str(Path(source).with_name(
            Path(source).stem + f"_{self.combo_norme.currentData()}.mp4"
        ))
        destination, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter en MP4", defaut, "Vidéo MP4 (*.mp4)"
        )
        if not destination:
            return

        hauteur, valide = QtWidgets.QInputDialog.getInt(
            self, "Hauteur de l'image",
            "Hauteur en pixels — au-delà de 1152, les lignes de balayage\n"
            "passent enfin la limite de Shannon et deviennent franches :",
            1152, 240, 2160, 24,
        )
        if not valide:
            return

        etait_en_lecture = self.source.en_lecture
        self.source.pause()

        reglages = ReglagesExport(destination=destination, hauteur=hauteur)
        largeur, hauteur = dimensions(hauteur)

        dialogue = QtWidgets.QProgressDialog(
            f"Export en {largeur}×{hauteur}…", "Annuler", 0, 100, self
        )
        dialogue.setWindowTitle("Export MP4")
        dialogue.setWindowModality(QtCore.Qt.WindowModal)
        dialogue.setMinimumDuration(0)
        dialogue.setAutoClose(False)

        exportateur = ExportateurMP4(self.vue, self)
        dialogue.canceled.connect(exportateur.annuler)

        def avancer(n, total):
            if total > 0:
                dialogue.setMaximum(total)
                dialogue.setValue(n)
                dialogue.setLabelText(
                    f"Export en {largeur}×{hauteur} — image {n} sur {total}"
                )
            else:
                dialogue.setMaximum(0)
                dialogue.setLabelText(f"Export en {largeur}×{hauteur} — image {n}")

        exportateur.progression.connect(avancer)
        exportateur.terminee.connect(
            lambda message: self._etat.setText(f"Export terminé — {message}")
        )
        exportateur.echouee.connect(
            lambda message: QtWidgets.QMessageBox.warning(self, "Export", message)
        )

        # L'image affichée est perdue pendant l'export : la vue sert de moteur
        # de rendu, image par image. On la remet ensuite là où elle était.
        try:
            exportateur.exporter(
                source, reglages, self.combo_norme.currentData(), self._parametres_son()
            )
        finally:
            dialogue.close()
            self.source.chercher(self._position)
            if etait_en_lecture:
                self.source.lire()

    # ------------------------------------------------------------------

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
