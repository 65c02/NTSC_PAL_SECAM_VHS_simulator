"""
Vérifie que les shaders temps réel disent la même chose que le simulateur.

Le simulateur `tvcolor` est la référence : il reconstruit le signal composite
sans compromis, et ses propres tests le comparent aux valeurs normatives. Les
shaders, eux, doivent faire le même trajet à une cadence de plusieurs centaines
d'images par seconde, ce qui impose des approximations. Ces tests mesurent
l'écart et le bornent.

Ils exigent un contexte OpenGL 3.3 : sans écran ni pilote, ils sont ignorés
plutôt que déclarés en échec.
"""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor import colorimetrie as col
from tvcolor import mires
from tvcolor.canal import ParametresCanal
from tvcolor.decodeur import ParametresDecodage
from tvcolor.pipeline import Parametres, encoder_decoder

pytest.importorskip("OpenGL", reason="PyOpenGL absent")

NORMES = ["NTSC-M", "PAL-BG", "SECAM-L"]
QUALITES = ["rapide", "normale", "haute"]


# ---------------------------------------------------------------------------
# Contexte partagé
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vue():
    """Une vue OpenGL prête à rendre, partagée par tous les tests du module."""
    from PyQt5 import QtGui, QtWidgets

    format_gl = QtGui.QSurfaceFormat()
    format_gl.setVersion(3, 3)
    format_gl.setProfile(QtGui.QSurfaceFormat.CoreProfile)
    format_gl.setSwapInterval(0)
    QtGui.QSurfaceFormat.setDefaultFormat(format_gl)

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    from lecteur.vue_gl import VueTelevision

    widget = VueTelevision()
    widget.resize(640, 480)
    widget.show()
    application.processEvents()

    if widget.image_rendue() is None and not widget.isVisible():
        pytest.skip("aucun contexte OpenGL disponible")

    yield widget

    widget.close()


