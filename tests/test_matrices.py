"""Vérifie le socle colorimétrique : d'où viennent les constantes des normes."""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor import colorimetrie as col
from tvcolor import matrices as mx
from tvcolor.constantes import FACTEUR_U, FACTEUR_V, KB, KG, KR


# ---------------------------------------------------------------------------
# Origine des constantes
# ---------------------------------------------------------------------------

def test_origine_des_coefficients_luma():
    """0,299 / 0,587 / 0,114 sortent des primaires NTSC 1953 sous illuminant C.

    Ce ne sont pas des nombres arbitraires : c'est la ligne « Y » de la matrice
    RGB→XYZ, c'est-à-dire la contribution de chaque primaire à la luminance
    photométrique. Les normalisateurs de 1953 les ont arrondis à trois
    décimales, et l'arrondi est resté gravé dans le marbre.
    """
    kr, kg, kb = col.PRIMAIRES["ntsc1953"].coefficients_luma()

    assert kr == pytest.approx(KR, abs=2e-3)
    assert kg == pytest.approx(KG, abs=2e-3)
    assert kb == pytest.approx(KB, abs=2e-3)
    assert kr + kg + kb == pytest.approx(1.0, abs=1e-12)


def test_les_coefficients_luma_ne_conviennent_plus_aux_primaires_modernes():
    """L'incohérence assumée de BT.470 : les coefficients n'ont pas suivi les tubes.

    PAL et SECAM utilisent les primaires EBU mais ont gardé les coefficients de
    luma de 1953. La « luma » transmise n'est donc pas la luminance des
    primaires réellement affichées — un écart que personne n'a jamais corrigé.
    """
    kr, kg, kb = col.PRIMAIRES["ebu"].coefficients_luma()
    assert abs(kg - KG) > 0.02   # le vert EBU pèse ≈ 0,61 et non 0,587


def test_deriver_facteurs_echelle():
    """0,492 et 0,877 découlent de la contrainte d'excursion [-1/3, +4/3]."""
    u, v = mx.deriver_facteurs_echelle()
    assert u == pytest.approx(FACTEUR_U, abs=5e-5)
    assert v == pytest.approx(FACTEUR_V, abs=5e-5)


def test_excursion_composite_des_couleurs_saturees():
    """Les six couleurs saturées touchent exactement les bornes -1/3 et +4/3.

    C'est la preuve que les facteurs d'échelle sont optimaux : aucune marge
    n'est gaspillée, aucune couleur ne déborde.
    """
    couleurs = {
        "rouge":   (1, 0, 0), "vert":    (0, 1, 0), "bleu":    (0, 0, 1),
        "cyan":    (0, 1, 1), "magenta": (1, 0, 1), "jaune":   (1, 1, 0),
    }
    minima, maxima = [], []
    for rgb in couleurs.values():
        y, u, v = mx.rgb_vers_yuv(np.array(rgb, dtype=float))
        amplitude = np.hypot(u, v)
        minima.append(y - amplitude)
        maxima.append(y + amplitude)

    assert min(minima) == pytest.approx(-1.0 / 3.0, abs=1e-3)
    assert max(maxima) == pytest.approx(+4.0 / 3.0, abs=1e-3)


# ---------------------------------------------------------------------------
# Cohérence des matrices avec les valeurs publiées
# ---------------------------------------------------------------------------

def test_matrice_yiq_contre_valeurs_normatives():
    """I et Q correspondent aux coefficients publiés dans toute la littérature."""
    attendu = np.array(
        [
            [0.299, 0.587, 0.114],
            [0.596, -0.274, -0.322],     # I
            [0.211, -0.523, 0.312],      # Q
        ]
    )
    assert np.allclose(mx.MATRICE_RGB_YIQ, attendu, atol=1e-3)


def test_matrice_yiq_inverse_contre_valeurs_normatives():
    attendu = np.array(
        [
            [1.000, 0.956, 0.621],
            [1.000, -0.272, -0.647],
            [1.000, -1.106, 1.703],
        ]
    )
    assert np.allclose(mx.MATRICE_YIQ_RGB, attendu, atol=2e-3)


def test_matrice_yuv_inverse_contre_valeurs_normatives():
    attendu = np.array(
        [
            [1.000, 0.000, 1.140],
            [1.000, -0.395, -0.581],
            [1.000, 2.032, 0.000],
        ]
    )
    assert np.allclose(mx.MATRICE_YUV_RGB, attendu, atol=2e-3)


