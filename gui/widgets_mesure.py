"""
Les instruments — oscilloscope, vectorscope, analyseur de spectre, bilan.

C'est ici que le simulateur cesse d'être un filtre à images pour devenir un
banc de mesure. Chaque widget expose une méthode `mettre_a_jour(resultat)` et
ne calcule rien tant qu'il n'est pas visible : les transformées de Fourier
d'une trame entière ne sont pas gratuites.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets

from tvcolor import matrices as mx
from tvcolor import mesures
from tvcolor.pipeline import Resultat

COULEURS_BARRES = {
    "jaune": "#c8c800", "cyan": "#00c8c8", "vert": "#00c800",
    "magenta": "#c800c8", "rouge": "#c80000", "bleu": "#0000c8",
}


class _Instrument(QtWidgets.QWidget):
    """Base commune : garde le dernier résultat, ne recalcule que si visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resultat: Resultat | None = None
        self._a_jour = False

    def mettre_a_jour(self, resultat: Resultat) -> None:
        self._resultat = resultat
        self._a_jour = False
        if self.isVisible():
            self.rafraichir()

    def showEvent(self, evenement):  # noqa: N802 - API Qt
        super().showEvent(evenement)
        if not self._a_jour:
            self.rafraichir()

    def rafraichir(self) -> None:
        if self._resultat is None:
            return
        self._dessiner(self._resultat)
        self._a_jour = True

    def _dessiner(self, resultat: Resultat) -> None:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Oscilloscope de ligne
# ---------------------------------------------------------------------------

