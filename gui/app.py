"""
Fenêtre principale du simulateur.

Organisation : les réglages à gauche, les images au centre, les instruments
en dessous. Toute modification d'un réglage relance un rendu complet dans un
fil séparé, après une courte temporisation qui évite de recalculer trente
fois pendant qu'un curseur glisse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from tvcolor import mesures, mires
from tvcolor.constantes import NORMES
from tvcolor.pipeline import Parametres, Resultat, encoder_decoder

from .onglet_son import OngletSon
from .panneau_params import PanneauParametres
from .vue_images import VueImages
from .widgets_mesure import Bilan, FormeOnde, Oscilloscope, ProfilLigne, Spectre, Vectorscope
from .worker import MoteurDeRendu

TAILLE_MIRE = (576, 768)
LARGEUR_MAX_IMAGE = 1024


def charger_image(chemin: str) -> np.ndarray:
    """Lit un fichier image et le ramène en sRGB flottant (H, W, 3) dans [0, 1]."""
    from PIL import Image

    with Image.open(chemin) as fichier:
        image = fichier.convert("RGB")
        if image.width > LARGEUR_MAX_IMAGE:
            hauteur = round(image.height * LARGEUR_MAX_IMAGE / image.width)
            image = image.resize((LARGEUR_MAX_IMAGE, hauteur), Image.LANCZOS)
        return np.asarray(image, dtype=np.float64) / 255.0


def enregistrer_image(image: np.ndarray, chemin: str) -> None:
    from PIL import Image

    Image.fromarray((np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)).save(chemin)


class FenetrePrincipale(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codage couleur de la télévision analogique — NTSC · PAL · SECAM")
        self.resize(1620, 980)

        self._source = mires.obtenir_mire("Barres de couleur 75 %", *TAILLE_MIRE)
        self._nom_source = "Barres de couleur 75 %"
        self._dernier_resultat: Resultat | None = None

        self._moteur = MoteurDeRendu(self)
        self._moteur.resultat_pret.connect(self._sur_resultat)
        self._moteur.erreur.connect(self._sur_erreur)
        self._moteur.occupation_changee.connect(self._sur_occupation)

        self._temporisation = QtCore.QTimer(self)
        self._temporisation.setSingleShot(True)
        self._temporisation.setInterval(180)
        self._temporisation.timeout.connect(self._rendre)

        self._construire_interface()
        self._construire_menus()
        self._demander_rendu()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _construire_interface(self) -> None:
        self.panneau = PanneauParametres()
        self.panneau.modifie.connect(self._demander_rendu)
        self.panneau.modifie.connect(self._contexte_son)

        # Deux onglets : l'image d'un côté, le son de l'autre. Ils partagent la
        # norme et le canal — il n'y a qu'une porteuse image et qu'un bruit —
        # mais rien d'autre, et les mêler dans un seul panneau le rendait
        # interminable.
        self.onglet_son = OngletSon()
        self.reglages = QtWidgets.QTabWidget()
        self.reglages.addTab(self.panneau, "Image")
        self.reglages.addTab(self.onglet_son, "Son")
        self.reglages.setMinimumWidth(360)

        self.vues = VueImages()
        self.vues.ligne_choisie.connect(self._sur_ligne)

        self.oscilloscope = Oscilloscope()
        self.profil = ProfilLigne()
        self.vectorscope = Vectorscope()
        self.spectre = Spectre()
        self.forme_onde = FormeOnde()
        self.bilan = Bilan()

        self.onglets = QtWidgets.QTabWidget()
        self.onglets.addTab(self.oscilloscope, "Oscilloscope de ligne")
        self.onglets.addTab(self.profil, "Profil décodé")
        self.onglets.addTab(self.vectorscope, "Vectorscope")
        self.onglets.addTab(self.spectre, "Spectre")
        self.onglets.addTab(self.forme_onde, "Forme d'onde")
        self.onglets.addTab(self.bilan, "Bilan")
        self.onglets.setMinimumHeight(260)

        vertical = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        vertical.addWidget(self.vues)
        vertical.addWidget(self.onglets)
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 2)

        horizontal = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        horizontal.addWidget(self.reglages)
        horizontal.addWidget(vertical)
        horizontal.setStretchFactor(0, 0)
        horizontal.setStretchFactor(1, 1)
        self.setCentralWidget(horizontal)

        self._construire_barre_outils()
        self._contexte_son()

        self._etat = QtWidgets.QLabel("Prêt")
        self._occupation = QtWidgets.QLabel("")
        self.statusBar().addWidget(self._etat, 1)
        self.statusBar().addPermanentWidget(self._occupation)

    def _contexte_son(self) -> None:
        """Transmet à l'onglet Son la norme et le bruit choisis côté image.

        Le bruit n'est pas dupliqué : il n'y a qu'un canal, et c'est le réglage
        de l'image qui en décide pour les deux voies. C'est précisément ce que
        l'onglet Son sert à montrer.
        """
        canal = self.panneau.parametres().canal
        self.onglet_son.definir_contexte(
            self.panneau.code_norme(), canal.rapport_signal_bruit
        )

    def _construire_barre_outils(self) -> None:
        barre = self.addToolBar("Source")
        barre.setMovable(False)
        barre.addWidget(QtWidgets.QLabel("  Mire de test  "))

        self.combo_mire = QtWidgets.QComboBox()
        for nom in mires.CATALOGUE:
            self.combo_mire.addItem(nom)
        self.combo_mire.setMinimumWidth(280)
        self.combo_mire.currentTextChanged.connect(self._charger_mire)
        barre.addWidget(self.combo_mire)

        barre.addSeparator()
        action_ouvrir = barre.addAction("Ouvrir une image…")
        action_ouvrir.triggered.connect(self._ouvrir_image)

        barre.addSeparator()
        action_comparer = barre.addAction("Comparer les trois normes")
        action_comparer.triggered.connect(self._comparer_normes)

        barre.addSeparator()
        self.action_animer = barre.addAction("Animer le fourmillement")
        self.action_animer.setCheckable(True)
        self.action_animer.toggled.connect(self._basculer_animation)

        self._animation = QtCore.QTimer(self)
        self._animation.setInterval(420)
        self._animation.timeout.connect(self._image_suivante)

    def _construire_menus(self) -> None:
        fichier = self.menuBar().addMenu("&Fichier")
        fichier.addAction("Ouvrir une image…", self._ouvrir_image, "Ctrl+O")
        fichier.addSeparator()
        fichier.addAction("Exporter l'image décodée…", self._exporter_decodee, "Ctrl+S")
        fichier.addAction("Exporter la comparaison des trois normes…", self._exporter_comparaison)
        fichier.addSeparator()
        fichier.addAction("Quitter", self.close, "Ctrl+Q")

        affichage = self.menuBar().addMenu("&Affichage")
        affichage.addAction("Recadrer les vues", self.vues.recadrer, "Ctrl+0")
        affichage.addAction(
            "Revenir aux valeurs normatives", self.panneau.reinitialiser
        )

        aide = self.menuBar().addMenu("&Aide")
        aide.addAction("À propos", self._a_propos)

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def _charger_mire(self, nom: str) -> None:
        supplements = {}
        if nom in ("Balayage de fréquence (cross-color)", "Multiburst"):
            supplements["norme"] = self.panneau.code_norme()
        self._source = mires.obtenir_mire(nom, *TAILLE_MIRE, **supplements)
        self._nom_source = nom
        self._demander_rendu()

    def _ouvrir_image(self) -> None:
        chemin, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Ouvrir une image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
        )
        if not chemin:
            return
        try:
            self._source = charger_image(chemin)
        except Exception as erreur:  # pragma: no cover - interaction
            QtWidgets.QMessageBox.critical(self, "Lecture impossible", str(erreur))
            return
        self._nom_source = Path(chemin).name
        self._demander_rendu()

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def _demander_rendu(self) -> None:
        self._temporisation.start()

    def _rendre(self) -> None:
        params = self.panneau.parametres()
        params.taille_sortie = None    # géométrie native de la norme
        self._moteur.demander(self._source, params)

    @QtCore.pyqtSlot(object)
    def _sur_resultat(self, resultat: Resultat) -> None:
        self._dernier_resultat = resultat
        self.vues.afficher(resultat.source, resultat.finale)
        for instrument in (
            self.oscilloscope, self.profil, self.vectorscope,
            self.spectre, self.forme_onde, self.bilan,
        ):
            instrument.mettre_a_jour(resultat)

        bilan = mesures.evaluer(resultat)
        norme = resultat.norme
        self._etat.setText(
            f"{self._nom_source} → {norme.code} · "
            f"{norme.lignes_actives}×{norme.echantillons_par_ligne} à "
            f"{norme.f_echantillonnage / 1e6:.2f} MHz · "
            f"ΔE moyen {bilan.delta_e_moyen:.2f} · "
            f"teinte {bilan.erreur_teinte_moyenne:+.1f}° · "
            f"saturation {bilan.erreur_saturation_relative:+.1%} · "
            f"écrêtage {bilan.taux_ecretage:.1%}"
        )

    @QtCore.pyqtSlot(str)
    def _sur_erreur(self, message: str) -> None:
        self._etat.setText("Erreur de rendu")
        QtWidgets.QMessageBox.critical(self, "Erreur de rendu", message)

    @QtCore.pyqtSlot(bool)
    def _sur_occupation(self, occupe: bool) -> None:
        self._occupation.setText("calcul en cours…" if occupe else "")

    def _sur_ligne(self, ligne: int) -> None:
        self.oscilloscope.definir_ligne(ligne)
        self.profil.definir_ligne(ligne)

    # ------------------------------------------------------------------
    # Animation du fourmillement
    # ------------------------------------------------------------------

    def _basculer_animation(self, actif: bool) -> None:
        if actif:
            self._animation.start()
        else:
            self._animation.stop()

    def _image_suivante(self) -> None:
        """Avance d'une image : la phase de sous-porteuse change, les points rampent."""
        self.panneau.spin_image.setValue((self.panneau.spin_image.value() + 1) % 4)

    # ------------------------------------------------------------------
    # Comparaison des trois normes
    # ------------------------------------------------------------------

    def _rendre_les_trois(self) -> dict[str, Resultat]:
        base = self.panneau.parametres()
        resultats = {}
        for code in ("NTSC-M", "PAL-BG", "SECAM-L"):
            import copy

            params = copy.deepcopy(base)
            params.norme = code
            params.taille_sortie = self._source.shape[:2]
            # Les bandes passantes reviennent aux valeurs normatives de chaque
            # norme : comparer PAL et NTSC avec la même bande de luminance
            # n'aurait aucun sens.
            params.encodage.bande_y = None
            params.encodage.bande_c1 = None
            params.encodage.bande_c2 = None
            params.decodage.bande_chroma = None
            if code.startswith("SECAM") and params.decodage.separateur not in (
                "notch", "parfait"
            ):
                params.decodage.separateur = "notch"
            resultats[code] = encoder_decoder(self._source, params)
        return resultats

    def _comparer_normes(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            resultats = self._rendre_les_trois()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        FenetreComparaison(resultats, self._source, self).show()

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def _exporter_decodee(self) -> None:
        if self._dernier_resultat is None:
            return
        chemin, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter l'image décodée",
            f"{self._dernier_resultat.norme.code}.png", "Images PNG (*.png)",
        )
        if chemin:
            enregistrer_image(self._dernier_resultat.finale, chemin)
            self._etat.setText(f"Exporté : {chemin}")

    def _exporter_comparaison(self) -> None:
        chemin, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter la comparaison", "comparaison.png", "Images PNG (*.png)"
        )
        if not chemin:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            resultats = self._rendre_les_trois()
            bandes = [self._source] + [r.finale for r in resultats.values()]
            hauteur = min(b.shape[0] for b in bandes)
            largeur = min(b.shape[1] for b in bandes)
            planche = np.concatenate([b[:hauteur, :largeur] for b in bandes], axis=1)
            enregistrer_image(planche, chemin)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._etat.setText(f"Exporté : {chemin}")

    # ------------------------------------------------------------------

    def _a_propos(self) -> None:
        QtWidgets.QMessageBox.about(
            self, "À propos",
            "<h3>Simulateur de codage couleur NTSC / PAL / SECAM</h3>"
            "<p>Le signal composite est reconstruit ligne par ligne, échantillonné "
            "à quatre fois la sous-porteuse, puis décodé comme le ferait un "
            "téléviseur.</p>"
            "<p>Les artefacts visibles — points rampants, moirages irisés, barres "
            "de Hanover, « feu » SECAM — ne sont jamais dessinés : ils émergent "
            "du calcul.</p>"
            "<p>Le cours complet se trouve dans <code>docs/cours.md</code>.</p>",
        )

    def closeEvent(self, evenement):  # noqa: N802 - API Qt
        self._animation.stop()
        self._moteur.arreter()
        super().closeEvent(evenement)