def test_matrice_secam_contre_valeurs_normatives():
    """D'R = -1,902 (R'-Y') et D'B = +1,505 (B'-Y')."""
    attendu = np.array(
        [
            [0.299, 0.587, 0.114],
            [-1.333, 1.116, 0.217],      # D'R
            [-0.450, -0.883, 1.333],     # D'B
        ]
    )
    assert np.allclose(mx.MATRICE_RGB_YDRDB, attendu, atol=1e-3)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("niveau", [0.0, 0.18, 0.5, 0.75, 1.0])
def test_les_gris_ont_une_chrominance_nulle(niveau):
    """Sur un gris, toutes les différences de couleur s'annulent exactement.

    C'est la condition de compatibilité avec le noir et blanc : une image
    monochrome ne produit aucune sous-porteuse, donc aucun point coloré sur
    un récepteur couleur, et aucun moirage sur un récepteur N&B.
    """
    gris = np.full(3, niveau)
    for conversion in (mx.rgb_vers_yuv, mx.rgb_vers_yiq, mx.rgb_vers_ydrdb):
        y, c1, c2 = conversion(gris)
        assert y == pytest.approx(niveau, abs=1e-12)
        assert c1 == pytest.approx(0.0, abs=1e-12)
        assert c2 == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize(
    "aller,retour",
    [
        (mx.rgb_vers_yuv, mx.yuv_vers_rgb),
        (mx.rgb_vers_yiq, mx.yiq_vers_rgb),
        (mx.rgb_vers_ydrdb, mx.ydrdb_vers_rgb),
    ],
)
def test_aller_retour_matriciel_exact(aller, retour):
    """Le matriçage seul ne perd rien : c'est un changement de base inversible."""
    rng = np.random.default_rng(0)
    rgb = rng.random((64, 64, 3))
    assert np.allclose(retour(aller(rgb)), rgb, atol=1e-12)


def test_rotation_iq_est_une_isometrie():
    """La rotation de 33° conserve le module : la saturation est intacte."""
    rng = np.random.default_rng(1)
    u, v = rng.normal(size=1000), rng.normal(size=1000)
    i, q = mx.uv_vers_iq(u, v)
    assert np.allclose(np.hypot(u, v), np.hypot(i, q))
    u2, v2 = mx.iq_vers_uv(i, q)
    assert np.allclose(u, u2) and np.allclose(v, v2)


def test_conversion_uv_drdb_coherente_avec_le_matricage():
    rng = np.random.default_rng(2)
    rgb = rng.random((100, 3))
    _, u, v = mx.rgb_vers_yuv(rgb).T
    dr, db = mx.uv_vers_drdb(u, v)
    _, dr_direct, db_direct = mx.rgb_vers_ydrdb(rgb).T
    assert np.allclose(dr, dr_direct)
    assert np.allclose(db, db_direct)


# ---------------------------------------------------------------------------
# Colorimétrie
# ---------------------------------------------------------------------------

def test_aller_retour_srgb():
    v = np.linspace(0.0, 1.0, 257)
    assert np.allclose(col.lineaire_vers_srgb(col.srgb_vers_lineaire(v)), v, atol=1e-12)


def test_conversion_primaires_identite():
    rng = np.random.default_rng(3)
    rgb = rng.random((32, 32, 3))
    aller = col.convertir_primaires(rgb, "bt709", "ebu")
    retour = col.convertir_primaires(aller, "ebu", "bt709")
    assert np.allclose(retour, rgb, atol=1e-12)


def test_le_blanc_reste_blanc_apres_changement_de_primaires():
    """L'adaptation chromatique garantit que (1,1,1) reste (1,1,1)."""
    for cible in ("ntsc1953", "ebu", "smpte-c"):
        blanc = col.convertir_primaires(np.ones(3), "bt709", cible)
        assert np.allclose(blanc, 1.0, atol=1e-9), cible


def test_primaires_1953_plus_larges_que_bt709():
    """Réinterpréter du sRGB en NTSC 1953 désature : le gamut cible est plus grand.

    Un rouge sRGB pur, exprimé dans les primaires de 1953, ne demande plus
    100 % du rouge disponible — il en demande moins, plus un peu de vert et
    de bleu. D'où l'aspect délavé du « vrai » NTSC 1953.
    """
    rouge = col.convertir_primaires(np.array([1.0, 0.0, 0.0]), "bt709", "ntsc1953")
    assert rouge[0] < 0.95
    assert rouge[1] > 0.0 or rouge[2] > 0.0


def test_delta_e_nul_sur_image_identique():
    rng = np.random.default_rng(4)
    img = rng.random((16, 16, 3))
    lab = col.srgb_vers_lab(img)
    assert np.allclose(col.delta_e_76(lab, lab), 0.0)