class Oscilloscope(_Instrument):
    """Le signal composite d'une ligne, tel qu'il circulerait dans un câble.

    La vue la plus instructive de l'outil : on y voit la marche d'escalier de
    la luminance, la sous-porteuse qui l'enfourche, son amplitude qui suit la
    saturation et sa phase qui suit la teinte.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ligne = 0

        self._graphe = pg.PlotWidget()
        self._graphe.setBackground("#101014")
        self._graphe.showGrid(x=True, y=True, alpha=0.25)
        self._graphe.setLabel("bottom", "temps dans la ligne", units="µs")
        self._graphe.setLabel("left", "niveau", units="IRE")
        self._graphe.addLegend(offset=(-10, 10))

        self._courbe_composite = self._graphe.plot(
            pen=pg.mkPen("#7fd4ff", width=1), name="composite émis"
        )
        self._courbe_recu = self._graphe.plot(
            pen=pg.mkPen("#ff9f4a", width=1), name="composite reçu"
        )
        self._courbe_luma = self._graphe.plot(
            pen=pg.mkPen("#ffffff", width=2), name="luminance décodée"
        )

        for niveau, couleur, etiquette in (
            (0.0, "#666a72", "suppression / 0 IRE"),
            (100.0, "#666a72", "blanc / 100 IRE"),
        ):
            trait = pg.InfiniteLine(
                pos=niveau, angle=0, pen=pg.mkPen(couleur, style=QtCore.Qt.DashLine)
            )
            self._graphe.addItem(trait)
            texte = pg.TextItem(etiquette, color="#666a72", anchor=(0, 1))
            texte.setPos(0, niveau)
            self._graphe.addItem(texte)

        self._zone_active = pg.LinearRegionItem(
            movable=False, brush=pg.mkBrush(120, 200, 255, 18)
        )
        self._zone_active.setZValue(-10)
        self._graphe.addItem(self._zone_active)

        self._case_recu = QtWidgets.QCheckBox("Afficher le signal reçu")
        self._case_recu.setChecked(True)
        self._case_recu.toggled.connect(self.rafraichir)
        self._etiquette = QtWidgets.QLabel()

        # Une ligne entière contient près de 300 cycles de sous-porteuse : à
        # cette échelle on ne voit qu'une bande pleine. Le bouton de zoom
        # ramène la vue à quelques microsecondes, où l'on distingue enfin la
        # sinusoïde, son amplitude qui suit la saturation et sa phase qui
        # suit la teinte.
        self._bouton_zoom = QtWidgets.QPushButton("Voir quelques cycles")
        self._bouton_zoom.clicked.connect(self._zoomer)
        self._bouton_ligne = QtWidgets.QPushButton("Ligne entière")
        self._bouton_ligne.clicked.connect(self._degrouper)

        barre = QtWidgets.QHBoxLayout()
        barre.setContentsMargins(4, 2, 4, 2)
        barre.addWidget(self._etiquette, 1)
        barre.addWidget(self._bouton_zoom)
        barre.addWidget(self._bouton_ligne)
        barre.addWidget(self._case_recu)

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addLayout(barre)
        disposition.addWidget(self._graphe, 1)

    def definir_ligne(self, ligne: int) -> None:
        self._ligne = int(ligne)
        self._a_jour = False
        if self.isVisible():
            self.rafraichir()

    def _zoomer(self) -> None:
        if self._resultat is None:
            return
        norme = self._resultat.norme
        milieu = 0.5 * norme.duree_ligne * 1e6
        largeur = 6.0 / (norme.f_sc / 1e6)     # environ six cycles
        self._graphe.setXRange(milieu - largeur, milieu + largeur)

    def _degrouper(self) -> None:
        if self._resultat is None:
            return
        self._graphe.setXRange(0.0, self._resultat.norme.duree_ligne * 1e6)
        self._graphe.enableAutoRange(axis="y")

    def _dessiner(self, resultat: Resultat) -> None:
        norme = resultat.norme
        signal = resultat.signal
        n_lignes = signal.composite.shape[0]
        ligne = int(np.clip(self._ligne, 0, n_lignes - 1))

        emis = signal.composite[ligne]
        recu = resultat.composite_recu[ligne]
        temps = np.linspace(0.0, norme.duree_ligne * 1e6, emis.size)

        self._courbe_composite.setData(temps, emis * 100.0)
        if self._case_recu.isChecked():
            self._courbe_recu.setData(temps, recu * 100.0)
        else:
            self._courbe_recu.setData([], [])

        luma = resultat.decodee.luma[ligne]
        debut = signal.marge / emis.size * norme.duree_ligne * 1e6
        fin = (signal.marge + signal.largeur_active) / emis.size * norme.duree_ligne * 1e6
        self._courbe_luma.setData(np.linspace(debut, fin, luma.size), luma * 100.0)
        self._zone_active.setRegion((debut, fin))

        cycles = norme.f_sc / norme.f_ligne
        self._etiquette.setText(
            f"Ligne {ligne} sur {n_lignes} · {norme.code} · "
            f"sous-porteuse {norme.f_sc / 1e6:.4f} MHz "
            f"({cycles:.4f} cycles par ligne, soit "
            f"{norme.avance_phase_par_ligne_deg:.1f}° de rotation d'une ligne à l'autre)"
        )


# ---------------------------------------------------------------------------
# Vectorscope
# ---------------------------------------------------------------------------

class Vectorscope(_Instrument):
    """Le plan (U, V) : le module donne la saturation, l'argument la teinte.

    Les six petites cases sont les cibles d'une mire de barres à 75 %. Un
    nuage tourné signale une erreur de teinte, un nuage rétréci une perte de
    saturation, un nuage étalé du bruit.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._graphe = pg.PlotWidget()
        self._graphe.setBackground("#101014")
        self._graphe.setAspectLocked(True)
        self._graphe.setLabel("bottom", "U   (B'−Y')")
        self._graphe.setLabel("left", "V   (R'−Y')")
        self._graphe.setXRange(-0.7, 0.7)
        self._graphe.setYRange(-0.7, 0.7)

        self._tracer_graticule()

        self._nuage = pg.ScatterPlotItem(
            size=2, pen=None, brush=pg.mkBrush(140, 230, 255, 70)
        )
        self._graphe.addItem(self._nuage)

        self._case_source = QtWidgets.QCheckBox("Superposer l'image d'origine")
        self._case_source.toggled.connect(self.rafraichir)
        self._nuage_source = pg.ScatterPlotItem(
            size=2, pen=None, brush=pg.mkBrush(255, 170, 90, 60)
        )
        self._graphe.addItem(self._nuage_source)

        barre = QtWidgets.QHBoxLayout()
        barre.setContentsMargins(4, 2, 4, 2)
        barre.addWidget(self._case_source)
        barre.addStretch(1)

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addLayout(barre)
        disposition.addWidget(self._graphe, 1)

    def _tracer_graticule(self) -> None:
        for rayon in (0.2, 0.4, 0.6):
            cercle = pg.QtWidgets.QGraphicsEllipseItem(
                -rayon, -rayon, 2 * rayon, 2 * rayon
            )
            cercle.setPen(pg.mkPen("#2c3038"))
            self._graphe.addItem(cercle)
        for angle in range(0, 360, 45):
            radian = np.deg2rad(angle)
            self._graphe.plot(
                [0, 0.68 * np.cos(radian)], [0, 0.68 * np.sin(radian)],
                pen=pg.mkPen("#22262c"),
            )

        # Cibles des barres de couleur à 75 %.
        for nom, (u, v) in mesures.cibles_vectorscope(0.75).items():
            cible = pg.QtWidgets.QGraphicsRectItem(u - 0.022, v - 0.022, 0.044, 0.044)
            cible.setPen(pg.mkPen(COULEURS_BARRES[nom], width=1))
            self._graphe.addItem(cible)
            texte = pg.TextItem(nom, color=COULEURS_BARRES[nom], anchor=(0.5, -0.4))
            texte.setPos(u, v)
            self._graphe.addItem(texte)

        # Axe du burst : la référence de phase, à 180°.
        self._graphe.plot([0, -0.68], [0, 0], pen=pg.mkPen("#556", width=2))
        burst = pg.TextItem("axe du burst (180°)", color="#667", anchor=(0, 0.5))
        burst.setPos(-0.66, 0.04)
        self._graphe.addItem(burst)

    def _dessiner(self, resultat: Resultat) -> None:
        u, v = mesures.uv_de_image(resultat.finale)
        u, v = mesures.nuage_vectorscope(u, v, 30000)
        self._nuage.setData(u, v)

        if self._case_source.isChecked():
            us, vs = mesures.uv_de_image(resultat.source)
            us, vs = mesures.nuage_vectorscope(us, vs, 30000)
            self._nuage_source.setData(us, vs)
        else:
            self._nuage_source.setData([], [])