class FenetreComparaison(QtWidgets.QDialog):
    """Les trois normes côte à côte, à réglages de canal identiques."""

    def __init__(self, resultats: dict[str, Resultat], source: np.ndarray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Les trois normes, dans les mêmes conditions")
        self.resize(1500, 760)
        self._resultats = resultats

        grille = QtWidgets.QGridLayout(self)
        grille.setSpacing(6)

        colonnes = [("Original", source, None)] + [
            (NORMES[code].nom, resultat.finale, resultat)
            for code, resultat in resultats.items()
        ]

        for colonne, (titre, image, resultat) in enumerate(colonnes):
            etiquette = QtWidgets.QLabel(titre)
            etiquette.setAlignment(QtCore.Qt.AlignCenter)
            police = etiquette.font()
            police.setBold(True)
            etiquette.setFont(police)
            grille.addWidget(etiquette, 0, colonne)

            vue = QtWidgets.QLabel()
            vue.setAlignment(QtCore.Qt.AlignCenter)
            vue.setPixmap(self._pixmap(image))
            vue.setMinimumSize(200, 150)
            grille.addWidget(vue, 1, colonne)

            texte = QtWidgets.QLabel(
                self._legende(resultat) if resultat is not None else "référence"
            )
            texte.setStyleSheet("font-family: Consolas; font-size: 11px;")
            texte.setAlignment(QtCore.Qt.AlignTop)
            grille.addWidget(texte, 2, colonne)

        grille.setRowStretch(1, 1)

    @staticmethod
    def _pixmap(image: np.ndarray) -> QtGui.QPixmap:
        donnees = np.ascontiguousarray(
            (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        )
        hauteur, largeur, _ = donnees.shape
        qimage = QtGui.QImage(
            donnees.data, largeur, hauteur, 3 * largeur, QtGui.QImage.Format_RGB888
        ).copy()
        return QtGui.QPixmap.fromImage(qimage).scaled(
            360, 320, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )

    @staticmethod
    def _legende(resultat: Resultat) -> str:
        bilan = mesures.evaluer(resultat)
        norme = resultat.norme
        return (
            f"ΔE moyen      {bilan.delta_e_moyen:6.2f}\n"
            f"ΔE médian     {bilan.delta_e_median:6.2f}\n"
            f"teinte        {bilan.erreur_teinte_moyenne:+6.2f}°\n"
            f"saturation    {bilan.erreur_saturation_relative:+6.1%}\n"
            f"écrêtage      {bilan.taux_ecretage:6.1%}\n"
            f"chroma H      {bilan.resolution_chroma_h:6.0f} pts\n"
            f"chroma V      {bilan.resolution_chroma_v:6.0f} lignes\n"
            f"bande Y       {norme.bande_y / 1e6:6.1f} MHz"
        )


def lancer(argv=None) -> int:
    application = QtWidgets.QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName("Simulateur NTSC/PAL/SECAM")
    fenetre = FenetrePrincipale()
    fenetre.show()
    return application.exec_()


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(lancer())
