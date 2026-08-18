"""
Fenêtre d'Arty : six opérateurs à gauche, la géométrie qu'ils dessinent à droite.

L'outil n'a qu'un but : rendre visible le lien entre un rapport de fréquences et
un motif. On règle une pile d'opérateurs comme sur un DX7, on l'injecte dans
l'onde du composite, et l'on regarde ce que le décodeur du téléviseur en fait.

L'encadré « ce que cela va donner » est le cœur pédagogique : il prédit le motif
de chaque opérateur AVANT de le tracer, à partir du seul rapport `f / f_ligne`.
Quand la prédiction et l'image concordent, on a compris quelque chose.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from gui.widgets_base import Curseur, Groupe, note
from tvcolor import mires
from tvcolor.constantes import NORMES, obtenir_norme

from .dx7 import ALGORITHMES, Enveloppe, Operateur, Voix
from .injection import ParametresArty, motif, rendre

FORMATS_IMAGE = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"

ENVELOPPES = {
    "plate": ("Plate — le même son de haut en bas", Enveloppe.plate()),
    "attaque": (
        "Attaque — fort en haut, éteint en bas",
        Enveloppe((1.0, 0.55, 0.25, 0.0), (0.001, 0.004, 0.008, 0.007)),
    ),
    "montee": (
        "Montée — rien en haut, plein en bas",
        Enveloppe((0.0, 0.15, 0.6, 1.0), (0.002, 0.006, 0.006, 0.006)),
    ),
    "bande": (
        "Bande — une seule zone dans la hauteur",
        Enveloppe((0.0, 1.0, 0.0, 0.0), (0.006, 0.003, 0.003, 0.008)),
    ),
    "cloche": (
        "Cloche — deux passages",
        Enveloppe((0.9, 0.1, 0.9, 0.0), (0.003, 0.005, 0.005, 0.007)),
    ),
}


class FenetreArty(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arty — écrire du son dans l'onde de l'image")
        self.resize(1420, 900)
        self.setAcceptDrops(True)

        self._silencieux = False
        self._image = None
        self._resultat = None

        self._construire()

        # Un rendu complet coûte près d'une seconde : on ne le relance qu'une
        # fois le curseur reposé, sans quoi l'interface colle aux doigts.
        self._attente = QtCore.QTimer(self)
        self._attente.setSingleShot(True)
        self._attente.setInterval(180)
        self._attente.timeout.connect(self._rendre)

        self._silencieux = False
        self._planifier()

    # ------------------------------------------------------------------

    def _construire(self) -> None:
        self._construire_barre()

        self.vue = QtWidgets.QLabel()
        self.vue.setAlignment(QtCore.Qt.AlignCenter)
        self.vue.setMinimumSize(560, 420)
        self.vue.setStyleSheet("background: #111;")

        onglets = QtWidgets.QTabWidget()
        onglets.addTab(self._enveloppe_vue(), "Image")
        onglets.addTab(self._construire_instruments(), "L'onde injectée")

        separation = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        separation.addWidget(onglets)
        separation.addWidget(self._construire_panneau())
        separation.setStretchFactor(0, 1)
        separation.setSizes([900, 500])
        self.setCentralWidget(separation)

        self._etat = QtWidgets.QLabel("")
        self.statusBar().addWidget(self._etat, 1)

    def _enveloppe_vue(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(widget)
        colonne.setContentsMargins(6, 6, 6, 6)
        colonne.addWidget(self.vue, 1)
        return widget

    def _construire_barre(self) -> None:
        barre = self.addToolBar("Source")
        barre.setMovable(False)
        barre.addAction("Ouvrir une image…", self._ouvrir).setShortcut("Ctrl+O")
        barre.addSeparator()

        barre.addWidget(QtWidgets.QLabel("  Mire  "))
        self.combo_mire = QtWidgets.QComboBox()
        for nom in mires.CATALOGUE:
            self.combo_mire.addItem(nom, nom)
        self.combo_mire.setCurrentIndex(self.combo_mire.findData("Mire TDF (France)"))
        self.combo_mire.currentIndexChanged.connect(self._sur_mire)
        self.combo_mire.setMinimumWidth(220)
        barre.addWidget(self.combo_mire)

        barre.addWidget(QtWidgets.QLabel("   Norme  "))
        self.combo_norme = QtWidgets.QComboBox()
        for code, norme in NORMES.items():
            self.combo_norme.addItem(norme.nom, code)
        self.combo_norme.setCurrentIndex(self.combo_norme.findData("PAL-BG"))
        self.combo_norme.currentIndexChanged.connect(self._planifier)
        barre.addWidget(self.combo_norme)

        barre.addSeparator()
        self.case_fin = QtWidgets.QCheckBox("Rendu fin (576 lignes)")
        self.case_fin.toggled.connect(self._planifier)
        barre.addWidget(self.case_fin)

        barre.addSeparator()
        barre.addAction("Exporter l'image…", self._exporter_image).setShortcut("Ctrl+E")
        barre.addAction("Exporter la voix…", self._exporter_voix)

    def _construire_instruments(self) -> QtWidgets.QWidget:
        import pyqtgraph as pg

        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        onglets = QtWidgets.QTabWidget()

        self.trace_onde = pg.PlotWidget()
        self.trace_onde.setLabel("bottom", "temps dans la ligne", units="s")
        self.trace_onde.setLabel("left", "niveau composite")
        self.trace_onde.showGrid(x=True, y=True, alpha=0.3)
        self.courbe_propre = self.trace_onde.plot(pen=pg.mkPen("#718096", width=1.2))
        self.courbe_sale = self.trace_onde.plot(pen=pg.mkPen("#c53030", width=1.4))
        onglets.addTab(self.trace_onde, "Une ligne du composite")

        self.trace_spectre = pg.PlotWidget()
        self.trace_spectre.setLabel("bottom", "fréquence", units="Hz")
        self.trace_spectre.setLabel("left", "niveau", units="dB")
        self.trace_spectre.setLogMode(x=True, y=False)
        self.trace_spectre.showGrid(x=True, y=True, alpha=0.3)
        self.courbe_spectre = self.trace_spectre.plot(pen=pg.mkPen("#2b6cb0", width=1.4))
        self.repere_sc = pg.InfiniteLine(angle=90, pen=pg.mkPen("#dd6b20", width=1.4))
        self.trace_spectre.addItem(self.repere_sc)
        onglets.addTab(self.trace_spectre, "Spectre de l'onde injectée")

        return onglets

    # ------------------------------------------------------------------

    @staticmethod
    def _page():
        defilement = QtWidgets.QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        contenu = QtWidgets.QWidget()
        colonne = QtWidgets.QVBoxLayout(contenu)
        colonne.setContentsMargins(8, 8, 8, 8)
        colonne.setSpacing(8)
        defilement.setWidget(contenu)
        return defilement, colonne

    def _construire_panneau(self) -> QtWidgets.QWidget:
        defilement, colonne = self._page()

        groupe = Groupe("La voix")
        self.combo_algo = QtWidgets.QComboBox()
        for code, algo in ALGORITHMES.items():
            self.combo_algo.addItem(algo.nom, code)
        self.combo_algo.setCurrentIndex(self.combo_algo.findData("chaine"))
        self.combo_algo.currentIndexChanged.connect(self._planifier)
        groupe.ajouter(QtWidgets.QLabel("Agencement"))
        groupe.ajouter(self.combo_algo)
        self.etiquette_algo = note("")
        groupe.ajouter(self.etiquette_algo)

        self.curseur_fondamentale = Curseur(
            "Fondamentale", 0.5, 300.0, 8.0, 0.25, " × f_ligne", 2
        )
        self.curseur_index = Curseur("Index de modulation", 0.0, 12.0, 3.0, 0.1, "", 1)
        self.curseur_niveau = Curseur("Niveau injecté", 0.0, 0.6, 0.10, 0.005, "", 3)
        self.curseur_instant = Curseur("Trame", 0.0, 24.0, 0.0, 1.0, "", 0)
        for curseur in (self.curseur_fondamentale, self.curseur_index,
                        self.curseur_niveau, self.curseur_instant):
            curseur.valeur_changee.connect(self._planifier)
            groupe.ajouter(curseur)
        colonne.addWidget(groupe)

        groupe = Groupe("Ce que cela va donner")
        self.etiquette_motif = note("")
        groupe.ajouter(self.etiquette_motif)
        colonne.addWidget(groupe)

        groupe = Groupe("Les six opérateurs")
        grille = QtWidgets.QGridLayout()
        grille.setContentsMargins(0, 0, 0, 0)
        grille.setHorizontalSpacing(6)
        for col, titre in enumerate(("", "rapport", "niveau", "désaccord", "rétro.", "enveloppe")):
            etiquette = QtWidgets.QLabel(titre)
            etiquette.setStyleSheet("font-size: 10px; color: #666;")
            grille.addWidget(etiquette, 0, col)

        self.operateurs = []
        for rang in range(6):
            grille.addWidget(QtWidgets.QLabel(f"OP{rang + 1}"), rang + 1, 0)

            rapport = QtWidgets.QDoubleSpinBox()
            rapport.setRange(0.05, 32.0)
            rapport.setSingleStep(0.5)
            rapport.setDecimals(2)
            rapport.setValue([1.0, 2.0, 1.0, 3.0, 1.0, 1.0][rang])

            niveau = QtWidgets.QDoubleSpinBox()
            niveau.setRange(0.0, 2.0)
            niveau.setSingleStep(0.05)
            niveau.setDecimals(2)
            niveau.setValue(1.0)

            detune = QtWidgets.QDoubleSpinBox()
            detune.setRange(-2000.0, 2000.0)
            detune.setSingleStep(10.0)
            detune.setDecimals(0)
            detune.setSuffix(" Hz")
            detune.setValue(0.0)

            retro = QtWidgets.QDoubleSpinBox()
            retro.setRange(0.0, 8.0)
            retro.setSingleStep(0.5)
            retro.setDecimals(1)
            retro.setValue(0.0)

            enveloppe = QtWidgets.QComboBox()
            for code, (libelle, _) in ENVELOPPES.items():
                enveloppe.addItem(libelle.split(" — ")[0], code)

            for widget in (rapport, niveau, detune, retro):
                widget.valueChanged.connect(self._planifier)
                widget.setMaximumWidth(88)
            enveloppe.currentIndexChanged.connect(self._planifier)
            enveloppe.setMaximumWidth(96)

            for col, widget in enumerate((rapport, niveau, detune, retro, enveloppe), start=1):
                grille.addWidget(widget, rang + 1, col)
            self.operateurs.append((rapport, niveau, detune, retro, enveloppe))

        conteneur = QtWidgets.QWidget()
        conteneur.setLayout(grille)
        groupe.ajouter(conteneur)
        groupe.ajouter(note(
            "Le RAPPORT est un multiple de la fondamentale : entier, le son est "
            "harmonique et les barres régulières ; fractionnaire, le spectre "
            "devient inharmonique et le motif ne se referme plus.\n\n"
            "Le NIVEAU d'un modulateur est l'indice β : au-delà de β + 1 "
            "harmoniques, les raies s'effondrent — c'est la fonction de Bessel "
            "qui le veut. Le monter, c'est passer d'une barre franche à une "
            "texture fine.\n\n"
            "Le DÉSACCORD fait battre deux opérateurs voisins, et le battement "
            "devient un glissement du motif d'une ligne à l'autre. La RÉTROACTION "
            "transforme la sinusoïde en dent de scie, puis en bruit.\n\n"
            "L'ENVELOPPE se lit du HAUT VERS LE BAS de l'image : une trame dure "
            "vingt millisecondes, et l'enveloppe les parcourt."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("Le décodeur")
        self.combo_separateur = QtWidgets.QComboBox()
        for code, libelle in (("peigne", "Filtre en peigne"),
                              ("notch", "Réjecteur de sous-porteuse"),
                              ("parfait", "Séparation parfaite")):
            self.combo_separateur.addItem(libelle, code)
        self.combo_separateur.currentIndexChanged.connect(self._planifier)
        groupe.ajouter(self.combo_separateur)
        groupe.ajouter(note(
            "C'est lui qui décide de ce que l'intrus devient. Une onde qui tombe "
            "près de la sous-porteuse est indiscernable de la chrominance : le "
            "décodeur choisit la couleur, et le son se met à teinter l'image. "
            "Changer de séparateur change donc le résultat — le peigne rejette "
            "ce qui alterne d'une ligne à l'autre, le réjecteur ce qui est à la "
            "bonne fréquence."
        ))
        colonne.addWidget(groupe)

        groupe = Groupe("Ce que cet outil ne fait pas")
        groupe.ajouter(note(
            "IL NE TOUCHE PAS AU SON. La voie audio d'un téléviseur a sa propre "
            "porteuse, plusieurs mégahertz plus haut ; ce qu'on injecte ici va "
            "dans le composite vidéo, exactement là où un brouilleur agirait. Un "
            "test le vérifie en comparant la sortie audio avec et sans "
            "perturbation, qui doivent être identiques au bit près.\n\n"
            "Rien n'est dessiné non plus. La géométrie qu'on voit est DÉDUITE du "
            "rapport entre la fréquence du son et celle du balayage, par la même "
            "chaîne de décodage que le reste du simulateur."
        ))
        colonne.addWidget(groupe)

        colonne.addStretch(1)
        return defilement

    # ------------------------------------------------------------------

    def _voix(self) -> Voix:
        norme = obtenir_norme(self.combo_norme.currentData())
        fondamentale = self.curseur_fondamentale.valeur() * norme.f_ligne
        operateurs = []
        for rapport, niveau, detune, retro, enveloppe in self.operateurs:
            code = enveloppe.currentData()
            operateurs.append(Operateur(
                rapport=rapport.value(),
                niveau=niveau.value(),
                detune=detune.value(),
                retroaction=retro.value(),
                enveloppe=ENVELOPPES[code][1],
            ))
        return Voix(
            fondamentale=fondamentale,
            algorithme=self.combo_algo.currentData(),
            operateurs=tuple(operateurs),
            index=self.curseur_index.valeur(),
        )

    def _parametres(self) -> ParametresArty:
        norme = obtenir_norme(self.combo_norme.currentData())
        hauteur = norme.lignes_actives if self.case_fin.isChecked() else 288
        largeur = int(round(hauteur * 4 / 3))
        return ParametresArty(
            norme=self.combo_norme.currentData(),
            voix=self._voix(),
            niveau=self.curseur_niveau.valeur(),
            instant=self.curseur_instant.valeur() / norme.f_trame * 2.0,
            mire=self.combo_mire.currentData(),
            image=self._image,
            taille=(hauteur, largeur),
            separateur=self.combo_separateur.currentData(),
        )

    def _planifier(self, *_args) -> None:
        if self._silencieux:
            return
        self._decrire()
        self._attente.start()

    def _decrire(self) -> None:
        norme = obtenir_norme(self.combo_norme.currentData())
        voix = self._voix()
        algo = ALGORITHMES[self.combo_algo.currentData()]
        self.etiquette_algo.setText(algo.caractere)

        lignes = [
            f"Fondamentale : {voix.fondamentale / 1e3:.1f} kHz, soit "
            f"{voix.fondamentale / norme.f_ligne:.2f} fois la fréquence ligne.",
            "",
        ]
        for rang, porteuse in enumerate(algo.porteuses):
            if not porteuse:
                continue
            frequence = voix.operateurs[rang].frequence(voix.fondamentale)
            m = motif(frequence, norme)
            au_dela = " — au-delà de la bande vidéo, invisible" if m["au_dela_de_la_bande"] else ""
            lignes.append(
                f"OP{rang + 1} · {frequence / 1e6:.3f} MHz · "
                f"{m['cycles_par_ligne']:.1f} barres, avance "
                f"{m['avance_par_ligne']:.0f}° par ligne\n    {m['allure']}{au_dela}"
            )
        self.etiquette_motif.setText("\n".join(lignes))

    def _rendre(self) -> None:
        params = self._parametres()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self._resultat = rendre(params)
        except Exception as erreur:            # pragma: no cover - garde-fou
            self._etat.setText(f"Rendu impossible : {erreur}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self._afficher(self._resultat.finale)
        self._tracer(params)
        norme = params.resolue()
        self._etat.setText(
            f"{self._resultat.finale.shape[1]} × {self._resultat.finale.shape[0]} · "
            f"{norme.nom} · composite à {norme.f_echantillonnage / 1e6:.2f} MHz · "
            f"{norme.echantillons_ligne_totale} points par ligne"
        )

    def _afficher(self, image: np.ndarray) -> None:
        octets = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        octets = np.ascontiguousarray(octets)
        hauteur, largeur = octets.shape[:2]
        qimage = QtGui.QImage(
            octets.data, largeur, hauteur, 3 * largeur, QtGui.QImage.Format_RGB888
        )
        pixmap = QtGui.QPixmap.fromImage(qimage.copy())
        self.vue.setPixmap(pixmap.scaled(
            self.vue.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        ))

    def _tracer(self, params: ParametresArty) -> None:
        from .injection import base_de_temps

        norme = params.resolue()
        resultat = self._resultat
        ligne = resultat.composite_emis.shape[0] // 2
        temps = base_de_temps(norme, resultat.composite_emis.shape[0], params.instant)

        onde = params.niveau * params.voix.rendre(temps[ligne : ligne + 1])[0]
        propre = resultat.composite_emis[ligne] - onde

        axe = temps[ligne] - temps[ligne, 0]
        fin = min(axe.size, int(0.15 * axe.size))
        self.courbe_propre.setData(axe[:fin], propre[:fin])
        self.courbe_sale.setData(axe[:fin], resultat.composite_emis[ligne][:fin])

        entier = params.voix.rendre(temps).reshape(-1)
        fenetre = np.hanning(entier.size)
        spectre = np.abs(np.fft.rfft(entier * fenetre)) / (entier.size / 4)
        frequences = np.fft.rfftfreq(entier.size, 1.0 / norme.f_echantillonnage)
        garde = (frequences > 1e4) & (frequences < norme.f_echantillonnage / 2)
        self.courbe_spectre.setData(
            frequences[garde], 20.0 * np.log10(np.maximum(spectre[garde], 1e-6))
        )
        self.repere_sc.setValue(np.log10(norme.f_sc))

    # ------------------------------------------------------------------

    def _sur_mire(self, *_args) -> None:
        self._image = None
        self._planifier()

    def _ouvrir(self) -> None:
        chemin, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Ouvrir une image", "", FORMATS_IMAGE
        )
        if chemin:
            self._charger(chemin)

    def _charger(self, chemin: str) -> None:
        from PIL import Image

        try:
            with Image.open(chemin) as fichier:
                image = np.asarray(fichier.convert("RGB"), dtype=np.float64) / 255.0
        except Exception as erreur:
            QtWidgets.QMessageBox.critical(self, "Lecture impossible", str(erreur))
            return
        self._image = image
        self._planifier()

    def _exporter_image(self) -> None:
        if self._resultat is None:
            return
        chemin, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter l'image", "arty.png", "PNG (*.png)"
        )
        if not chemin:
            return
        from PIL import Image

        octets = (np.clip(self._resultat.finale, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        Image.fromarray(octets).save(chemin)
        self._etat.setText(f"Exporté : {Path(chemin).name}")

    def _exporter_voix(self) -> None:
        """Écrit la même voix en WAV, transposée dans l'audible.

        Ce n'est pas le son du téléviseur — celui-là n'est pas touché — mais la
        voix qu'on vient d'injecter, rejouée à une fondamentale audible. Les
        rapports, les indices et les enveloppes sont les mêmes : c'est
        littéralement le son qu'on regarde.
        """
        chemin, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter la voix", "arty.wav", "WAV (*.wav)"
        )
        if not chemin:
            return

        from radio.services import F_AUDIO
        from radio.source_audio import ecrire_wav

        voix = self._voix()
        norme = obtenir_norme(self.combo_norme.currentData())
        # On transpose la fondamentale de la fréquence ligne vers 110 Hz : les
        # rapports entre opérateurs, eux, ne changent pas.
        audible = replace(voix, fondamentale=voix.fondamentale / norme.f_ligne * 110.0)
        temps = np.arange(int(3.0 * F_AUDIO)) / F_AUDIO
        onde = audible.rendre(temps)
        crete = float(np.max(np.abs(onde)))
        if crete > 0.0:
            onde = onde / crete * 0.8
        ecrire_wav(chemin, onde)
        self._etat.setText(
            f"Voix exportée : {Path(chemin).name} — fondamentale transposée à 110 Hz"
        )

    # ------------------------------------------------------------------

    def resizeEvent(self, evenement):        # noqa: N802 - API Qt
        super().resizeEvent(evenement)
        if self._resultat is not None:
            self._afficher(self._resultat.finale)

    def dragEnterEvent(self, evenement):     # noqa: N802 - API Qt
        if evenement.mimeData().hasUrls():
            evenement.acceptProposedAction()

    def dropEvent(self, evenement):          # noqa: N802 - API Qt
        for url in evenement.mimeData().urls():
            chemin = url.toLocalFile()
            if chemin:
                self._charger(chemin)
                break


def principal(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    application = QtWidgets.QApplication(argv)
    application.setApplicationName("Arty")
    fenetre = FenetreArty()
    fenetre.show()
    for argument in argv[1:]:
        if Path(argument).exists():
            fenetre._charger(argument)
            break
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(principal())