# ---------------------------------------------------------------------------
# Analyseur de spectre
# ---------------------------------------------------------------------------

class Spectre(_Instrument):
    """Le spectre du signal composite, gradué en multiples de la fréquence ligne.

    C'est ici que se démontre l'entrelacement spectral. Le spectre d'une image
    balayée n'occupe pas la bande de façon continue : il se concentre en un
    peigne de raies espacées de f_H, avec de larges creux entre elles. En
    plaçant la sous-porteuse sur un multiple demi-entier de f_H, on loge la
    chrominance exactement dans ces creux — et deux signaux tiennent dans une
    bande prévue pour un seul.

    Zoomez autour de la sous-porteuse : les raies de chrominance tombent
    précisément au milieu des raies de luminance.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._graphe = pg.PlotWidget()
        self._graphe.setBackground("#101014")
        self._graphe.showGrid(x=True, y=True, alpha=0.25)
        self._graphe.setLabel("bottom", "fréquence, en multiples de f_H")
        self._graphe.setLabel("left", "niveau", units="dB")
        self._courbe = self._graphe.plot(pen=pg.mkPen("#7fd4ff", width=1))

        self._repere_sc = pg.InfiniteLine(
            angle=90, pen=pg.mkPen("#ff6b6b", style=QtCore.Qt.DashLine)
        )
        self._graphe.addItem(self._repere_sc)
        self._texte_sc = pg.TextItem("sous-porteuse", color="#ff6b6b", anchor=(0, 1))
        self._graphe.addItem(self._texte_sc)

        self._combo = QtWidgets.QComboBox()
        self._combo.addItem("Trame entière — montre les peignes", "raster")
        self._combo.addItem("Une seule ligne", "ligne")
        self._combo.currentIndexChanged.connect(self.rafraichir)

        self._bouton_zoom = QtWidgets.QPushButton("Zoomer sur la sous-porteuse")
        self._bouton_zoom.clicked.connect(self._zoomer)

        barre = QtWidgets.QHBoxLayout()
        barre.setContentsMargins(4, 2, 4, 2)
        barre.addWidget(self._combo, 1)
        barre.addWidget(self._bouton_zoom)

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addLayout(barre)
        disposition.addWidget(self._graphe, 1)
        self._cycles_sc = 0.0

    def _zoomer(self) -> None:
        if self._cycles_sc:
            self._graphe.setXRange(self._cycles_sc - 6, self._cycles_sc + 6)
            self._graphe.setYRange(-90, 0)

    def _dessiner(self, resultat: Resultat) -> None:
        norme = resultat.norme
        self._cycles_sc = norme.f_sc / norme.f_ligne

        if self._combo.currentData() == "raster":
            x, y = mesures.spectre_raster(
                resultat.composite_recu, norme, f_max=1.15 * norme.bande_y
            )
            self._graphe.setLabel("bottom", "fréquence, en multiples de f_H")
        else:
            ligne = resultat.composite_recu.shape[0] // 2
            f, y = mesures.spectre_ligne(
                resultat.composite_recu[ligne], norme.f_echantillonnage
            )
            garde = f <= 1.15 * norme.bande_y
            x, y = f[garde] / norme.f_ligne, y[garde]
            self._graphe.setLabel("bottom", "fréquence, en multiples de f_H")

        self._courbe.setData(x, y)
        self._repere_sc.setPos(self._cycles_sc)
        self._texte_sc.setPos(self._cycles_sc, 0)


# ---------------------------------------------------------------------------
# Moniteur de forme d'onde
# ---------------------------------------------------------------------------

class FormeOnde(_Instrument):
    """Histogramme vertical des niveaux de luminance, colonne par colonne."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._graphe = pg.PlotWidget()
        self._graphe.setBackground("#101014")
        self._graphe.setLabel("left", "niveau", units="IRE")
        self._graphe.setLabel("bottom", "position horizontale")
        self._graphe.hideAxis("bottom")
        self._element = pg.ImageItem(axisOrder="row-major")
        self._element.setLookupTable(self._palette())
        self._graphe.addItem(self._element)

        for niveau in (0.0, 100.0):
            self._graphe.addItem(
                pg.InfiniteLine(
                    pos=niveau, angle=0,
                    pen=pg.mkPen("#888", style=QtCore.Qt.DashLine),
                )
            )

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addWidget(self._graphe)

    @staticmethod
    def _palette() -> np.ndarray:
        t = np.linspace(0.0, 1.0, 256)
        return np.stack(
            [30 + 100 * t, 40 + 200 * t**0.7, 60 + 195 * t**0.5], axis=1
        ).astype(np.ubyte)

    def _dessiner(self, resultat: Resultat) -> None:
        image = mesures.forme_onde(resultat.finale)
        # L'image couvre des niveaux de -20 à +120 IRE ; on la positionne dans
        # le repère du graphe pour que l'axe soit directement lisible.
        self._element.setImage(image, autoLevels=False, levels=(0.0, 1.0))
        self._element.setRect(QtCore.QRectF(0.0, -20.0, image.shape[1], 140.0))
        self._graphe.setYRange(-20.0, 120.0)
        self._graphe.setXRange(0, image.shape[1])


