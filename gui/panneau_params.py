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


class PanneauParametres(QtWidgets.QScrollArea):
    """Tous les réglages de la chaîne, regroupés par étage."""

    modifie = QtCore.pyqtSignal()
    norme_changee = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(330)

        contenu = QtWidgets.QWidget()
        self._colonne = QtWidgets.QVBoxLayout(contenu)
        self._colonne.setContentsMargins(8, 8, 8, 8)
        self._colonne.setSpacing(8)
        self.setWidget(contenu)

        self._silencieux = False
        self._construire_norme()
        self._construire_codage()
        self._construire_canal()
        self._construire_decodage()
        self._construire_colorimetrie()
        self._colonne.addStretch(1)

        self._appliquer_norme(self.code_norme())

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