def rendre(vue, image, **reglages) -> np.ndarray:
    """Fait passer une image sRGB flottante par les shaders. Retourne du sRGB flottant."""
    from lecteur.vue_gl import ParametresRendu

    parametres = ParametresRendu(animer=False, **reglages)
    vue.appliquer(parametres)
    vue.definir_image((np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
    rendu = vue.image_rendue()
    assert rendu is not None, "le rendu n'a rien produit"
    return rendu.astype(np.float64) / 255.0


def reference(image, norme, taille):
    """La même image dans le simulateur de référence."""
    params = Parametres(norme=norme, taille_sortie=taille)
    if norme.startswith("SECAM"):
        params.decodage = ParametresDecodage(separateur="notch")
    return encoder_decoder(image, params).finale


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("norme", NORMES)
@pytest.mark.parametrize("qualite", QUALITES)
def test_les_shaders_compilent_et_rendent(vue, norme, qualite):
    """Neuf combinaisons de norme et de qualité, neuf programmes à lier.

    Chaque changement de qualité recompile : les longueurs de noyau sont des
    constantes de compilation, pour que les boucles soient déroulées par le
    pilote plutôt que testées à chaque tour.
    """
    sortie = rendre(vue, mires.barres_couleur(288, 384), norme=norme, qualite=qualite)
    assert sortie.ndim == 3 and sortie.shape[2] == 3
    assert np.isfinite(sortie).all()
    assert sortie.max() > 0.5, "l'image rendue est noire"


# ---------------------------------------------------------------------------
# Accord avec le simulateur de référence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "norme,delta_median_max",
    [("NTSC-M", 1.5), ("PAL-BG", 1.5), ("SECAM-L", 8.0)],
)
def test_accord_avec_le_simulateur(vue, norme, delta_median_max):
    """Les shaders doivent retrouver ce que calcule `tvcolor`.

    Le seuil est plus large pour le SECAM, et pour des raisons identifiées :
    le shader n'applique pas les préaccentuations basse fréquence — sans effet
    à l'aller-retour, mais elles décalent légèrement les transitions — et son
    piège de sous-porteuse est un filtre à réponse finie là où la référence
    emploie un Butterworth récursif, hors de portée d'un shader.

    On écarte une bande aux bords : les deux chaînes ne traitent pas le
    hors-champ de la même façon, la référence codant la ligne entière avec sa
    suppression quand le shader s'arrête au bord de l'image.
    """
    mire = mires.barres_couleur(288, 384)
    obtenu = rendre(vue, mire, norme=norme)
    attendu = reference(mire, norme, obtenu.shape[:2])

    ecart = col.delta_e_76(col.srgb_vers_lab(obtenu), col.srgb_vers_lab(attendu))
    interieur = ecart[20:-20, 30:-30]

    assert np.median(interieur) < delta_median_max


@pytest.mark.parametrize("norme", ["NTSC-M", "PAL-BG"])
def test_une_image_grise_reste_grise(vue, norme):
    """Compatibilité noir et blanc : sans chrominance, pas de sous-porteuse.

    Le SECAM est exclu à dessein — sa porteuse est émise en permanence, et le
    test correspondant du simulateur vérifie justement qu'il en produit une.
    """
    hauteur, largeur = 288, 384
    gris = np.repeat(
        np.linspace(0.05, 0.95, largeur)[None, :, None], hauteur, 0
    ).repeat(3, 2)

    sortie = rendre(vue, gris, norme=norme)
    ecart = sortie.max(axis=2) - sortie.min(axis=2)
    assert np.median(ecart) < 0.02


# ---------------------------------------------------------------------------
# La physique des trois normes
# ---------------------------------------------------------------------------

FRACTION_JAUNE = 0.19
"""Position de la barre jaune dans la mire, en fraction de largeur.

Le choix de la barre n'est pas indifférent, et s'y tromper fait passer les
tests à côté du phénomène. La phase différentielle est, par définition,
proportionnelle au NIVEAU DE LUMINANCE : elle ne produit presque rien sur le
rouge (Y' = 0,22) ou le bleu (Y' = 0,09), et son plein effet sur le jaune
(Y' = 0,70) ou le cyan (Y' = 0,52). C'est d'ailleurs ce qu'on observe à
l'écran — les barres de Hanover strient le jaune et le cyan en laissant le
rouge et le bleu impassibles."""


def _teinte_moyenne(image, colonne):
    """Teinte moyenne d'une bande verticale, dans le plan (U, V)."""
    from tvcolor import matrices as mx

    zone = image[60:-60, colonne : colonne + 10]
    yuv = mx.rgb_vers_yuv(zone.reshape(-1, 3)).mean(axis=0)
    return np.rad2deg(np.arctan2(yuv[2], yuv[1])), float(np.hypot(yuv[1], yuv[2]))


def test_reponse_des_trois_normes_a_la_phase_differentielle(vue):
    """Le résultat central, retrouvé sur le GPU.

    Un seul et même défaut de canal, trois comportements : le NTSC voit sa
    teinte tourner, le PAL l'annule par sa ligne à retard, le SECAM l'ignore
    parce qu'un retard ne change pas une fréquence.
    """
    mire = mires.barres_couleur(288, 384)
    mesures = {}

    for norme in NORMES:
        sain = rendre(vue, mire, norme=norme)
        degrade = rendre(vue, mire, norme=norme, phase_differentielle=50.0)
        colonne = int(sain.shape[1] * FRACTION_JAUNE)
        teinte_saine, sat_saine = _teinte_moyenne(sain, colonne)
        teinte_degradee, sat_degradee = _teinte_moyenne(degrade, colonne)
        mesures[norme] = (
            abs(teinte_degradee - teinte_saine),
            sat_degradee / max(sat_saine, 1e-6),
        )

    assert mesures["NTSC-M"][0] > 4.0, "le NTSC devrait dériver en teinte"
    assert mesures["PAL-BG"][0] < 1.5, "la ligne à retard devrait annuler la dérive"
    assert mesures["SECAM-L"][0] < 1.5, "le SECAM devrait être insensible"

    # Le PAL paie l'annulation en saturation ; le SECAM ne paie rien.
    assert mesures["PAL-BG"][1] < 0.995
    assert mesures["SECAM-L"][1] == pytest.approx(1.0, abs=0.03)


def test_les_barres_de_hanover_apparaissent_sans_ligne_a_retard(vue):
    """PAL-S : l'erreur de teinte alterne d'une ligne à l'autre."""
    mire = mires.barres_couleur(288, 384)

    def striage(ligne_a_retard):
        from tvcolor import matrices as mx

        sortie = rendre(
            vue, mire, norme="PAL-BG",
            phase_differentielle=60.0, ligne_retard=ligne_a_retard,
        )
        colonne = int(sortie.shape[1] * FRACTION_JAUNE)
        bande = sortie[60:-60, colonne : colonne + 10].mean(axis=1)
        yuv = mx.rgb_vers_yuv(bande)
        teintes = np.rad2deg(np.arctan2(yuv[:, 2], yuv[:, 1]))
        return float(np.abs(np.diff(teintes)).mean())

    assert striage(ligne_a_retard=False) > 8.0
    assert striage(ligne_a_retard=True) < 2.0


def test_secam_garde_sa_sous_porteuse_sous_controle(vue):
    """La porteuse SECAM est permanente, mais le filtre cloche la contient.

    Sur une image blanche, le résidu que le piège laisse passer doit rester
    sous quelques niveaux sur 255 — au-delà, il dessinerait un motif visible
    en clair, ce qui n'a jamais été le cas d'un vrai récepteur.
    """
    blanc = np.ones((288, 384, 3))
    for qualite in QUALITES:
        sortie = rendre(vue, blanc, norme="SECAM-L", qualite=qualite)
        interieur = sortie[60:-60, 80:-80, 0]
        assert interieur.std() < 0.06, qualite
        assert interieur.mean() > 0.95, qualite


def test_le_peigne_et_le_rejecteur_ne_donnent_pas_la_meme_image(vue):
    """Deux séparateurs, deux compromis — donc deux images différentes."""
    mire = mires.piege_dot_crawl(288, 384)
    peigne = rendre(vue, mire, norme="NTSC-M", separateur=0)
    notch = rendre(vue, mire, norme="NTSC-M", separateur=1)
    assert np.abs(peigne - notch).mean() > 1e-3