# ---------------------------------------------------------------------------
# Bilan chiffré
# ---------------------------------------------------------------------------

class Bilan(_Instrument):
    """Ce que la chaîne a coûté à l'image, en chiffres."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._texte = QtWidgets.QTextBrowser()
        self._texte.setOpenExternalLinks(False)
        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addWidget(self._texte)

    def _dessiner(self, resultat: Resultat) -> None:
        bilan = mesures.evaluer(resultat)
        norme = resultat.norme
        luminance = mesures.bilan_luminance(resultat.source, norme.gamma_affichage)
        colores = mesures.uv_de_image(resultat.source)
        masque = np.hypot(*colores) > 0.05
        fraction = (
            float(np.mean(luminance["fraction_portee"][masque])) if masque.any() else 1.0
        )

        def ligne(intitule, valeur, commentaire=""):
            gris = f"<span style='color:#8a8f98'>{commentaire}</span>" if commentaire else ""
            return (
                f"<tr><td style='padding-right:16px'>{intitule}</td>"
                f"<td style='text-align:right'><b>{valeur}</b></td>"
                f"<td style='padding-left:14px'>{gris}</td></tr>"
            )

        html = [
            "<style>body{font-family:Segoe UI,sans-serif;font-size:12px}"
            "h3{margin:14px 0 4px 0;font-size:12px;color:#7fd4ff}"
            "td{padding:1px 0}</style>",
            f"<h3>{norme.nom}</h3><table>",
            ligne("ΔE*ab moyen", f"{bilan.delta_e_moyen:.2f}",
                  "1 = seuil de perception, 3 = évident"),
            ligne("ΔE*ab médian", f"{bilan.delta_e_median:.2f}"),
            ligne("ΔE*ab 95ᵉ centile", f"{bilan.delta_e_p95:.2f}",
                  "essentiellement les contours"),
            ligne("ΔE*ab maximal", f"{bilan.delta_e_max:.2f}"),
            "</table><h3>Teinte et saturation</h3><table>",
            ligne("Erreur de teinte moyenne", f"{bilan.erreur_teinte_moyenne:+.2f}°",
                  "sur les pixels colorés"),
            ligne("Erreur de teinte maximale", f"{bilan.erreur_teinte_max:.1f}°"),
            ligne("Écart de saturation", f"{bilan.erreur_saturation_relative:+.1%}"),
            ligne("Pixels écrêtés hors gamut", f"{bilan.taux_ecretage:.1%}",
                  "l'écrêtage déplace la teinte, il ne fait pas que désaturer"),
            "</table><h3>Résolution</h3><table>",
            ligne("Luminance, horizontale", f"{bilan.resolution_luma_h:.0f} points/ligne"),
            ligne("Chrominance, horizontale", f"{bilan.resolution_chroma_h:.0f} points/ligne"),
            ligne("Chrominance, verticale", f"{bilan.resolution_chroma_v:.0f} lignes",
                  "divisée par deux par la ligne à retard PAL et par le séquentiel SECAM"),
            "</table><h3>Non-constant-luminance</h3><table>",
            ligne("Luminance portée par la voie Y", f"{fraction:.1%}",
                  "sur les zones colorées ; le reste voyage dans la chrominance, "
                  "six fois moins large"),
            "</table>",
        ]
        self._texte.setHtml("".join(html))


# ---------------------------------------------------------------------------
# Profil de ligne décodé
# ---------------------------------------------------------------------------

class ProfilLigne(_Instrument):
    """Luminance et chrominance décodées le long de la ligne sélectionnée.

    Fait voir d'un coup d'œil la différence de bande passante : la luminance
    saute d'une valeur à l'autre, la chrominance met dix fois plus longtemps
    à la rejoindre.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ligne = 0
        self._graphe = pg.PlotWidget()
        self._graphe.setBackground("#101014")
        self._graphe.showGrid(x=True, y=True, alpha=0.25)
        self._graphe.setLabel("bottom", "colonne")
        self._courbes = {
            "luma": self._graphe.plot(pen=pg.mkPen("#ffffff", width=2)),
            "c1": self._graphe.plot(pen=pg.mkPen("#7fd4ff", width=1)),
            "c2": self._graphe.plot(pen=pg.mkPen("#ff9f4a", width=1)),
            "luma_src": self._graphe.plot(
                pen=pg.mkPen("#888888", width=1, style=QtCore.Qt.DashLine)
            ),
        }
        self._legende = QtWidgets.QLabel()
        self._legende.setContentsMargins(6, 2, 6, 2)

        disposition = QtWidgets.QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addWidget(self._legende)
        disposition.addWidget(self._graphe, 1)

    def definir_ligne(self, ligne: int) -> None:
        self._ligne = int(ligne)
        self._a_jour = False
        if self.isVisible():
            self.rafraichir()

    def _dessiner(self, resultat: Resultat) -> None:
        decodee = resultat.decodee
        n = decodee.luma.shape[0]
        ligne = int(np.clip(self._ligne, 0, n - 1))
        x = np.arange(decodee.luma.shape[1])

        self._courbes["luma"].setData(x, decodee.luma[ligne])
        self._courbes["c1"].setData(x, decodee.chroma1[ligne])
        self._courbes["c2"].setData(x, decodee.chroma2[ligne])

        source = resultat.signal.partie_active(resultat.signal.ref_luma)
        self._courbes["luma_src"].setData(x, source[min(ligne, source.shape[0] - 1)])

        noms = {
            "NTSC": ("U", "V"), "PAL": ("U", "V"), "SECAM": ("D'B", "D'R"),
        }[resultat.norme.famille]
        self._legende.setText(
            f"Ligne {ligne} &nbsp;·&nbsp; "
            "<span style='color:#ffffff'>━</span> Y' décodée &nbsp; "
            "<span style='color:#888888'>┄</span> Y' d'origine &nbsp; "
            f"<span style='color:#7fd4ff'>━</span> {noms[0]} &nbsp; "
            f"<span style='color:#ff9f4a'>━</span> {noms[1]}"
        )
