"""
Panneau de réglages — la face visible de tous les paramètres normatifs.

Chaque commande correspond à un champ précis des dataclasses de `tvcolor`.
Les libellés s'adaptent à la norme choisie : l'axe de chrominance étroit
s'appelle Q en NTSC, V en PAL, D'R en SECAM, et ne recouvre pas les mêmes
réalités.
"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from tvcolor.canal import ParametresCanal
from tvcolor.constantes import NORMES, obtenir_norme
from tvcolor.decodeur import ParametresDecodage
from tvcolor.encodeur import ParametresEncodage
from tvcolor.pipeline import Parametres
from tvcolor.tube import (
    CAMERA_PAR_DEFAUT,
    CAMERAS,
    ParametresTube,
    obtenir_camera,
)
from tvcolor.vhs import ParametresVHS

from .widgets_base import Curseur, Groupe, note

SEPARATEURS = [
    ("peigne", "Filtre en peigne (1H en NTSC, 2H en PAL)"),
    ("peigne3", "Peigne symétrique à trois lignes"),
    ("notch", "Réjecteur de sous-porteuse (téléviseur simple)"),
    ("parfait", "Séparation parfaite (référence théorique)"),
]

_LIBELLES_CHROMA = {
    "NTSC": ("Bande de I (orange–cyan)", "Bande de Q (vert–magenta)"),
    "PAL": ("Bande de U (B'−Y')", "Bande de V (R'−Y')"),
    "SECAM": ("Bande de D'B (bleu)", "Bande de D'R (rouge)"),
}


class PanneauParametres(QtWidgets.QTabWidget):
    """Tous les réglages de la chaîne, en onglets.

    Le découpage suit ce que les réglages GOUVERNENT, et non l'ordre dans
    lequel le signal les traverse.

    Le bruit a son propre onglet, et c'est la raison d'être de ce découpage :
    depuis que la voie son existe, **il n'appartient plus à l'image**. Il n'y a
    qu'un canal et qu'une densité de bruit ; l'image et le son y puisent tous
    les deux, chacun selon sa largeur de bande. Le laisser dans l'onglet Image
    laissait croire le contraire.
    """

    modifie = QtCore.pyqtSignal()
    norme_changee = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        self._silencieux = False

        self._colonne = self._nouvelle_page("Image")
        self._construire_norme()
        self._construire_codage()
        self._construire_decodage()
        self._construire_colorimetrie()
        self._colonne.addStretch(1)

        self._colonne = self._nouvelle_page("Caméra")
        self._construire_camera()
        self._colonne.addStretch(1)

        self._colonne = self._nouvelle_page("Bruit")
        self._construire_canal()
        self._colonne.addStretch(1)

        self._colonne = self._nouvelle_page("Magnétoscope")
        self._construire_magnetoscope()
        self._colonne.addStretch(1)

        self._appliquer_norme(self.code_norme())

    def _nouvelle_page(self, titre: str) -> QtWidgets.QVBoxLayout:
        """Ajoute un onglet défilant, et retourne la colonne où le garnir."""
        defilement = QtWidgets.QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        contenu = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(contenu)
        colonne.setContentsMargins(8, 8, 8, 8)
        colonne.setSpacing(8)
        defilement.setWidget(contenu)
        self.addTab(defilement, titre)
        return colonne

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _construire_norme(self) -> None:
        groupe = Groupe("Norme")
        self.combo_norme = QtWidgets.QComboBox()
        for code, norme in NORMES.items():
            self.combo_norme.addItem(norme.nom, code)
        self.combo_norme.setCurrentIndex(self.combo_norme.findData("PAL-BG"))
        self.combo_norme.currentIndexChanged.connect(self._sur_norme)
        groupe.ajouter(self.combo_norme)

        self.resume_norme = note("")
        groupe.ajouter(self.resume_norme)
        self._colonne.addWidget(groupe)

    def _construire_codage(self) -> None:
        groupe = Groupe("Codage")
        self.bande_y = Curseur("Bande de luminance", 0.5, 8.0, 5.0, 0.1, "MHz", 1)
        self.bande_c1 = Curseur("Bande de U", 0.1, 3.0, 1.3, 0.05, "MHz", 2)
        self.bande_c2 = Curseur("Bande de V", 0.1, 3.0, 1.3, 0.05, "MHz", 2)
        self.saturation_emission = Curseur("Amplitude de chrominance", 0.0, 2.0, 1.0, 0.05, "×", 2)
        for c in (self.bande_y, self.bande_c1, self.bande_c2, self.saturation_emission):
            c.valeur_changee.connect(self._signaler)
            groupe.ajouter(c)

        self.case_piedestal = QtWidgets.QCheckBox("Piédestal de la norme (setup 7,5 IRE)")
        self.case_piedestal.setChecked(True)
        self.case_piedestal.toggled.connect(self._signaler)
        groupe.ajouter(self.case_piedestal)

        self.case_entrelace = QtWidgets.QCheckBox("Balayage entrelacé")
        self.case_entrelace.toggled.connect(self._signaler)
        groupe.ajouter(self.case_entrelace)

        self.spin_image = QtWidgets.QSpinBox()
        self.spin_image.setRange(0, 999)
        self.spin_image.valueChanged.connect(self._signaler)
        groupe.ajouter_ligne("Numéro d'image", self.spin_image)
        groupe.ajouter(
            note(
                "La phase de sous-porteuse dépend du temps absolu : changer le "
                "numéro d'image déplace le motif de points. C'est ce qui les "
                "fait « ramper » sur un téléviseur."
            )
        )
        self._colonne.addWidget(groupe)

    def _construire_canal(self) -> None:
        groupe = Groupe("Canal de transmission")

        self.case_bruit = QtWidgets.QCheckBox("Bruit")
        self.case_bruit.toggled.connect(self._signaler)
        groupe.ajouter(self.case_bruit)
        self.rapport_sb = Curseur("Rapport signal/bruit", 12.0, 60.0, 40.0, 1.0, "dB", 0)
        self.rapport_sb.valeur_changee.connect(self._signaler)
        groupe.ajouter(self.rapport_sb)

        self.phase_diff = Curseur("Phase différentielle", 0.0, 90.0, 0.0, 1.0, "°", 0)
        self.gain_diff = Curseur("Gain différentiel", -1.0, 1.0, 0.0, 0.05, "", 2)
        self.echo = Curseur("Écho (image fantôme)", 0.0, 0.6, 0.0, 0.02, "", 2)
        self.echo_retard = Curseur("Retard de l'écho", 0.1, 5.0, 0.5, 0.1, "µs", 1)
        for c in (self.phase_diff, self.gain_diff, self.echo, self.echo_retard):
            c.valeur_changee.connect(self._signaler)
            groupe.ajouter(c)

        groupe.ajouter(
            note(
                "La phase différentielle est le défaut historique du NTSC : le "
                "déphasage de l'émetteur dépend du niveau de luminance, donc la "
                "teinte varie avec la luminosité. Comparez les trois normes en "
                "poussant ce curseur."
            )
        )
        groupe.ajouter(note(
            "Ces réglages ont leur propre onglet pour une raison précise : le "
            "bruit N'APPARTIENT PAS à l'image. Il y a un canal, une densité de "
            "bruit, et deux porteuses qui y puisent — celle de l'image et celle "
            "du son. Ce que chacune en récolte se déduit de sa largeur de bande "
            "et de sa puissance d'émission ; l'onglet Son montre le calcul et "
            "ce qu'il donne à l'oreille."
        ))
        self._colonne.addWidget(groupe)

    def _construire_camera(self) -> None:
        """La caméra à tubes — le premier maillon, bien avant le codeur."""
        groupe = Groupe("Caméra")

        self.case_tube = QtWidgets.QCheckBox("Filmer avec une caméra à tubes")
        self.case_tube.toggled.connect(self._signaler)
        groupe.ajouter(self.case_tube)

        self.combo_camera = QtWidgets.QComboBox()
        self.combo_camera.addItem("Réglage libre", None)
        for camera in CAMERAS.values():
            self.combo_camera.addItem(f"{camera.annee} — {camera.nom}", camera.code)
        self.combo_camera.setCurrentIndex(self.combo_camera.findData(CAMERA_PAR_DEFAUT))
        self.combo_camera.currentIndexChanged.connect(self._sur_modele_camera)
        groupe.ajouter(QtWidgets.QLabel("Modèle"))
        groupe.ajouter(self.combo_camera)

        self.etiquette_camera = note("")
        groupe.ajouter(self.etiquette_camera)
        self._colonne.addWidget(groupe)

        # Les valeurs de départ viennent de la table des caméras, et non de
        # constantes recopiées ici : le menu afficherait sinon un modèle dont
        # les curseurs ne diraient pas tout à fait la même chose.
        depart = obtenir_camera(CAMERA_PAR_DEFAUT)

        groupe = Groupe("Le matériel")
        self.faisceau = Curseur(
            "Courant du faisceau", 1.0, 4.0, depart.faisceau, 0.05, " × blanc", 2)
        self.anti_comete = Curseur(
            "Circuit anti-comète", 0.0, 1.0, depart.anti_comete, 0.05, "", 2)
        self.remanence = Curseur(
            "Rémanence du tube", 0.0, 0.9, depart.remanence, 0.05, "", 2)
        self.genou_remanence = Curseur(
            "Genou de rémanence", 0.02, 1.20, depart.genou_remanence, 0.01, "", 2)
        self.charge_maximale = Curseur(
            "Capacité de la cible", 2.0, 40.0, depart.charge_maximale, 0.5,
            " × blanc", 1)
        self.biais = Curseur(
            "Lumière de biais", 0.0, 0.15, depart.lumiere_de_biais, 0.01, "", 2)
        self.desalignement = Curseur(
            "Désalignement des tubes", 0.0, 6.0, depart.desalignement, 0.1, " px", 1)
        self.masquage = Curseur(
            "Matrice de masquage", 0.0, 1.0, depart.masquage, 0.05, "", 2)
        self._curseurs_camera = (
            self.faisceau, self.anti_comete, self.remanence, self.genou_remanence,
            self.charge_maximale, self.biais, self.desalignement, self.masquage,
        )
        for curseur in self._curseurs_camera:
            curseur.valeur_changee.connect(self._sur_curseur_camera)
            groupe.ajouter(curseur)
        self._colonne.addWidget(groupe)

        groupe = Groupe("La scène (ce que la caméra regarde)")
        self.eclat_reflets = Curseur("Éclat des reflets", 0.0, 100.0, 25.0, 1.0, " × blanc", 0)
        self.seuil_reflets = Curseur("Seuil des reflets", 0.4, 1.0, 0.75, 0.01, "", 2)
        for curseur in (self.eclat_reflets, self.seuil_reflets):
            curseur.valeur_changee.connect(self._signaler)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Ces deux-là ne décrivent pas la caméra mais le PLATEAU qu'elle "
            "filme, et le menu des modèles n'y touche donc pas : deux caméras "
            "différentes braquées sur les mêmes cymbales y voient les mêmes "
            "reflets.\n\n"
            "Ils existent parce qu'un fichier huit bits a déjà été écrêté par "
            "celui qui l'a fabriqué : aucun pixel n'y dépasse le blanc, et sans "
            "rien faire la cible ne serait jamais en surcharge — il n'y aurait "
            "donc pas la moindre queue de comète."
        ))
        self._colonne.addWidget(groupe)

        groupe = Groupe("Le filé (image fixe seulement)")
        self.vitesse_file = Curseur("Vitesse du filé", -30.0, 30.0, 6.0, 1.0, " px/trame", 0)
        self.champs_tube = Curseur("Trames intégrées", 1.0, 60.0, 14.0, 1.0, "", 0)
        for curseur in (self.vitesse_file, self.champs_tube):
            curseur.valeur_changee.connect(self._signaler)
            groupe.ajouter(curseur)
        groupe.ajouter(note(
            "Une image fixe ne peut pas montrer de queue de comète : la traînée "
            "EST la trace du passé d'un point qui a bougé, et une image fixe n'a "
            "pas de passé. On simule donc le seul mouvement dont on dispose, "
            "celui de la caméra : la scène glisse de tant de pixels par trame, on "
            "intègre le nombre de trames demandé, et l'on n'affiche que la "
            "dernière. Ce qui apparaît alors est le résultat d'un calcul sur "
            "quatorze trames, pas un flou directionnel — et cela se voit : la "
            "traînée s'arrête net au lieu de s'éteindre en fondu."
        ))
        self._colonne.addWidget(groupe)

        groupe = Groupe("Ce que la caméra fait")
        groupe.ajouter(note(
            "Un tube analyseur ne mesure pas la lumière : il mesure la CHARGE que "
            "la lumière a soutirée à une cible photoconductrice, et c'est le "
            "courant qu'il faut au faisceau pour la remettre à niveau qui fait le "
            "signal vidéo.\n\n"
            "Le faisceau a un débit maximal, réglé pour évacuer 130 % du blanc. "
            "Un reflet sur du chrome sous un projecteur en fait vingt-cinq fois. "
            "Le faisceau en évacue une tranche FIXE par trame — d'où une "
            "décroissance arithmétique et non exponentielle, et une traînée qui "
            "s'arrête net. Elle se lit tout du long au maximum que le faisceau "
            "sait fournir, donc au blanc écrêté : elle est plate, et l'image "
            "disparaît derrière elle.\n\n"
            "Le circuit anti-comète, livré par Philips en 1976, augmente "
            "fortement le courant pendant la suppression ligne pour vider "
            "l'excès. Passer du modèle de 1970 à celui de 1977 fait exactement "
            "cela : les traînées disparaissent sans qu'on ait changé de tube."
        ))
        self._colonne.addWidget(groupe)

        self._decrire_camera()

    def _sur_modele_camera(self, *_args) -> None:
        """Pose les six réglages du matériel choisi, en un seul rendu.

        L'entrée « Réglage libre » ne touche à rien : elle est l'état dans lequel
        bascule le menu dès qu'on déplace un curseur, et la choisir soi-même ne
        doit donc rien changer.
        """
        if self._silencieux:
            return
        code = self.combo_camera.currentData()
        if code is None:
            self._decrire_camera()
            return

        camera = obtenir_camera(code)
        precedent, self._silencieux = self._silencieux, True
        try:
            self.faisceau.definir(camera.faisceau)
            self.anti_comete.definir(camera.anti_comete)
            self.remanence.definir(camera.remanence)
            self.genou_remanence.definir(camera.genou_remanence)
            self.charge_maximale.definir(camera.charge_maximale)
            self.biais.definir(camera.lumiere_de_biais)
            self.desalignement.definir(camera.desalignement)
            self.masquage.definir(camera.masquage)
        finally:
            self._silencieux = precedent
        self._decrire_camera()
        self._signaler()

    def _sur_curseur_camera(self, *_args) -> None:
        """Un curseur bougé : on n'est plus sur un modèle d'origine."""
        if self._silencieux:
            return
        if self.combo_camera.currentData() is not None:
            precedent, self._silencieux = self._silencieux, True
            try:
                self.combo_camera.setCurrentIndex(0)
            finally:
                self._silencieux = precedent
            self._decrire_camera()
        self._signaler()

    def _decrire_camera(self) -> None:
        """Rappelle en clair ce que le modèle choisi a de particulier."""
        code = self.combo_camera.currentData()
        if code is None:
            self.etiquette_camera.setText(
                "Réglages libres — le menu ne décrit plus le matériel."
            )
            return
        camera = obtenir_camera(code)
        self.etiquette_camera.setText(
            f"{camera.tube}, vers {camera.annee}. {camera.caractere}\n\n"
            f"Encaisse {camera.encaisse():{'.2f' if camera.encaisse() < 10.0 else '.0f'}} "
            f"fois le blanc sans traîner ; "
            f"rémanence mesurée à {camera.lag_troisieme_trame:.2f} % de résidu "
            f"en troisième trame, à 5 % du blanc."
        )

    def _construire_magnetoscope(self) -> None:
        """Le magnétoscope, entre l'antenne et le téléviseur — sa vraie place."""
        groupe = Groupe("Magnétoscope (cassette VHS)")

        self.case_vhs = QtWidgets.QCheckBox("Passer par une cassette")
        self.case_vhs.toggled.connect(self._signaler)
        groupe.ajouter(self.case_vhs)

        self.combo_vitesse_vhs = QtWidgets.QComboBox()
        for code, libelle in (
            ("SP", "SP — 3 heures, la meilleure définition"),
            ("LP", "LP — 6 heures"),
            ("EP", "EP — 9 heures, la plus mauvaise"),
        ):
            self.combo_vitesse_vhs.addItem(libelle, code)
        self.combo_vitesse_vhs.currentIndexChanged.connect(self._signaler)
        groupe.ajouter(QtWidgets.QLabel("Vitesse de défilement"))
        groupe.ajouter(self.combo_vitesse_vhs)

        self.generation_vhs = Curseur("Génération de copie", 1.0, 5.0, 1.0, 1.0, "", 0)
        self.usure_vhs = Curseur("Usure de la bande", 0.0, 1.0, 0.15, 0.05, "", 2)
        self.gigue_vhs = Curseur("Gigue de défilement", 0.0, 1.0, 0.35, 0.05, "", 2)
        self.abandons_vhs = Curseur("Pertes de signal", 0.0, 1.0, 0.25, 0.05, "", 2)
        self.depassement_vhs = Curseur("Liseré de contour", 0.0, 2.0, 0.8, 0.05, "", 2)
        for c in (self.generation_vhs, self.usure_vhs, self.gigue_vhs,
                  self.abandons_vhs, self.depassement_vhs):
            c.valeur_changee.connect(self._signaler)
            groupe.ajouter(c)

        self.case_commutation = QtWidgets.QCheckBox("Commutation des têtes (bas de l'image)")
        self.case_commutation.setChecked(True)
        self.case_commutation.toggled.connect(self._signaler)
        groupe.ajouter(self.case_commutation)

        self.etiquette_vhs = note("")
        groupe.ajouter(self.etiquette_vhs)
        groupe.ajouter(note(
            "Un magnétoscope n'enregistre pas le composite tel quel : il sépare "
            "luminance et chrominance, module la première en fréquence et "
            "TRANSPOSE la seconde sous elle, à 627 kHz. D'où le nom de "
            "color-under, et d'où la caractéristique du format : la couleur du "
            "VHS est huit fois moins fine que sa luminance.\n\n"
            "La gigue est l'artefact le plus reconnaissable — la bande ne défile "
            "pas d'un mouvement parfait, et les verticales ondulent. Elle ne fait "
            "PAS tourner la teinte : la porteuse de relecture est régénérée à "
            "partir du signal lu, et l'erreur s'annule dans la démodulation."
        ))
        self._colonne.addWidget(groupe)

    def _construire_decodage(self) -> None:
        groupe = Groupe("Décodage (le récepteur)")

        self.combo_separateur = QtWidgets.QComboBox()
        for code, libelle in SEPARATEURS:
            self.combo_separateur.addItem(libelle, code)
        self.combo_separateur.currentIndexChanged.connect(self._signaler)
        groupe.ajouter(QtWidgets.QLabel("Séparation luminance / chrominance"))
        groupe.ajouter(self.combo_separateur)

        self.case_ligne_retard = QtWidgets.QCheckBox("Ligne à retard (PAL-D)")
        self.case_ligne_retard.setChecked(True)
        self.case_ligne_retard.toggled.connect(self._signaler)
        groupe.ajouter(self.case_ligne_retard)
        groupe.ajouter(
            note(
                "Décochez pour obtenir le PAL-S des premiers récepteurs, et voir "
                "apparaître les barres de Hanover dès que la phase dérive."
            )
        )

        self.bande_chroma_dec = Curseur("Bande chroma au décodage", 0.2, 3.0, 1.3, 0.05, "MHz", 2)
        self.desaccord = Curseur("Désaccord de sous-porteuse", -2000.0, 2000.0, 0.0, 25.0, "Hz", 0)
        self.teinte = Curseur("Réglage de teinte", -60.0, 60.0, 0.0, 1.0, "°", 0)
        self.saturation_dec = Curseur("Réglage de saturation", 0.0, 2.0, 1.0, 0.05, "×", 2)
        for c in (self.bande_chroma_dec, self.desaccord, self.teinte, self.saturation_dec):
            c.valeur_changee.connect(self._signaler)
            groupe.ajouter(c)

        self._colonne.addWidget(groupe)

    def _construire_colorimetrie(self) -> None:
        groupe = Groupe("Colorimétrie")
        self.case_gamma = QtWidgets.QCheckBox("Appliquer le gamma de la norme")
        self.case_gamma.setChecked(True)
        self.case_gamma.toggled.connect(self._signaler)
        groupe.ajouter(self.case_gamma)

        self.case_primaires = QtWidgets.QCheckBox("Simuler les primaires de la norme")
        self.case_primaires.toggled.connect(self._signaler)
        groupe.ajouter(self.case_primaires)
        groupe.ajouter(
            note(
                "Réinterprète l'image dans les primaires du système, puis la "
                "ramène en sRGB pour l'affichage. Choisissez la norme "
                "« NTSC 1953 » pour voir l'effet du gamut d'origine, que plus "
                "aucun tube n'a jamais su reproduire."
            )
        )

        bouton = QtWidgets.QPushButton("Revenir aux valeurs normatives")
        bouton.clicked.connect(self.reinitialiser)
        groupe.ajouter(bouton)
        self._colonne.addWidget(groupe)

    # ------------------------------------------------------------------
    # Réactions
    # ------------------------------------------------------------------

    def code_norme(self) -> str:
        return self.combo_norme.currentData()

    def _sur_norme(self) -> None:
        code = self.code_norme()
        self._appliquer_norme(code)
        self.norme_changee.emit(code)
        self._signaler()

    def _appliquer_norme(self, code: str) -> None:
        """Recale les libellés, les valeurs par défaut et ce qui est pertinent."""
        norme = obtenir_norme(code)
        precedent, self._silencieux = self._silencieux, True
        try:
            self.bande_y.definir(norme.bande_y / 1e6)
            self.bande_c1.definir(norme.bande_c1 / 1e6)
            self.bande_c2.definir(norme.bande_c2 / 1e6)
            self.bande_chroma_dec.definir(max(norme.bande_c1, norme.bande_c2) / 1e6)

            libelle1, libelle2 = _LIBELLES_CHROMA[norme.famille]
            self.bande_c1.definir_libelle(libelle1)
            self.bande_c2.definir_libelle(libelle2)

            self.case_piedestal.setEnabled(norme.piedestal > 0.0)
            self.case_ligne_retard.setEnabled(norme.famille == "PAL")
            # En SECAM, aucun peigne ne peut fonctionner : les sous-porteuses
            # sont des multiples entiers de la fréquence ligne, elles ne
            # s'inversent jamais d'une ligne à l'autre.
            secam = norme.famille == "SECAM"
            for rang in range(self.combo_separateur.count()):
                actif = not secam or self.combo_separateur.itemData(rang) in (
                    "notch", "parfait"
                )
                self.combo_separateur.model().item(rang).setEnabled(actif)
            if secam and self.combo_separateur.currentData() not in ("notch", "parfait"):
                self.combo_separateur.setCurrentIndex(
                    self.combo_separateur.findData("notch")
                )
            self.desaccord.setEnabled(not secam)
            self.teinte.setEnabled(not secam)

            self.resume_norme.setText(
                f"{norme.lignes_totales} lignes · {norme.f_trame:.2f} trames/s · "
                f"f_H = {norme.f_ligne:,.0f} Hz\n"
                f"sous-porteuse {norme.f_sc / 1e6:.6f} MHz "
                f"= {norme.cycles_sous_porteuse_par_ligne:.4f} · f_H\n"
                f"soit {norme.avance_phase_par_ligne_deg:.3f}° de rotation par ligne\n"
                f"image utile {norme.lignes_actives} × {norme.echantillons_par_ligne} "
                f"échantillons à {norme.f_echantillonnage / 1e6:.3f} MHz"
                .replace(",", " ")
            )
        finally:
            self._silencieux = precedent

    def reinitialiser(self) -> None:
        precedent, self._silencieux = self._silencieux, True
        try:
            self.saturation_emission.definir(1.0)
            self.case_piedestal.setChecked(True)
            self.case_entrelace.setChecked(False)
            self.spin_image.setValue(0)
            self.case_bruit.setChecked(False)
            self.case_tube.setChecked(False)
            self.combo_camera.setCurrentIndex(
                self.combo_camera.findData(CAMERA_PAR_DEFAUT)
            )
            camera = obtenir_camera(CAMERA_PAR_DEFAUT)
            self.faisceau.definir(camera.faisceau)
            self.anti_comete.definir(camera.anti_comete)
            self.remanence.definir(camera.remanence)
            self.genou_remanence.definir(camera.genou_remanence)
            self.charge_maximale.definir(camera.charge_maximale)
            self.biais.definir(camera.lumiere_de_biais)
            self.desalignement.definir(camera.desalignement)
            self.masquage.definir(camera.masquage)
            self.eclat_reflets.definir(25.0)
            self.seuil_reflets.definir(0.75)
            self.vitesse_file.definir(6.0)
            self.champs_tube.definir(14.0)
            self._decrire_camera()
            self.rapport_sb.definir(40.0)
            self.phase_diff.definir(0.0)
            self.gain_diff.definir(0.0)
            self.echo.definir(0.0)
            self.echo_retard.definir(0.5)
            self.combo_separateur.setCurrentIndex(0)
            self.case_ligne_retard.setChecked(True)
            self.desaccord.definir(0.0)
            self.teinte.definir(0.0)
            self.saturation_dec.definir(1.0)
            self.case_gamma.setChecked(True)
            self.case_primaires.setChecked(False)
            self._appliquer_norme(self.code_norme())
        finally:
            self._silencieux = precedent
        self._signaler()

    def _signaler(self, *_args) -> None:
        if not self._silencieux:
            self.modifie.emit()

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def parametres(self) -> Parametres:
        """Assemble l'objet `Parametres` correspondant à l'état de l'interface."""
        return Parametres(
            norme=self.code_norme(),
            encodage=ParametresEncodage(
                bande_y=self.bande_y.valeur() * 1e6,
                bande_c1=self.bande_c1.valeur() * 1e6,
                bande_c2=self.bande_c2.valeur() * 1e6,
                amplitude_chroma=self.saturation_emission.valeur(),
                piedestal=self.case_piedestal.isChecked(),
                entrelace=self.case_entrelace.isChecked(),
                numero_image=self.spin_image.value(),
            ),
            tube=ParametresTube(
                actif=self.case_tube.isChecked(),
                faisceau=self.faisceau.valeur(),
                anti_comete=self.anti_comete.valeur(),
                remanence=self.remanence.valeur(),
                genou_remanence=self.genou_remanence.valeur(),
                charge_maximale=self.charge_maximale.valeur(),
                lumiere_de_biais=self.biais.valeur(),
                eclat_reflets=self.eclat_reflets.valeur(),
                seuil_reflets=self.seuil_reflets.valeur(),
                desalignement=self.desalignement.valeur(),
                masquage=self.masquage.valeur(),
                mouvement=(self.vitesse_file.valeur(), 0.0),
                champs=int(self.champs_tube.valeur()),
            ),
            vhs=ParametresVHS(
                actif=self.case_vhs.isChecked(),
                vitesse=self.combo_vitesse_vhs.currentData(),
                generation=int(self.generation_vhs.valeur()),
                usure=self.usure_vhs.valeur(),
                gigue=self.gigue_vhs.valeur(),
                abandons=self.abandons_vhs.valeur(),
                commutation_tetes=self.case_commutation.isChecked(),
                depassement=self.depassement_vhs.valeur(),
            ),
            canal=ParametresCanal(
                rapport_signal_bruit=(
                    self.rapport_sb.valeur() if self.case_bruit.isChecked() else None
                ),
                phase_differentielle=self.phase_diff.valeur(),
                gain_differentiel=self.gain_diff.valeur(),
                echo_amplitude=self.echo.valeur(),
                echo_retard_us=self.echo_retard.valeur(),
            ),
            decodage=ParametresDecodage(
                separateur=self.combo_separateur.currentData(),
                ligne_a_retard=self.case_ligne_retard.isChecked(),
                bande_chroma=self.bande_chroma_dec.valeur() * 1e6,
                desaccord_sous_porteuse=self.desaccord.valeur(),
                erreur_teinte=self.teinte.valeur(),
                gain_saturation=self.saturation_dec.valeur(),
            ),
            simuler_primaires=self.case_primaires.isChecked(),
            simuler_gamma=self.case_gamma.isChecked(),
        )
