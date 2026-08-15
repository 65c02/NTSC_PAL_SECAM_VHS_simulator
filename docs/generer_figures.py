"""
Génère toutes les figures du cours à partir de la bibliothèque de simulation.

Aucune illustration n'est dessinée à la main : chaque courbe, chaque spectre,
chaque image d'artefact est une sortie réelle de `tvcolor`. Si la simulation
change, les figures changent avec elle — et si une figure ne montre pas ce
que le texte annonce, c'est le texte ou la simulation qu'il faut corriger.

Usage :

    python docs/generer_figures.py [--dossier docs/figures] [--seulement 06,11]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tvcolor import colorimetrie as col  # noqa: E402
from tvcolor import filtres, matrices as mx, mesures, mires, porteuse  # noqa: E402
from tvcolor.canal import ParametresCanal  # noqa: E402
from tvcolor.constantes import (  # noqa: E402
    F_SC_SECAM_B,
    F_SC_SECAM_R,
    SECAM_F0,
    obtenir_norme,
)
from tvcolor.decodeur import ParametresDecodage  # noqa: E402
from tvcolor.encodeur import ParametresEncodage  # noqa: E402
from tvcolor.pipeline import Parametres, encoder_decoder  # noqa: E402

plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": 140,
        "savefig.bbox": "tight",
        "font.size": 9,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": ":",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "legend.framealpha": 0.9,
        "legend.fontsize": 8,
    }
)

BLEU, ORANGE, VERT, ROUGE, VIOLET = "#2b6cb0", "#dd6b20", "#2f855a", "#c53030", "#6b46c1"
GRIS = "#718096"

_FIGURES: dict[str, callable] = {}


def figure(numero: str, titre: str):
    """Décorateur d'enregistrement d'une figure."""

    def decorateur(fonction):
        fonction.numero, fonction.titre = numero, titre
        _FIGURES[numero] = fonction
        return fonction

    return decorateur


def _enregistrer(fig, dossier: Path, numero: str, nom: str) -> Path:
    chemin = dossier / f"{numero}_{nom}.png"
    fig.savefig(chemin)
    plt.close(fig)
    return chemin


def _image(ax, image, titre=""):
    ax.imshow(np.clip(image, 0.0, 1.0), interpolation="nearest", aspect="equal")
    ax.set_title(titre)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)


# ===========================================================================
# 1. Colorimétrie
# ===========================================================================

def _fonctions_colorimetriques(lam):
    """Approximation analytique des fonctions x̄, ȳ, z̄ de la CIE 1931 (2°).

    Ajustement par gaussiennes asymétriques de Wyman, Sperling & Gyulassy
    (Journal of Computer Graphics Techniques, 2013). Précision de l'ordre du
    pour-cent, largement suffisante pour tracer un diagramme de chromaticité,
    et cela évite d'embarquer une table de plusieurs centaines de valeurs.
    """

    def g(x, mu, s1, s2):
        s = np.where(x < mu, s1, s2)
        return np.exp(-0.5 * ((x - mu) / s) ** 2)

    x = 1.056 * g(lam, 599.8, 37.9, 31.0) + 0.362 * g(lam, 442.0, 16.0, 26.7) \
        - 0.065 * g(lam, 501.1, 20.4, 26.2)
    y = 0.821 * g(lam, 568.8, 46.9, 40.5) + 0.286 * g(lam, 530.9, 16.3, 31.1)
    z = 1.217 * g(lam, 437.0, 11.8, 36.0) + 0.681 * g(lam, 459.0, 26.0, 13.8)
    return x, y, z


@figure("01", "Les gamuts des trois systèmes")
def figure_01_gamuts(dossier: Path) -> Path:
    lam = np.linspace(380.0, 700.0, 400)
    x, y, z = _fonctions_colorimetriques(lam)
    somme = x + y + z
    locus = np.stack([x / somme, y / somme], axis=1)

    fig, ax = plt.subplots(figsize=(6.4, 6.0))
    ax.add_patch(Polygon(locus, closed=True, facecolor="#f2f2f5", edgecolor="#aab", lw=1))
    ax.plot(locus[:, 0], locus[:, 1], color="#889", lw=1)

    styles = {
        "ntsc1953": (ROUGE, "NTSC 1953 (jamais réalisé)", "-"),
        "smpte-c": (ORANGE, "SMPTE-C (tubes NTSC réels)", "--"),
        "ebu": (BLEU, "EBU — PAL et SECAM", "-"),
        "bt709": (VERT, "BT.709 / sRGB", ":"),
    }
    for cle, (couleur, libelle, style) in styles.items():
        p = col.PRIMAIRES[cle]
        sommets = np.array([p.rouge, p.vert, p.bleu, p.rouge])
        ax.plot(sommets[:, 0], sommets[:, 1], style, color=couleur, lw=1.8, label=libelle)
        ax.plot(*p.blanc, "o", color=couleur, ms=4)

    ax.set_xlim(0.0, 0.75)
    ax.set_ylim(0.0, 0.85)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title("Primaires : ce que la norme promettait, ce que les tubes ont donné")
    ax.legend(loc="upper right")
    ax.set_aspect("equal")
    return _enregistrer(fig, dossier, "01", "gamuts")


@figure("02", "La non-constant-luminance")
def figure_02_non_constant_luminance(dossier: Path) -> Path:
    teintes = np.linspace(0.0, 1.0, 361)
    image = mires._hsv_vers_rgb(teintes[None, :], np.ones((1, 361)), np.ones((1, 361)))

    fig, axes = plt.subplots(2, 1, figsize=(7.6, 5.4), height_ratios=[3, 1])
    for gamma, couleur, libelle in (
        (2.2, ORANGE, "γ = 2,2 (NTSC)"),
        (2.8, BLEU, "γ = 2,8 (PAL/SECAM)"),
    ):
        bilan = mesures.bilan_luminance(image, gamma)
        axes[0].plot(
            teintes * 360, 100.0 * bilan["fraction_portee"][0],
            color=couleur, lw=2, label=libelle,
        )

    axes[0].axhline(100.0, color=GRIS, ls="--", lw=1)
    axes[0].set_ylabel("part de la luminance\nportée par Y'   (%)")
    axes[0].set_xlim(0, 360)
    axes[0].set_ylim(0, 110)
    axes[0].set_title(
        "Sur une couleur saturée, la voie luminance ne transporte presque rien"
    )
    axes[0].legend(loc="lower right")
    for angle, nom in ((0, "rouge"), (60, "jaune"), (120, "vert"),
                       (180, "cyan"), (240, "bleu"), (300, "magenta")):
        axes[0].axvline(angle, color=GRIS, lw=0.6, alpha=0.5)
        axes[0].annotate(nom, (angle, 104), fontsize=7.5, ha="center", color=GRIS)

    axes[1].imshow(np.repeat(image, 40, axis=0), aspect="auto",
                   extent=(0, 360, 0, 1), interpolation="nearest")
    axes[1].set_yticks([])
    axes[1].set_xlabel("teinte (degrés)")
    axes[1].grid(False)
    return _enregistrer(fig, dossier, "02", "non_constant_luminance")


@figure("03", "L'excursion du signal composite")
def figure_03_excursion(dossier: Path) -> Path:
    couleurs = list(zip(mires.NOMS_BARRES, mires.ORDRE_BARRES))
    fig, ax = plt.subplots(figsize=(7.6, 4.2))

    for rang, (nom, rgb) in enumerate(couleurs):
        y, u, v = mx.rgb_vers_yuv(np.array(rgb, dtype=float))
        amplitude = float(np.hypot(u, v))
        ax.vlines(rang, y - amplitude, y + amplitude, color=BLEU, lw=7, alpha=0.45)
        ax.plot(rang, y, "o", color="#1a202c", ms=5, zorder=3)
        ax.annotate(f"{y:.3f}", (rang, y), textcoords="offset points",
                    xytext=(9, -3), fontsize=7.5)

    ax.axhline(4 / 3, color=ROUGE, ls="--", lw=1.4)
    ax.axhline(-1 / 3, color=ROUGE, ls="--", lw=1.4)
    ax.axhline(1.0, color=GRIS, ls=":", lw=1)
    ax.axhline(0.0, color=GRIS, ls=":", lw=1)
    ax.annotate("+4/3 — plafond de l'émetteur", (7.4, 4 / 3), ha="right",
                va="bottom", color=ROUGE, fontsize=8)
    ax.annotate("−1/3 — plancher, au-delà commencent les synchros",
                (7.4, -1 / 3), ha="right", va="top", color=ROUGE, fontsize=8)
    ax.annotate("blanc", (-0.4, 1.0), va="bottom", color=GRIS, fontsize=8)
    ax.annotate("noir", (-0.4, 0.0), va="top", color=GRIS, fontsize=8)

    ax.set_xticks(range(len(couleurs)))
    ax.set_xticklabels([nom for nom, _ in couleurs])
    ax.set_ylabel("niveau du composite")
    ax.set_title(
        "Pourquoi 0,492 et 0,877 : les couleurs saturées touchent pile les bornes"
    )
    ax.set_ylim(-0.55, 1.55)
    return _enregistrer(fig, dossier, "03", "excursion")


@figure("04", "Les axes I et Q du NTSC")
def figure_04_axes_iq(dossier: Path) -> Path:
    fig, ax = plt.subplots(figsize=(6.2, 6.0))
    theta = np.linspace(0, 2 * np.pi, 400)
    for rayon in (0.2, 0.4, 0.6):
        ax.plot(rayon * np.cos(theta), rayon * np.sin(theta), color="#e2e8f0", lw=1)

    ax.annotate("", (0.7, 0), (-0.7, 0), arrowprops=dict(arrowstyle="<->", color=GRIS))
    ax.annotate("", (0, 0.7), (0, -0.7), arrowprops=dict(arrowstyle="<->", color=GRIS))
    ax.text(0.71, 0.02, "U", color=GRIS)
    ax.text(0.02, 0.71, "V", color=GRIS)

    angle = np.deg2rad(33.0)
    axe_i = np.array([-np.sin(angle), np.cos(angle)])
    axe_q = np.array([np.cos(angle), np.sin(angle)])
    for axe, couleur, nom, bande in (
        (axe_i, ORANGE, "I", "1,3 MHz"),
        (axe_q, VIOLET, "Q", "0,4 MHz"),
    ):
        ax.plot([-0.7 * axe[0], 0.7 * axe[0]], [-0.7 * axe[1], 0.7 * axe[1]],
                color=couleur, lw=2)
        ax.annotate(f"{nom}  ({bande})", 0.72 * axe, color=couleur, fontweight="bold")

    for nom, (u, v) in mesures.cibles_vectorscope(1.0).items():
        ax.plot([0, u], [0, v], color="#cbd5e0", lw=1, zorder=0)
        ax.plot(u, v, "o", ms=7, color=dict(
            jaune="#c8c800", cyan="#00b0b0", vert="#00a000",
            magenta="#b000b0", rouge="#c00000", bleu="#0000c0")[nom])
        ax.annotate(nom, (u, v), textcoords="offset points", xytext=(6, 5), fontsize=8)

    ax.set_aspect("equal")
    ax.set_xlim(-0.85, 0.85)
    ax.set_ylim(-0.85, 0.85)
    ax.set_title("Les axes I/Q : 33° de rotation, et trois fois moins de bande sur Q")
    ax.grid(False)
    return _enregistrer(fig, dossier, "04", "axes_iq")


# ===========================================================================
# 2. L'entrelacement spectral
# ===========================================================================

@figure("05", "L'entrelacement spectral")
def figure_05_entrelacement(dossier: Path) -> Path:
    resultat = encoder_decoder(
        mires.barres_couleur(288, 384), Parametres(norme="NTSC-M")
    )
    norme = resultat.norme
    f, db = mesures.spectre_raster(resultat.composite_emis, norme, f_max=4.5e6)

    fig, axes = plt.subplots(2, 1, figsize=(8.4, 6.4))

    axes[0].plot(f, db, color=BLEU, lw=0.7)
    axes[0].axvline(227.5, color=ROUGE, ls="--", lw=1.2)
    axes[0].annotate("sous-porteuse\n227,5 · f_H", (227.5, -4), color=ROUGE,
                     ha="center", va="top", fontsize=8)
    axes[0].set_xlim(0, 290)
    axes[0].set_ylim(-100, 4)
    axes[0].set_xlabel("fréquence, en multiples de f_H")
    axes[0].set_ylabel("niveau (dB)")
    axes[0].set_title("Spectre complet du signal composite NTSC")

    zone = (f > 224.0) & (f < 231.0)
    axes[1].plot(f[zone], db[zone], color=BLEU, lw=1.1)
    for entier in range(224, 232):
        axes[1].axvline(entier, color=VERT, lw=1.0, alpha=0.7)
        axes[1].axvline(entier + 0.5, color=ORANGE, ls="--", lw=1.0, alpha=0.8)
    axes[1].set_xlim(224, 231)
    axes[1].set_ylim(-100, 4)
    axes[1].set_xlabel("fréquence, en multiples de f_H")
    axes[1].set_ylabel("niveau (dB)")
    axes[1].set_title(
        "Zoom : les raies de chrominance (traits orange, demi-entiers) tombent "
        "exactement entre celles de la luminance (traits verts, entiers)"
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "05", "entrelacement_spectral")


@figure("06", "Le signal composite d'une ligne")
def figure_06_signal_ligne(dossier: Path) -> Path:
    fig, axes = plt.subplots(3, 2, figsize=(11.5, 7.4), width_ratios=[3, 1])

    for rang, code in enumerate(("NTSC-M", "PAL-BG", "SECAM-L")):
        resultat = encoder_decoder(
            mires.barres_couleur(288, 384), Parametres(norme=code)
        )
        norme = resultat.norme
        ligne = norme.lignes_actives // 2
        signal = resultat.composite_emis[ligne]
        temps = np.linspace(0.0, norme.duree_ligne * 1e6, signal.size)

        axes[rang, 0].plot(temps, signal * 100.0, color=BLEU, lw=0.5)
        luma = resultat.signal.ref_luma[ligne]
        axes[rang, 0].plot(temps, luma * 100.0, color="#1a202c", lw=1.4)
        axes[rang, 0].axhline(0, color=GRIS, ls=":", lw=1)
        axes[rang, 0].axhline(100, color=GRIS, ls=":", lw=1)
        axes[rang, 0].set_ylabel(f"{norme.code}\nniveau (IRE)")
        axes[rang, 0].set_ylim(-45, 145)
        if rang == 0:
            axes[rang, 0].set_title(
                "Une ligne de barres de couleur : la luminance en escalier, "
                "la sous-porteuse par-dessus"
            )

        # Zoom sur quelques cycles, au milieu de la barre cyan.
        centre = int(signal.size * 0.35)
        largeur = int(round(6.0 * norme.f_echantillonnage / norme.f_sc))
        tranche = slice(centre - largeur, centre + largeur)
        axes[rang, 1].plot(temps[tranche], signal[tranche] * 100.0, color=BLEU, lw=1.2)
        axes[rang, 1].plot(temps[tranche], luma[tranche] * 100.0, color="#1a202c", lw=1.4)
        axes[rang, 1].set_ylim(-45, 145)
        if rang == 0:
            axes[rang, 1].set_title("douze cycles de sous-porteuse")

    axes[2, 0].set_xlabel("temps dans la ligne (µs)")
    axes[2, 1].set_xlabel("µs")
    fig.tight_layout()
    return _enregistrer(fig, dossier, "06", "signal_composite")


# ===========================================================================
# 3. L'erreur de phase et les trois réponses
# ===========================================================================

@figure("07", "Erreur de teinte selon la phase différentielle")
def figure_07_erreur_teinte(dossier: Path) -> Path:
    mire = mires.barres_couleur(288, 384)
    phases = np.arange(0.0, 61.0, 7.5)

    def mesurer(code, phase, ligne_a_retard=True):
        params = Parametres(
            norme=code,
            canal=ParametresCanal(phase_differentielle=float(phase)),
            decodage=ParametresDecodage(ligne_a_retard=ligne_a_retard),
        )
        if code.startswith("SECAM"):
            params.decodage.separateur = "notch"
        resultat = encoder_decoder(mire, params)
        u, v = resultat.decodee.chroma1, resultat.decodee.chroma2
        if resultat.norme.famille == "SECAM":
            u, v = mx.drdb_vers_uv(v, u)
        largeur = u.shape[1]
        zone = (slice(80, -80), slice(int(largeur * 0.66), int(largeur * 0.70)))
        uu, vv = u[zone].mean(), v[zone].mean()
        lignes = np.rad2deg(
            np.arctan2(v[zone].mean(axis=1), u[zone].mean(axis=1))
        )
        return (
            np.rad2deg(np.arctan2(vv, uu)),
            float(np.hypot(uu, vv)),
            float(np.abs(np.diff(lignes)).mean()),
        )

    # Plusieurs courbes se superposent exactement — c'est précisément le
    # résultat qu'on veut montrer. On les trace donc en traits larges puis de
    # plus en plus fins, avec des pointillés distincts, pour que celles du
    # dessous restent visibles sous celles du dessus.
    series = {}
    styles = (
        ("PAL-BG", "PAL-D (avec ligne à retard)", True, BLEU, "-", 4.5, 0.55),
        ("SECAM-L", "SECAM", True, VERT, (0, (6, 3)), 2.4, 1.0),
        ("PAL-BG", "PAL-S (sans ligne à retard)", False, ORANGE, (0, (1, 1.6)), 2.2, 1.0),
        ("NTSC-M", "NTSC", True, ROUGE, "-", 2.0, 1.0),
    )
    for code, libelle, retard, couleur, tiret, largeur, opacite in styles:
        valeurs = [mesurer(code, p, retard) for p in phases]
        reference = valeurs[0]
        series[libelle] = (
            couleur, tiret, largeur, opacite,
            [v[0] - reference[0] for v in valeurs],
            [v[1] / reference[1] for v in valeurs],
            [v[2] for v in valeurs],
        )

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 3.9))
    for libelle, (couleur, tiret, largeur, opacite, teinte, saturation, striage) in \
            series.items():
        options = dict(color=couleur, lw=largeur, alpha=opacite, ls=tiret)
        axes[0].plot(phases, teinte, label=libelle, **options)
        axes[1].plot(phases, saturation, **options)
        axes[2].plot(phases, striage, **options)

    axes[0].set_title("Erreur de teinte")
    axes[0].set_ylabel("degrés")
    axes[0].annotate(
        "PAL et SECAM restent à zéro,\nleurs trois courbes se superposent",
        (30, -1.2), fontsize=7.5, color=GRIS, ha="center", va="top",
    )
    axes[1].set_title("Saturation restituée")
    axes[1].set_ylabel("rapport à la référence")
    axes[1].annotate(
        "les deux variantes de PAL\nperdent la même saturation",
        (32, 0.9735), fontsize=7.5, color=GRIS, ha="center",
    )
    axes[2].set_title("Striage d'une ligne à l'autre\n(barres de Hanover)")
    axes[2].set_ylabel("degrés")
    for ax in axes:
        ax.set_xlabel("phase différentielle du canal (degrés)")
    axes[0].legend(loc="lower left", fontsize=7.5)
    fig.suptitle(
        "Le même canal dégradé, trois réponses : le NTSC tourne, "
        "le PAL pâlit, le SECAM ignore",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "07", "erreur_teinte")


@figure("08", "Vectorscope comparé")
def figure_08_vectorscope(dossier: Path) -> Path:
    mire = mires.barres_couleur(288, 384)
    canal = ParametresCanal(phase_differentielle=45.0)

    fig, axes = plt.subplots(1, 4, figsize=(13.0, 3.6))
    cas = [
        ("Référence (canal parfait)", "PAL-BG", None, True),
        ("NTSC, phase différentielle 45°", "NTSC-M", canal, True),
        ("PAL-D, même canal", "PAL-BG", canal, True),
        ("SECAM, même canal", "SECAM-L", canal, True),
    ]
    for ax, (titre, code, defaut, retard) in zip(axes, cas):
        params = Parametres(
            norme=code,
            canal=defaut or ParametresCanal(),
            decodage=ParametresDecodage(ligne_a_retard=retard),
        )
        if code.startswith("SECAM"):
            params.decodage.separateur = "notch"
        resultat = encoder_decoder(mire, params)
        u, v = mesures.uv_de_image(resultat.finale)
        u, v = mesures.nuage_vectorscope(u, v, 12000)
        ax.plot(u, v, ".", ms=1, color=BLEU, alpha=0.35)

        for nom, (cu, cv) in mesures.cibles_vectorscope(0.75).items():
            ax.plot(cu, cv, "s", ms=9, mfc="none", mec=ROUGE, mew=1.2)
            ax.annotate(nom, (cu, cv), textcoords="offset points",
                        xytext=(0, 9), fontsize=6.5, ha="center", color=ROUGE)

        for rayon in (0.2, 0.4, 0.6):
            theta = np.linspace(0, 2 * np.pi, 200)
            ax.plot(rayon * np.cos(theta), rayon * np.sin(theta),
                    color="#e2e8f0", lw=0.8)
        ax.set_aspect("equal")
        ax.set_xlim(-0.75, 0.75)
        ax.set_ylim(-0.75, 0.75)
        ax.set_title(titre, fontsize=8.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
    fig.tight_layout()
    return _enregistrer(fig, dossier, "08", "vectorscope")


@figure("09", "Les barres de Hanover")
def figure_09_hanover(dossier: Path) -> Path:
    mire = mires.barres_couleur(200, 320)
    canal = ParametresCanal(phase_differentielle=60.0)

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.4))
    cas = [
        ("PAL-D — la ligne à retard fait son travail", True, "PAL-BG"),
        ("PAL-S — sans ligne à retard : barres de Hanover", False, "PAL-BG"),
        ("NTSC — même canal : la teinte a tourné", True, "NTSC-M"),
    ]
    for ax, (titre, retard, code) in zip(axes, cas):
        resultat = encoder_decoder(
            mire,
            Parametres(
                norme=code, canal=canal,
                decodage=ParametresDecodage(ligne_a_retard=retard),
            ),
        )
        image = resultat.finale
        h, w = image.shape[:2]
        _image(ax, image[h // 3 : 2 * h // 3, int(w * 0.35) : int(w * 0.85)], titre)
    fig.tight_layout()
    return _enregistrer(fig, dossier, "09", "hanover")


# ===========================================================================
# 4. Les artefacts de séparation Y/C
# ===========================================================================

@figure("10", "Dot crawl : le peigne ne le supprime pas, il le déplace")
def figure_10_dot_crawl(dossier: Path) -> Path:
    mire = mires.piege_dot_crawl(288, 384)
    fig, axes = plt.subplots(2, 3, figsize=(11.0, 6.0))

    for colonne, (separateur, titre) in enumerate(
        (("notch", "Réjecteur de sous-porteuse"),
         ("peigne", "Filtre en peigne"),
         ("parfait", "Séparation parfaite (irréalisable)"))
    ):
        resultat = encoder_decoder(
            mire,
            Parametres(
                norme="NTSC-M",
                decodage=ParametresDecodage(separateur=separateur),
                taille_sortie=(480, 753),
            ),
        )
        image = resultat.finale
        _image(axes[0, colonne], image[45:145, 175:275], f"{titre}\ncontour vertical")
        _image(axes[1, colonne], image[10:60, 60:200], "contour horizontal")

    fig.suptitle(
        "Le réjecteur salit les contours verticaux, le peigne les nettoie mais "
        "salit les horizontaux",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "10", "dot_crawl")


@figure("11", "Le cross-color")
def figure_11_cross_color(dossier: Path) -> Path:
    norme = obtenir_norme("NTSC-M")
    mire = mires.balayage_frequentiel(200, 384, "NTSC-M", f_max=6.0e6)
    resultat = encoder_decoder(
        mire,
        Parametres(
            norme="NTSC-M",
            decodage=ParametresDecodage(separateur="notch"),
            taille_sortie=(200, 753),
        ),
    )

    fig, axes = plt.subplots(3, 1, figsize=(9.6, 6.2), height_ratios=[1, 1, 1.3])
    _image(axes[0], mire, "Mire d'entrée : strictement en noir et blanc, "
                          "fréquence croissante de 0 à 6 MHz")
    _image(axes[1], resultat.finale, "Après codage puis décodage NTSC")

    u, v = mesures.uv_de_image(resultat.finale)
    saturation = np.hypot(u, v).mean(axis=0)
    frequences = np.linspace(0.0, 6.0, saturation.size)
    axes[2].fill_between(frequences, saturation, color=BLEU, alpha=0.35)
    axes[2].plot(frequences, saturation, color=BLEU, lw=1.2)
    axes[2].axvline(norme.f_sc / 1e6, color=ROUGE, ls="--", lw=1.4)
    axes[2].annotate("sous-porteuse 3,58 MHz", (norme.f_sc / 1e6, saturation.max()),
                     color=ROUGE, ha="center", va="bottom", fontsize=8)
    axes[2].set_xlabel("fréquence spatiale de la mire (MHz)")
    axes[2].set_ylabel("saturation\nparasite")
    axes[2].set_xlim(0, 6)
    axes[2].set_title(
        "Le décodeur prend pour de la couleur tout détail de luminance proche "
        "de la sous-porteuse"
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "11", "cross_color")


# ===========================================================================
# 5. Bande passante et résolution
# ===========================================================================

@figure("12", "La chrominance bave, la luminance non")
def figure_12_bande_chroma(dossier: Path) -> Path:
    hauteur, largeur = 576, 921
    resultat = encoder_decoder(
        mires.barres_couleur(hauteur, largeur),
        Parametres(norme="PAL-BG", taille_sortie=(hauteur, largeur)),
    )
    norme = resultat.norme
    u, v = mesures.uv_de_image(resultat.finale)
    y = mx.luma(resultat.finale)
    ligne = hauteur // 2
    frontiere = largeur // 8
    fenetre = slice(frontiere - 40, frontiere + 60)
    echelle = (np.arange(fenetre.start, fenetre.stop) - frontiere) \
        / norme.f_echantillonnage * 1e6

    fig, axes = plt.subplots(2, 1, figsize=(8.6, 5.6), height_ratios=[1, 2])
    _image(axes[0], resultat.finale[ligne - 40 : ligne + 40, fenetre],
           "Transition blanc → jaune, agrandie")

    axes[1].plot(echelle, y[ligne, fenetre], color="#1a202c", lw=2,
                 label="luminance décodée (5,0 MHz)")
    axes[1].plot(echelle, u[ligne, fenetre], color=BLEU, lw=1.6,
                 label="U décodé (1,3 MHz)")
    axes[1].plot(echelle, v[ligne, fenetre], color=ORANGE, lw=1.6,
                 label="V décodé (1,3 MHz)")
    axes[1].axvline(0, color=GRIS, ls=":", lw=1)
    axes[1].set_xlabel("temps relatif à la transition (µs)")
    axes[1].set_title(
        "La luminance bascule en 70 ns, la chrominance met 270 ns : "
        "quatre fois plus, et cela se voit"
    )
    axes[1].legend(loc="center right")
    fig.tight_layout()
    return _enregistrer(fig, dossier, "12", "bande_chroma")


@figure("13", "La résolution chromatique verticale")
def figure_13_resolution_verticale(dossier: Path) -> Path:
    hauteur, largeur = 576, 768
    motif = np.zeros((hauteur, largeur, 3))
    for ligne in range(hauteur):
        motif[ligne] = (0.8, 0.1, 0.1) if (ligne // 2) % 2 == 0 else (0.1, 0.1, 0.8)

    fig, axes = plt.subplots(1, 4, figsize=(12.0, 3.4))
    _image(axes[0], motif[100:140, :120], "Motif d'entrée\n(2 lignes rouges, 2 bleues)")
    for ax, (code, retard, titre) in zip(
        axes[1:],
        (("NTSC-M", True, "NTSC — chroma pleine résolution verticale"),
         ("PAL-BG", True, "PAL-D — la ligne à retard moyenne deux lignes"),
         ("SECAM-L", True, "SECAM — le séquentiel impose la même perte")),
    ):
        params = Parametres(norme=code, taille_sortie=(hauteur, largeur),
                            decodage=ParametresDecodage(ligne_a_retard=retard))
        if code.startswith("SECAM"):
            params.decodage.separateur = "notch"
        resultat = encoder_decoder(motif, params)
        _image(ax, resultat.finale[100:140, :120], titre)
    fig.suptitle(
        "Le prix de la robustesse : PAL-D et SECAM divisent par deux la "
        "résolution chromatique verticale",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "13", "resolution_verticale")


# ===========================================================================
# 6. SECAM
# ===========================================================================

@figure("14", "Les préaccentuations SECAM")
def figure_14_preaccentuations(dossier: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 3.9))

    f = np.logspace(3.0, 6.3, 800)
    gain = 20.0 * np.log10(np.abs(filtres.reponse_preaccentuation_bf(f)))
    axes[0].semilogx(f, gain, color=BLEU, lw=2)
    axes[0].axhline(20 * np.log10(3.0), color=GRIS, ls="--", lw=1)
    axes[0].annotate("plafond : rapport 3, soit 9,5 dB", (1.2e6, 9.6),
                     fontsize=8, color=GRIS, va="bottom")
    axes[0].axvline(85e3, color=ROUGE, ls=":", lw=1.2)
    axes[0].annotate("f₁ = 85 kHz", (85e3, 1), color=ROUGE, fontsize=8, rotation=90,
                     va="bottom", ha="right")
    axes[0].set_xlabel("fréquence du signal de différence de couleur (Hz)")
    axes[0].set_ylabel("gain (dB)")
    axes[0].set_title("Préaccentuation basse fréquence, avant modulation")

    f = np.linspace(3.0e6, 5.6e6, 900)
    axes[1].plot(f / 1e6, 20.0 * np.log10(np.maximum(filtres.gain_cloche(f), 1e-6)),
                 color=BLEU, lw=2)
    for frequence, couleur, nom in (
        (F_SC_SECAM_B, VERT, "f_OB = 4,250 MHz"),
        (F_SC_SECAM_R, ORANGE, "f_OR = 4,406 MHz"),
        (SECAM_F0, ROUGE, "f₀ = 4,286 MHz"),
    ):
        axes[1].axvline(frequence / 1e6, color=couleur, ls=":", lw=1.2)
        axes[1].annotate(nom, (frequence / 1e6, -0.5), color=couleur, fontsize=7.5,
                         rotation=90, va="top", ha="right")
    axes[1].set_xlabel("fréquence instantanée de la sous-porteuse (MHz)")
    axes[1].set_ylabel("gain (dB)")
    axes[1].set_title(
        "Filtre « cloche » : minimum au repos, remontée aux fortes excursions"
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "14", "preaccentuations_secam")


@figure("15", "La modulation de fréquence SECAM")
def figure_15_fm_secam(dossier: Path) -> Path:
    norme = obtenir_norme("SECAM-L")
    resultat = encoder_decoder(
        mires.barres_couleur(288, 384), Parametres(norme="SECAM-L")
    )
    signal = resultat.signal
    ligne_bleue = norme.lignes_actives // 2
    if porteuse.secam_ligne_rouge(signal.indices)[ligne_bleue]:
        ligne_bleue += 1
    ligne_rouge = ligne_bleue + 1

    fig, axes = plt.subplots(3, 1, figsize=(9.4, 6.8))

    for ligne, couleur, nom, repos in (
        (ligne_bleue, BLEU, "ligne « bleue » — porte D'B", F_SC_SECAM_B),
        (ligne_rouge, ROUGE, "ligne « rouge » — porte D'R", F_SC_SECAM_R),
    ):
        chroma = signal.partie_active(signal.ref_chroma)[ligne]
        ecart = porteuse.demoduler_frequence(
            chroma[None, :], repos, norme.f_echantillonnage, filtres.passe_bas
        )[0]
        x = np.arange(chroma.size)
        axes[0].plot(x, (repos + ecart) / 1e6, color=couleur, lw=1.4, label=nom)
        axes[1].plot(x, np.abs(chroma), color=couleur, lw=0.6, alpha=0.8)

    axes[0].axhline(F_SC_SECAM_B / 1e6, color=BLEU, ls=":", lw=1)
    axes[0].axhline(F_SC_SECAM_R / 1e6, color=ROUGE, ls=":", lw=1)
    axes[0].set_ylim(3.55, 5.05)
    axes[0].set_ylabel("fréquence\ninstantanée (MHz)")
    axes[0].set_title(
        "En SECAM, la couleur est portée par la FRÉQUENCE : chaque palier "
        "correspond à une barre"
    )
    axes[0].annotate(
        "les pointes aux transitions sortent du cadre : ce sont les "
        "dépassements de la modulation de fréquence, bien réels",
        (0.5, 0.03), xycoords="axes fraction", fontsize=7.5, color=GRIS, ha="center",
    )
    axes[0].legend(loc="upper right", fontsize=8)

    axes[1].set_ylabel("amplitude de la\nsous-porteuse")
    axes[1].set_title(
        "L'amplitude ne porte aucune information — et surtout, elle ne "
        "s'annule JAMAIS, même sur le blanc et le noir"
    )

    ligne_pal = obtenir_norme("PAL-BG").lignes_actives // 2
    pal = encoder_decoder(mires.barres_couleur(288, 384), Parametres(norme="PAL-BG"))
    chroma_pal = pal.signal.partie_active(pal.signal.ref_chroma)[ligne_pal]
    axes[2].plot(np.abs(chroma_pal), color=VERT, lw=0.6)
    axes[2].set_ylabel("amplitude de la\nsous-porteuse")
    axes[2].set_xlabel("échantillon dans la ligne active")
    axes[2].set_title(
        "Pour comparaison, en PAL : c'est l'AMPLITUDE qui porte la saturation "
        "— d'où la vulnérabilité au gain, et la possibilité de faire un fondu"
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "15", "fm_secam")


@figure("16", "Le comportement au bruit")
def figure_16_bruit(dossier: Path) -> Path:
    mire = mires.barres_couleur(288, 384)
    fig, axes = plt.subplots(2, 3, figsize=(11.0, 5.6))

    for colonne, code in enumerate(("NTSC-M", "PAL-BG", "SECAM-L")):
        for rang, rapport in enumerate((34.0, 22.0)):
            params = Parametres(
                norme=code, canal=ParametresCanal(rapport_signal_bruit=rapport)
            )
            if code.startswith("SECAM"):
                params.decodage.separateur = "notch"
            resultat = encoder_decoder(mire, params)
            image = resultat.finale
            h, w = image.shape[:2]
            _image(
                axes[rang, colonne],
                image[h // 4 : 3 * h // 4, w // 8 : 7 * w // 8],
                f"{resultat.norme.code} — S/B {rapport:.0f} dB",
            )
    fig.suptitle(
        "Le bruit atteint la teinte en NTSC, surtout la saturation en PAL, "
        "et presque rien en SECAM tant que le discriminateur ne décroche pas",
        fontsize=10.5, fontweight="bold",
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "16", "bruit")


# ===========================================================================
# 7. Synthèse
# ===========================================================================

@figure("17", "Les trois normes côte à côte")
def figure_17_comparaison(dossier: Path) -> Path:
    mire = mires.roue_de_teintes(360, 360)
    fig, axes = plt.subplots(1, 4, figsize=(12.4, 3.6))
    _image(axes[0], mire, "Original")

    for ax, code in zip(axes[1:], ("NTSC-M", "PAL-BG", "SECAM-L")):
        params = Parametres(norme=code, taille_sortie=mire.shape[:2])
        if code.startswith("SECAM"):
            params.decodage.separateur = "notch"
        resultat = encoder_decoder(mire, params)
        bilan = mesures.evaluer(resultat)
        _image(
            ax, resultat.finale,
            f"{resultat.norme.code}\nΔE moyen {bilan.delta_e_moyen:.2f} · "
            f"teinte {bilan.erreur_teinte_moyenne:+.1f}°",
        )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "17", "comparaison")


@figure("18", "Ce que la chaîne coûte, en chiffres")
def figure_18_bilan(dossier: Path) -> Path:
    mire = mires.degrade_saturation(288, 384)
    codes = ("NTSC-M", "PAL-BG", "SECAM-L")
    bilans = {}
    for code in codes:
        params = Parametres(norme=code)
        if code.startswith("SECAM"):
            params.decodage.separateur = "notch"
        bilans[code] = mesures.evaluer(encoder_decoder(mire, params))

    fig, axes = plt.subplots(1, 3, figsize=(11.6, 3.6))
    x = np.arange(len(codes))
    couleurs = [ROUGE, BLEU, VERT]

    axes[0].bar(x, [bilans[c].delta_e_moyen for c in codes], color=couleurs, alpha=0.8)
    axes[0].set_title("ΔE*ab moyen")
    axes[0].set_ylabel("unités ΔE (1 = seuil de perception)")

    axes[1].bar(x, [bilans[c].resolution_chroma_h for c in codes],
                color=couleurs, alpha=0.8)
    axes[1].set_title("Résolution chroma horizontale")
    axes[1].set_ylabel("points par ligne")

    axes[2].bar(x, [bilans[c].resolution_chroma_v for c in codes],
                color=couleurs, alpha=0.8)
    axes[2].set_title("Résolution chroma verticale")
    axes[2].set_ylabel("lignes")

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(codes)
    fig.tight_layout()
    return _enregistrer(fig, dossier, "18", "bilan")


@figure("19", "Le piédestal du NTSC-M")
def figure_19_piedestal(dossier: Path) -> Path:
    rampe = mires.rampe(288, 384)
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.8))

    for code, couleur, libelle in (
        ("NTSC-M", ROUGE, "NTSC-M — piédestal 7,5 IRE"),
        ("NTSC-J", BLEU, "NTSC-J — sans piédestal"),
    ):
        resultat = encoder_decoder(rampe, Parametres(norme=code))
        ligne = resultat.norme.lignes_actives // 2
        signal = resultat.signal.partie_active(resultat.composite_emis)[ligne]
        axes[0].plot(np.linspace(0, 1, signal.size), signal * 100.0,
                     color=couleur, lw=1.8, label=libelle)
        axes[1].plot(np.linspace(0, 1, resultat.finale.shape[1]),
                     resultat.finale[144, :, 0], color=couleur, lw=1.8, label=libelle)

    axes[0].axhline(7.5, color=GRIS, ls=":", lw=1)
    axes[0].axhline(0.0, color=GRIS, ls="--", lw=1)
    axes[0].annotate("7,5 IRE", (0.02, 8), fontsize=8, color=GRIS)
    axes[0].annotate("niveau de suppression", (0.02, -3), fontsize=8, color=GRIS)
    axes[0].set_xlabel("position sur la rampe")
    axes[0].set_ylabel("niveau composite (IRE)")
    axes[0].set_title("Le piédestal remonte tout le signal image")
    axes[0].legend(loc="lower right")

    axes[1].set_xlabel("position sur la rampe")
    axes[1].set_ylabel("valeur restituée")
    axes[1].set_title(
        "Après décodage cohérent, l'image est identique — l'écart n'apparaît "
        "que sur un récepteur mal réglé"
    )
    fig.tight_layout()
    return _enregistrer(fig, dossier, "19", "piedestal")


@figure("20", "L'effet des primaires de 1953")
def figure_20_primaires(dossier: Path) -> Path:
    mire = mires.barres_couleur(240, 384)
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 2.8))
    _image(axes[0], mire, "Image d'origine, interprétée en sRGB")

    for ax, (code, titre) in zip(
        axes[1:],
        (("NTSC-1953", "Primaires NTSC 1953\n(gamut très large : tout paraît terne)"),
         ("PAL-BG", "Primaires EBU\n(quasi identiques à sRGB)")),
    ):
        resultat = encoder_decoder(
            mire, Parametres(norme=code, simuler_primaires=True,
                             taille_sortie=mire.shape[:2])
        )
        _image(ax, resultat.finale, titre)
    fig.tight_layout()
    return _enregistrer(fig, dossier, "20", "primaires")


# ===========================================================================

def principal(argv=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dossier", default=str(Path(__file__).parent / "figures"))
    analyseur.add_argument(
        "--seulement", default="", help="numéros de figures, séparés par des virgules"
    )
    arguments = analyseur.parse_args(argv)

    dossier = Path(arguments.dossier)
    dossier.mkdir(parents=True, exist_ok=True)

    choisies = (
        [n.strip().zfill(2) for n in arguments.seulement.split(",") if n.strip()]
        or sorted(_FIGURES)
    )

    total = time.perf_counter()
    for numero in choisies:
        fonction = _FIGURES.get(numero)
        if fonction is None:
            print(f"  figure {numero} inconnue")
            continue
        debut = time.perf_counter()
        chemin = fonction(dossier)
        print(f"  {numero}  {fonction.titre:52s} {time.perf_counter() - debut:5.1f} s"
              f"  → {chemin.name}")
    print(f"\nTerminé en {time.perf_counter() - total:.1f} s — {dossier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
